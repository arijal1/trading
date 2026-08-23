"""Builds a DB-backed `PortfolioState` for the live/paper PortfolioRiskEngine
(brief Section 21), and records the `portfolio_snapshots` history that
peak/day-start/week-start equity are read back from on the next call.

Cash is reconstructed from the fill ledger rather than stored as a mutable
balance column — `starting_equity` plus every buy/sell fill's cost or
proceeds is the one source of truth, so it can never drift out of sync
with what orders actually did.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Account
from app.db.models.portfolio import PortfolioSnapshot
from app.db.models.trading import Fill, Order, Position
from app.schemas.portfolio import PortfolioState
from app.services import system_state as system_state_service

_OPEN_STATUSES = ("OPENING", "OPEN", "CAPITAL_RECOVERY_PENDING", "PROFIT_RUNNER", "CLOSING")


async def _compute_cash(db: AsyncSession, account: Account) -> Decimal:
    net_signed = await db.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Order.side == "BUY", -(Fill.price * Fill.quantity + Fill.fee)),
                        else_=(Fill.price * Fill.quantity - Fill.fee),
                    )
                ),
                0,
            )
        )
        .select_from(Fill)
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account.id)
    )
    return account.starting_equity + Decimal(net_signed)


async def build_portfolio_state(
    db: AsyncSession, *, account: Account, current_prices: dict[uuid.UUID, Decimal]
) -> PortfolioState:
    cash = await _compute_cash(db, account)

    open_positions_result = await db.execute(
        select(Position).where(
            Position.account_id == account.id, Position.status.in_(_OPEN_STATUSES)
        )
    )
    open_positions = list(open_positions_result.scalars())

    exposure_by_asset: dict[str, Decimal] = {}
    total_exposure = Decimal(0)
    for position in open_positions:
        price = current_prices.get(position.asset_id, position.avg_entry_price)
        value = position.quantity * price
        exposure_by_asset[str(position.asset_id)] = value
        total_exposure += value

    equity = cash + total_exposure
    now = datetime.now(UTC)

    peak_equity = await db.scalar(
        select(func.coalesce(func.max(PortfolioSnapshot.equity), equity)).where(
            PortfolioSnapshot.account_id == account.id
        )
    )
    peak_equity = max(Decimal(peak_equity), equity)

    day_start_equity = await _first_snapshot_equity_since(
        db, account.id, now.replace(hour=0, minute=0, second=0, microsecond=0), default=equity
    )
    week_start = now - timedelta(days=now.isoweekday() - 1)
    week_start_equity = await _first_snapshot_equity_since(
        db,
        account.id,
        week_start.replace(hour=0, minute=0, second=0, microsecond=0),
        default=equity,
    )

    system_state = await system_state_service.get_or_create_state(db)

    return PortfolioState(
        equity=equity,
        cash=cash,
        open_position_count=len(open_positions),
        exposure_by_asset=exposure_by_asset,
        total_exposure=total_exposure,
        peak_equity=peak_equity,
        day_start_equity=day_start_equity,
        week_start_equity=week_start_equity,
        is_emergency_stopped=system_state.is_emergency_stopped,
        is_trading_halted=system_state.is_trading_halted,
    )


async def _first_snapshot_equity_since(
    db: AsyncSession, account_id: uuid.UUID, since: datetime, *, default: Decimal
) -> Decimal:
    result = await db.scalar(
        select(PortfolioSnapshot.equity)
        .where(PortfolioSnapshot.account_id == account_id, PortfolioSnapshot.snapshot_at >= since)
        .order_by(PortfolioSnapshot.snapshot_at.asc())
        .limit(1)
    )
    return Decimal(result) if result is not None else default


async def record_snapshot(db: AsyncSession, *, account: Account, state: PortfolioState) -> None:
    db.add(
        PortfolioSnapshot(
            account_id=account.id,
            equity=state.equity,
            cash=state.cash,
            exposure=state.total_exposure,
            unrealized_pnl=state.equity - account.starting_equity,
            # Tracked per-position via profit_locked, not summarized here yet.
            realized_pnl=Decimal(0),
            drawdown=(
                (state.peak_equity - state.equity) / state.peak_equity
                if state.peak_equity > 0
                else Decimal(0)
            ),
        )
    )
    await db.commit()
