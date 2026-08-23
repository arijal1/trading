from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.core import Account, Asset, Exchange, Market, User
from app.db.models.trading import Fill
from app.schemas.exchange import OrderSide, OrderType
from app.services import system_state as system_state_service
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.execution.order_manager import OrderManager
from app.services.execution.position_manager import PositionManager
from app.services.portfolio.state_builder import build_portfolio_state, record_snapshot


@pytest_asyncio.fixture
async def seeded(db_session):
    user = User(email="trader@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    account = Account(user_id=user.id, name="Paper", mode="paper", starting_equity=Decimal("10000"))
    exchange = Exchange(name="Mock Exchange", adapter_type="mock")
    base = Asset(symbol="BTC")
    quote = Asset(symbol="USD")
    db_session.add_all([account, exchange, base, quote])
    await db_session.flush()

    market = Market(
        exchange_id=exchange.id, base_asset_id=base.id, quote_asset_id=quote.id, symbol="BTC/USD"
    )
    db_session.add(market)
    await db_session.commit()
    await db_session.refresh(account)
    await db_session.refresh(base)
    await db_session.refresh(market)
    return {"account": account, "asset": base, "market": market}


@pytest.mark.asyncio
async def test_no_activity_state_matches_starting_equity(db_session, seeded):
    state = await build_portfolio_state(db_session, account=seeded["account"], current_prices={})
    assert state.cash == Decimal("10000")
    assert state.equity == Decimal("10000")
    assert state.open_position_count == 0
    assert state.total_exposure == Decimal("0")
    assert state.is_emergency_stopped is False
    assert state.is_trading_halted is False


@pytest.mark.asyncio
async def test_cash_reflects_buy_fill_cost(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    order = await order_manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    fill_result = await db_session.execute(select(Fill).where(Fill.order_id == order.id))
    fill = fill_result.scalars().first()

    state = await build_portfolio_state(
        db_session, account=seeded["account"], current_prices={seeded["asset"].id: fill.price}
    )
    expected_cash = Decimal("10000") - (fill.price * fill.quantity + fill.fee)
    assert state.cash == expected_cash
    # No position row created yet (only an order/fill) -> no exposure counted.
    assert state.total_exposure == Decimal("0")
    assert state.equity == expected_cash


@pytest.mark.asyncio
async def test_open_position_counted_in_exposure_and_equity(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()
    order = await order_manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("2"),
    )
    fill_result = await db_session.execute(select(Fill).where(Fill.order_id == order.id))
    fill = fill_result.scalars().first()
    position = await position_manager.apply_buy_fill(
        db_session,
        order=order,
        fill=fill,
        stop_price=fill.price * Decimal("0.9"),
        take_profit_price=None,
        trailing_stop_pct=None,
        max_hold_seconds=None,
    )

    current_price = fill.price * Decimal("1.2")
    state = await build_portfolio_state(
        db_session, account=seeded["account"], current_prices={seeded["asset"].id: current_price}
    )
    assert state.open_position_count == 1
    assert state.total_exposure == position.quantity * current_price
    assert state.exposure_by_asset[str(seeded["asset"].id)] == position.quantity * current_price
    assert state.equity == state.cash + state.total_exposure


@pytest.mark.asyncio
async def test_snapshot_establishes_peak_equity_for_next_build(db_session, seeded):
    state = await build_portfolio_state(db_session, account=seeded["account"], current_prices={})
    await record_snapshot(db_session, account=seeded["account"], state=state)

    # A later build (lower equity, hypothetically) should still see the
    # earlier snapshot as its peak rather than resetting to current equity.
    later_state = await build_portfolio_state(
        db_session, account=seeded["account"], current_prices={}
    )
    assert later_state.peak_equity == state.equity


@pytest.mark.asyncio
async def test_emergency_stop_reflected_in_state(db_session, seeded):
    await system_state_service.emergency_stop(db_session, reason="test", actor="tester")
    state = await build_portfolio_state(db_session, account=seeded["account"], current_prices={})
    assert state.is_emergency_stopped is True
    assert state.is_trading_halted is True
