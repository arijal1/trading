"""Position Manager: turns fills into positions and re-evaluates exits.

Bridges the Order Manager (fills) and Phase 3's ExitEngine (which is
pure/stateless) to a persisted `Position` row, so exit state — the
trailing stop, the running high — survives between paper-trading ticks
rather than living only in memory for the duration of one process.

LONG-only, one open position per (account, asset) at a time, matching
`PositionExitState`'s scope (see app/services/execution/exit_engine.py).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trading import Fill, Order, Position, PositionEvent
from app.schemas.exit import ExitDecision, PositionExitState
from app.schemas.technical_analysis import TechnicalAnalysisResult
from app.services.execution.exit_engine import ExitEngine, advance_position_state


class PositionManager:
    def __init__(self, exit_engine: ExitEngine | None = None) -> None:
        self.exit_engine = exit_engine or ExitEngine()

    async def get_open_position(
        self, db: AsyncSession, *, account_id: uuid.UUID, asset_id: uuid.UUID
    ) -> Position | None:
        open_statuses = ("OPENING", "OPEN", "CAPITAL_RECOVERY_PENDING", "PROFIT_RUNNER", "CLOSING")
        result = await db.execute(
            select(Position).where(
                Position.account_id == account_id,
                Position.asset_id == asset_id,
                Position.status.in_(open_statuses),
            )
        )
        return result.scalar_one_or_none()

    async def apply_buy_fill(
        self,
        db: AsyncSession,
        *,
        order: Order,
        fill: Fill,
        stop_price: Decimal,
        take_profit_price: Decimal | None,
        trailing_stop_pct: Decimal | None,
        max_hold_seconds: int | None,
    ) -> Position:
        """Opens a new position, or adds to an existing one (weighted-average
        entry price; the stop/target/trailing config is refreshed to the
        new values rather than blended — a fresh add is a fresh risk decision).
        """
        position = await self.get_open_position(
            db, account_id=order.account_id, asset_id=order.asset_id
        )
        cost = fill.price * fill.quantity + fill.fee

        if position is None:
            position = Position(
                account_id=order.account_id,
                asset_id=order.asset_id,
                status="OPEN",
                initial_capital=cost,
                quantity=fill.quantity,
                avg_entry_price=fill.price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                trailing_stop_pct=trailing_stop_pct,
                highest_price_since_entry=fill.price,
                max_hold_seconds=max_hold_seconds,
            )
            db.add(position)
            await db.flush()
            db.add(
                PositionEvent(
                    position_id=position.id,
                    event_type="OPENED",
                    payload={
                        "quantity": str(fill.quantity),
                        "entry_price": str(fill.price),
                        "stop_price": str(stop_price),
                    },
                )
            )
        else:
            new_quantity = position.quantity + fill.quantity
            position.avg_entry_price = (
                position.avg_entry_price * position.quantity + fill.price * fill.quantity
            ) / new_quantity
            position.quantity = new_quantity
            position.initial_capital += cost
            position.stop_price = stop_price
            position.take_profit_price = take_profit_price
            position.trailing_stop_pct = trailing_stop_pct
            position.max_hold_seconds = max_hold_seconds
            db.add(
                PositionEvent(
                    position_id=position.id,
                    event_type="INCREASED",
                    payload={
                        "added_quantity": str(fill.quantity),
                        "fill_price": str(fill.price),
                        "new_avg_entry_price": str(position.avg_entry_price),
                    },
                )
            )

        await db.commit()
        await db.refresh(position)
        return position

    async def apply_sell_fill(
        self, db: AsyncSession, *, position: Position, fill: Fill, exit_trigger: str
    ) -> Position:
        """Reduces (or fully closes) a position by a sell fill's quantity."""
        if fill.quantity > position.quantity:
            raise ValueError(
                f"sell fill quantity {fill.quantity} exceeds position quantity {position.quantity}"
            )

        proceeds = fill.price * fill.quantity - fill.fee
        cost_basis_sold = position.avg_entry_price * fill.quantity
        realized_pnl = proceeds - cost_basis_sold

        position.quantity -= fill.quantity
        if position.quantity == 0:
            position.status = "CLOSED"
            event_type = "CLOSED"
        else:
            event_type = "REDUCED"

        db.add(
            PositionEvent(
                position_id=position.id,
                event_type=event_type,
                payload={
                    "sold_quantity": str(fill.quantity),
                    "fill_price": str(fill.price),
                    "realized_pnl": str(realized_pnl),
                    "exit_trigger": exit_trigger,
                    "remaining_quantity": str(position.quantity),
                },
            )
        )
        await db.commit()
        await db.refresh(position)
        return position

    async def advance_and_evaluate_exit(
        self,
        db: AsyncSession,
        position: Position,
        *,
        current_high: Decimal,
        current_low: Decimal,
        current_close: Decimal,
        current_ts: datetime,
        ta: TechnicalAnalysisResult | None = None,
    ) -> ExitDecision:
        """Ratchets the trailing stop (persisting it), then checks exit
        triggers. Never mutates position.status — callers apply the
        resulting sell fill via `apply_sell_fill`, keeping "what should
        happen" and "what did happen" separate.
        """
        highest_so_far = position.highest_price_since_entry or position.avg_entry_price
        state = PositionExitState(
            entry_price=position.avg_entry_price,
            stop_price=position.stop_price,
            take_profit_price=position.take_profit_price,
            trailing_stop_pct=position.trailing_stop_pct,
            highest_price_since_entry=highest_so_far,
            opened_at=position.created_at,
            max_hold_seconds=position.max_hold_seconds,
        )
        advanced = advance_position_state(state, current_high)
        if advanced.stop_price != position.stop_price:
            position.stop_price = advanced.stop_price
        if advanced.highest_price_since_entry != position.highest_price_since_entry:
            position.highest_price_since_entry = advanced.highest_price_since_entry
        await db.commit()
        await db.refresh(position)

        return self.exit_engine.evaluate(
            advanced,
            current_high=current_high,
            current_low=current_low,
            current_close=current_close,
            current_ts=current_ts,
            ta=ta,
        )
