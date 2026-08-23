from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.core import Account, Asset, Exchange, Market, User
from app.db.models.trading import Fill, Order, OrderEvent
from app.schemas.exchange import OrderSide, OrderStatus, OrderType
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.execution.order_manager import OrderManager, OrderReconciliationRequiredError


@pytest_asyncio.fixture
async def seeded(db_session):
    user = User(email="trader@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    account = Account(
        user_id=user.id, name="Paper Account", mode="paper", starting_equity=Decimal("10000")
    )
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
async def test_market_buy_fills_and_records_events(db_session, seeded):
    manager = OrderManager(MockExchangeAdapter())
    order = await manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    assert order.status == OrderStatus.FILLED.value
    assert order.exchange_order_id is not None

    fills = await db_session.execute(select(Fill).where(Fill.order_id == order.id))
    fill_rows = list(fills.scalars())
    assert len(fill_rows) == 1
    assert fill_rows[0].quantity == Decimal("1")
    assert fill_rows[0].fee > 0

    events = await db_session.execute(
        select(OrderEvent.event_type).where(OrderEvent.order_id == order.id)
    )
    event_types = {row[0] for row in events}
    assert "CREATED" in event_types
    assert "FILLED" in event_types


@pytest.mark.asyncio
async def test_resubmitting_same_client_order_id_does_not_duplicate_fill(db_session, seeded):
    manager = OrderManager(MockExchangeAdapter())
    client_order_id = str(uuid.uuid4())

    first = await manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        client_order_id=client_order_id,
    )
    second = await manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        client_order_id=client_order_id,
    )
    assert first.id == second.id

    orders = await db_session.execute(
        select(Order).where(Order.client_order_id == client_order_id)
    )
    assert len(list(orders.scalars())) == 1

    fills = await db_session.execute(select(Fill).where(Fill.order_id == first.id))
    assert len(list(fills.scalars())) == 1


@pytest.mark.asyncio
async def test_resubmit_does_not_call_adapter_again(db_session, seeded):
    class _CountingAdapter(MockExchangeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.place_calls = 0

        async def place_market_buy(self, request):
            self.place_calls += 1
            return await super().place_market_buy(request)

    adapter = _CountingAdapter()
    manager = OrderManager(adapter)
    client_order_id = str(uuid.uuid4())

    for _ in range(3):
        await manager.submit_order(
            db_session,
            account_id=seeded["account"].id,
            asset_id=seeded["asset"].id,
            symbol=seeded["market"].symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            client_order_id=client_order_id,
        )

    assert adapter.place_calls == 1


@pytest.mark.asyncio
async def test_limit_order_stays_open_then_cancels(db_session, seeded):
    adapter = MockExchangeAdapter()
    manager = OrderManager(adapter)
    price = await adapter.get_market_price(seeded["market"].symbol)

    order = await manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=price * Decimal("0.5"),
    )
    assert order.status == OrderStatus.SUBMITTED.value

    cancelled = await manager.cancel_order(db_session, order, symbol=seeded["market"].symbol)
    assert cancelled.status == OrderStatus.CANCELLED.value

    fills = await db_session.execute(select(Fill).where(Fill.order_id == order.id))
    assert len(list(fills.scalars())) == 0


@pytest.mark.asyncio
async def test_stuck_order_with_no_exchange_id_requires_reconciliation(db_session, seeded):
    manager = OrderManager(MockExchangeAdapter())
    stuck = Order(
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        client_order_id=str(uuid.uuid4()),
        side="BUY",
        type="MARKET",
        quantity=Decimal("1"),
        status="NEW",
    )
    db_session.add(stuck)
    await db_session.commit()

    with pytest.raises(OrderReconciliationRequiredError):
        await manager.submit_order(
            db_session,
            account_id=seeded["account"].id,
            asset_id=seeded["asset"].id,
            symbol=seeded["market"].symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            client_order_id=stuck.client_order_id,
        )


@pytest.mark.asyncio
async def test_terminal_order_reconciliation_never_calls_adapter(db_session, seeded):
    class _CountingAdapter(MockExchangeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.status_calls = 0

        async def get_order_status(self, symbol, exchange_order_id):
            self.status_calls += 1
            return await super().get_order_status(symbol, exchange_order_id)

    adapter = _CountingAdapter()
    manager = OrderManager(adapter)
    client_order_id = str(uuid.uuid4())

    order = await manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        client_order_id=client_order_id,
    )
    assert order.status == OrderStatus.FILLED.value

    await manager.submit_order(
        db_session,
        account_id=seeded["account"].id,
        asset_id=seeded["asset"].id,
        symbol=seeded["market"].symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        client_order_id=client_order_id,
    )
    # A terminal order returns immediately without ever calling
    # get_order_status — no need to ask the exchange about something
    # already known to be finished.
    assert adapter.status_calls == 0


@pytest.mark.asyncio
async def test_concurrent_submissions_never_produce_two_fills(db_session, seeded):
    """Two real concurrent DB sessions racing to create the same
    client_order_id must never both place an order with the exchange."""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    adapter = MockExchangeAdapter()
    manager = OrderManager(adapter)
    client_order_id = str(uuid.uuid4())
    account_id = seeded["account"].id
    asset_id = seeded["asset"].id
    symbol = seeded["market"].symbol

    async def attempt():
        async with session_factory() as session:
            try:
                return await manager.submit_order(
                    session,
                    account_id=account_id,
                    asset_id=asset_id,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("1"),
                    client_order_id=client_order_id,
                )
            except OrderReconciliationRequiredError:
                return None

    try:
        await asyncio.gather(*(attempt() for _ in range(5)))
    finally:
        await engine.dispose()

    orders = await db_session.execute(
        select(Order).where(Order.client_order_id == client_order_id)
    )
    order_rows = list(orders.scalars())
    assert len(order_rows) == 1

    fills = await db_session.execute(select(Fill).where(Fill.order_id == order_rows[0].id))
    fill_rows = list(fills.scalars())
    assert len(fill_rows) <= 1  # never duplicated, even if not yet filled
