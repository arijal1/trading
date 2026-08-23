"""Paper trading endpoints (Phase 4, `docs/API_DESIGN.md`'s "Planned" table).

Accounts are created directly in the DB for now, matching the same
"no onboarding endpoint yet" pattern already established for
markets/exchanges in Phase 2 (see `app/api/v1/endpoints/market_data.py`).
Every route below takes `account_id` as a path parameter rather than
deriving it from an authenticated session, since auth lands in Phase 5+.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Account, Market
from app.db.models.trading import Fill, Order, Position
from app.db.session import get_db
from app.schemas.account_api import (
    AccountResponse,
    OrderResponse,
    PaperTickRequest,
    PaperTickResponse,
    PositionResponse,
    TradeResponse,
)
from app.schemas.portfolio import PortfolioState
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.execution.paper_trading_session import PaperTradingSession
from app.services.portfolio.state_builder import build_portfolio_state

router = APIRouter(tags=["paper-trading"])

# Same Phase-2 scope note as market_data.py/backtests.py: only a mock
# adapter exists. A dedicated session is fine here since paper trading is
# stateless across ticks (all state lives in the DB), so nothing needs to
# survive between requests inside this object.
_adapter = MockExchangeAdapter()
_session = PaperTradingSession(_adapter)


async def _get_account_or_404(db: AsyncSession, account_id: uuid.UUID) -> Account:
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)) -> list[AccountResponse]:
    result = await db.execute(select(Account).order_by(Account.created_at.desc()))
    return [
        AccountResponse(
            id=a.id,
            user_id=a.user_id,
            name=a.name,
            mode=a.mode,
            base_currency=a.base_currency,
            starting_equity=a.starting_equity,
            created_at=a.created_at,
        )
        for a in result.scalars()
    ]


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> AccountResponse:
    account = await _get_account_or_404(db, account_id)
    return AccountResponse(
        id=account.id,
        user_id=account.user_id,
        name=account.name,
        mode=account.mode,
        base_currency=account.base_currency,
        starting_equity=account.starting_equity,
        created_at=account.created_at,
    )


@router.get("/accounts/{account_id}/portfolio", response_model=PortfolioState)
async def get_portfolio(
    account_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> PortfolioState:
    account = await _get_account_or_404(db, account_id)

    open_positions_result = await db.execute(
        select(Position).where(
            Position.account_id == account.id,
            Position.status.in_(("OPENING", "OPEN", "CAPITAL_RECOVERY_PENDING", "PROFIT_RUNNER")),
        )
    )
    open_positions = list(open_positions_result.scalars())
    # No live-price feed to mark against outside a tick: value open
    # positions at their own average entry price, same as an untouched
    # PortfolioState would before any current_prices are supplied.
    current_prices = {p.asset_id: p.avg_entry_price for p in open_positions}

    return await build_portfolio_state(db, account=account, current_prices=current_prices)


@router.get("/accounts/{account_id}/positions", response_model=list[PositionResponse])
async def list_positions(
    account_id: uuid.UUID, status: str | None = None, db: AsyncSession = Depends(get_db)
) -> list[PositionResponse]:
    await _get_account_or_404(db, account_id)
    stmt = select(Position).where(Position.account_id == account_id)
    if status is not None:
        stmt = stmt.where(Position.status == status)
    stmt = stmt.order_by(Position.created_at.desc())
    result = await db.execute(stmt)
    return [
        PositionResponse(
            id=p.id,
            asset_id=p.asset_id,
            status=p.status,
            initial_capital=p.initial_capital,
            quantity=p.quantity,
            avg_entry_price=p.avg_entry_price,
            capital_recovered=p.capital_recovered,
            profit_locked=p.profit_locked,
            stop_price=p.stop_price,
            take_profit_price=p.take_profit_price,
            trailing_stop_pct=p.trailing_stop_pct,
            highest_price_since_entry=p.highest_price_since_entry,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in result.scalars()
    ]


@router.get("/accounts/{account_id}/orders", response_model=list[OrderResponse])
async def list_orders(
    account_id: uuid.UUID, limit: int = 100, db: AsyncSession = Depends(get_db)
) -> list[OrderResponse]:
    await _get_account_or_404(db, account_id)
    limit = max(1, min(limit, 1000))
    result = await db.execute(
        select(Order)
        .where(Order.account_id == account_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return [
        OrderResponse(
            id=o.id,
            client_order_id=o.client_order_id,
            exchange_order_id=o.exchange_order_id,
            asset_id=o.asset_id,
            side=o.side,
            type=o.type,
            quantity=o.quantity,
            limit_price=o.limit_price,
            status=o.status,
            error=o.error,
            created_at=o.created_at,
        )
        for o in result.scalars()
    ]


@router.get("/accounts/{account_id}/trades", response_model=list[TradeResponse])
async def list_trades(
    account_id: uuid.UUID, limit: int = 100, db: AsyncSession = Depends(get_db)
) -> list[TradeResponse]:
    await _get_account_or_404(db, account_id)
    limit = max(1, min(limit, 1000))
    result = await db.execute(
        select(Fill)
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account_id)
        .order_by(Fill.filled_at.desc())
        .limit(limit)
    )
    return [
        TradeResponse(
            id=f.id,
            order_id=f.order_id,
            price=f.price,
            quantity=f.quantity,
            fee=f.fee,
            slippage=f.slippage,
            filled_at=f.filled_at,
        )
        for f in result.scalars()
    ]


@router.post("/accounts/{account_id}/paper/tick", response_model=PaperTickResponse)
async def run_paper_tick(
    account_id: uuid.UUID, request: PaperTickRequest, db: AsyncSession = Depends(get_db)
) -> PaperTickResponse:
    account = await _get_account_or_404(db, account_id)
    if account.mode != "paper":
        raise HTTPException(
            status_code=422, detail=f"account mode is '{account.mode}', not 'paper'"
        )

    market = await db.get(Market, request.market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="market not found")

    result = await _session.run_tick(
        db, account=account, market=market, timeframe=request.timeframe
    )
    return PaperTickResponse(result=result)
