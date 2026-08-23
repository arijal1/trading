from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.core import Account, Asset, Exchange, Market, User
from app.db.models.trading import Fill, Order, Position, PositionEvent
from app.schemas.exchange import OrderSide, OrderType
from app.schemas.exit import ExitTrigger
from app.schemas.technical_analysis import IndicatorSnapshot, TechnicalAnalysisResult
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.execution.order_manager import OrderManager
from app.services.execution.position_manager import PositionManager


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


def _ta(**overrides) -> TechnicalAnalysisResult:
    defaults = dict(
        symbol="BTC/USD",
        timeframe="1h",
        bar_count=80,
        trend_direction="SIDEWAYS",
        trend_score=50.0,
        momentum_score=50.0,
        volume_score=50.0,
        volatility_score=50.0,
        breakout_score=0.0,
        reversal_probability=0.0,
        support_levels=[],
        resistance_levels=[],
        indicators=IndicatorSnapshot(close=100.0, volume=100.0),
    )
    defaults.update(overrides)
    return TechnicalAnalysisResult(**defaults)


async def _buy(db_session, seeded, order_manager, position_manager, *, quantity=Decimal("1")):
    order = await order_manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=quantity,
    )
    result = await db_session.execute(select(Fill).where(Fill.order_id == order.id))
    fill = result.scalars().first()
    position = await position_manager.apply_buy_fill(
        db_session,
        order=order,
        fill=fill,
        stop_price=fill.price * Decimal("0.9"),
        take_profit_price=fill.price * Decimal("1.2"),
        trailing_stop_pct=Decimal("0.05"),
        max_hold_seconds=None,
    )
    return order, fill, position


@pytest.mark.asyncio
async def test_buy_fill_opens_a_new_position(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()

    order, fill, position = await _buy(db_session, seeded, order_manager, position_manager)

    assert position.status == "OPEN"
    assert position.quantity == fill.quantity
    assert position.avg_entry_price == fill.price
    assert position.initial_capital == fill.price * fill.quantity + fill.fee

    events = await db_session.execute(
        select(PositionEvent.event_type).where(PositionEvent.position_id == position.id)
    )
    assert {row[0] for row in events} == {"OPENED"}


@pytest.mark.asyncio
async def test_second_buy_fill_adds_to_existing_position(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()

    _, first_fill, position_1 = await _buy(
        db_session, seeded, order_manager, position_manager, quantity=Decimal("1")
    )
    _, second_fill, position_2 = await _buy(
        db_session, seeded, order_manager, position_manager, quantity=Decimal("1")
    )

    assert position_1.id == position_2.id
    assert position_2.quantity == Decimal("2")
    expected_avg = (first_fill.price + second_fill.price) / 2
    assert position_2.avg_entry_price == expected_avg

    open_positions = await db_session.execute(
        select(Position).where(
            Position.account_id == seeded["account"].id, Position.status == "OPEN"
        )
    )
    assert len(list(open_positions.scalars())) == 1


@pytest.mark.asyncio
async def test_sell_fill_fully_closes_position(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()
    _, buy_fill, position = await _buy(db_session, seeded, order_manager, position_manager)

    sell_order = await order_manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=buy_fill.quantity,
    )
    result = await db_session.execute(select(Fill).where(Fill.order_id == sell_order.id))
    sell_fill = result.scalars().first()

    closed = await position_manager.apply_sell_fill(
        db_session, position=position, fill=sell_fill, exit_trigger="STOP_LOSS"
    )
    assert closed.status == "CLOSED"
    assert closed.quantity == Decimal("0")


@pytest.mark.asyncio
async def test_sell_fill_partial_reduces_without_closing(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()
    _, buy_fill, position = await _buy(
        db_session, seeded, order_manager, position_manager, quantity=Decimal("2")
    )

    sell_order = await order_manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    result = await db_session.execute(select(Fill).where(Fill.order_id == sell_order.id))
    sell_fill = result.scalars().first()

    reduced = await position_manager.apply_sell_fill(
        db_session, position=position, fill=sell_fill, exit_trigger="TAKE_PROFIT"
    )
    assert reduced.status == "OPEN"
    assert reduced.quantity == Decimal("1")


@pytest.mark.asyncio
async def test_sell_fill_exceeding_quantity_raises(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()
    _, buy_fill, position = await _buy(db_session, seeded, order_manager, position_manager)

    phantom_order = Order(
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        client_order_id="phantom",
        side="SELL",
        type="MARKET",
        quantity=Decimal("999"),
        status="FILLED",
    )
    db_session.add(phantom_order)
    await db_session.flush()
    phantom_fill = Fill(
        order_id=phantom_order.id, price=Decimal("100"), quantity=Decimal("999"), fee=Decimal("1")
    )

    with pytest.raises(ValueError, match="exceeds position quantity"):
        await position_manager.apply_sell_fill(
            db_session, position=position, fill=phantom_fill, exit_trigger="STOP_LOSS"
        )


@pytest.mark.asyncio
async def test_advance_and_evaluate_exit_persists_ratcheted_stop(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()
    _, buy_fill, position = await _buy(db_session, seeded, order_manager, position_manager)

    # +10%: enough to ratchet the trailing stop, but below the _buy
    # helper's +20% take-profit target, so only the trailing-stop
    # mechanic under test is in play.
    higher_price = buy_fill.price * Decimal("1.1")
    # Bar stays near its high (low = 99% of high) so it doesn't dip back
    # through the newly-ratcheted trailing stop within the same bar.
    near_high_low = higher_price * Decimal("0.99")
    decision = await position_manager.advance_and_evaluate_exit(
        db_session,
        position,
        current_high=higher_price,
        current_low=near_high_low,
        current_close=higher_price,
        current_ts=datetime.now(UTC),
        ta=_ta(trend_direction="UPTREND", momentum_score=70.0),
    )
    assert decision.should_exit is False
    assert position.highest_price_since_entry == higher_price
    # 5% trailing stop off the new high should have ratcheted upward
    # above the original static stop.
    assert position.stop_price > buy_fill.price * Decimal("0.9")

    reloaded = await db_session.execute(select(Position).where(Position.id == position.id))
    assert reloaded.scalar_one().stop_price == position.stop_price


@pytest.mark.asyncio
async def test_advance_and_evaluate_exit_triggers_max_hold_time(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()
    _, buy_fill, position = await _buy(db_session, seeded, order_manager, position_manager)
    position.max_hold_seconds = 60
    await db_session.commit()

    decision = await position_manager.advance_and_evaluate_exit(
        db_session,
        position,
        current_high=buy_fill.price,
        current_low=buy_fill.price,
        current_close=buy_fill.price,
        current_ts=position.created_at + timedelta(hours=1),
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.MAX_HOLD_TIME
