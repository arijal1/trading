from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.core import Account, Asset, Exchange, Market, User
from app.db.models.trading import Fill, Order
from app.schemas.exchange import OrderSide, OrderType
from app.schemas.profit import ProfitManagerConfig
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.execution.order_manager import OrderManager
from app.services.execution.position_manager import PositionManager
from app.services.portfolio.profit_manager import (
    apply_capital_recovery_fill,
    evaluate_capital_recovery,
)


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
async def test_full_capital_recovery_lifecycle(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()

    buy_order = await order_manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    buy_fill = (
        await db_session.execute(select(Fill).where(Fill.order_id == buy_order.id))
    ).scalars().first()

    position = await position_manager.apply_buy_fill(
        db_session,
        order=buy_order,
        fill=buy_fill,
        stop_price=buy_fill.price * Decimal("0.9"),
        take_profit_price=buy_fill.price * Decimal("1.5"),
        trailing_stop_pct=None,
        max_hold_seconds=None,
    )
    assert position.status == "OPEN"

    # Price rallies well past the recovery threshold.
    current_price = buy_fill.price * Decimal("1.4")
    config = ProfitManagerConfig(max_slippage_percent=Decimal("0"), min_position_value=Decimal("1"))
    proposal = evaluate_capital_recovery(
        position, current_price=current_price, fee_pct=Decimal("0"), config=config
    )
    assert proposal.should_recover is True
    assert proposal.sell_quantity < position.quantity

    sell_order = await order_manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=proposal.sell_quantity,
    )
    sell_fill = (
        await db_session.execute(select(Fill).where(Fill.order_id == sell_order.id))
    ).scalars().first()

    runner = await apply_capital_recovery_fill(
        db_session, position=position, fill=sell_fill, config=config
    )

    assert runner.status == "PROFIT_RUNNER"
    assert runner.quantity > 0
    assert runner.quantity < Decimal("10")
    assert runner.capital_recovered > 0
    # The remainder is never given a fixed take-profit target back —
    # it's managed by trailing stop / structure from here.
    assert runner.take_profit_price is None
    assert runner.trailing_stop_pct == config.trailing_stop_percent


@pytest.mark.asyncio
async def test_capital_recovery_never_closes_the_position_outright(db_session, seeded):
    order_manager = OrderManager(MockExchangeAdapter())
    position_manager = PositionManager()

    buy_order = await order_manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )
    buy_fill = (
        await db_session.execute(select(Fill).where(Fill.order_id == buy_order.id))
    ).scalars().first()
    position = await position_manager.apply_buy_fill(
        db_session,
        order=buy_order,
        fill=buy_fill,
        stop_price=buy_fill.price * Decimal("0.9"),
        take_profit_price=None,
        trailing_stop_pct=None,
        max_hold_seconds=None,
    )

    current_price = buy_fill.price * Decimal("2.0")
    config = ProfitManagerConfig(max_slippage_percent=Decimal("0"), min_position_value=Decimal("1"))
    proposal = evaluate_capital_recovery(
        position, current_price=current_price, fee_pct=Decimal("0"), config=config
    )
    assert proposal.should_recover is True

    order = Order(
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        client_order_id="recovery-sell",
        side="SELL",
        type="MARKET",
        quantity=proposal.sell_quantity,
        status="FILLED",
    )
    db_session.add(order)
    await db_session.flush()
    fill = Fill(
        order_id=order.id,
        price=current_price,
        quantity=proposal.sell_quantity,
        fee=Decimal("0"),
    )

    runner = await apply_capital_recovery_fill(
        db_session, position=position, fill=fill, config=config
    )
    assert runner.status != "CLOSED"
    assert runner.quantity > 0
