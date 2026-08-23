from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.exchange import OrderRequest, OrderSide, OrderStatus, OrderType, Timeframe
from app.services.exchanges.base import OrderNotFoundError
from app.services.exchanges.mock import MockExchangeAdapter


@pytest.mark.asyncio
async def test_ohlcv_is_deterministic_across_calls():
    adapter = MockExchangeAdapter()
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + timedelta(hours=10)

    bars_1 = await adapter.get_ohlcv("BTC/USD", Timeframe.H1, since, until)
    bars_2 = await adapter.get_ohlcv("BTC/USD", Timeframe.H1, since, until)

    assert bars_1 == bars_2
    assert len(bars_1) == 10


@pytest.mark.asyncio
async def test_ohlcv_differs_by_symbol():
    adapter = MockExchangeAdapter()
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + timedelta(hours=5)

    btc_bars = await adapter.get_ohlcv("BTC/USD", Timeframe.H1, since, until)
    eth_bars = await adapter.get_ohlcv("ETH/USD", Timeframe.H1, since, until)

    assert [b.close for b in btc_bars] != [b.close for b in eth_bars]


@pytest.mark.asyncio
async def test_ohlcv_bars_are_internally_consistent():
    adapter = MockExchangeAdapter()
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + timedelta(hours=20)
    bars = await adapter.get_ohlcv("BTC/USD", Timeframe.H1, since, until)

    for bar in bars:
        assert bar.high >= bar.open
        assert bar.high >= bar.close
        assert bar.low <= bar.open
        assert bar.low <= bar.close
        assert bar.volume > 0


@pytest.mark.asyncio
async def test_market_buy_fills_immediately():
    adapter = MockExchangeAdapter()
    request = OrderRequest(
        client_order_id=str(uuid.uuid4()),
        symbol="BTC/USD",
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    result = await adapter.place_market_buy(request)
    assert result.status == OrderStatus.FILLED
    assert result.filled_quantity == Decimal("1")
    assert result.avg_fill_price is not None
    assert result.fee > 0


@pytest.mark.asyncio
async def test_limit_buy_below_market_stays_open_then_can_be_cancelled():
    adapter = MockExchangeAdapter()
    price = await adapter.get_market_price("BTC/USD")
    request = OrderRequest(
        client_order_id=str(uuid.uuid4()),
        symbol="BTC/USD",
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=price * Decimal("0.5"),
    )
    result = await adapter.place_limit_buy(request)
    assert result.status == OrderStatus.SUBMITTED

    open_orders = await adapter.get_open_orders("BTC/USD")
    assert any(o.exchange_order_id == result.exchange_order_id for o in open_orders)

    cancelled = await adapter.cancel_order("BTC/USD", result.exchange_order_id)
    assert cancelled.status == OrderStatus.CANCELLED

    open_orders_after = await adapter.get_open_orders("BTC/USD")
    assert not any(o.exchange_order_id == result.exchange_order_id for o in open_orders_after)


@pytest.mark.asyncio
async def test_get_order_status_unknown_id_raises():
    adapter = MockExchangeAdapter()
    with pytest.raises(OrderNotFoundError):
        await adapter.get_order_status("BTC/USD", "does-not-exist")


@pytest.mark.asyncio
async def test_account_status_never_allows_withdrawals():
    adapter = MockExchangeAdapter()
    status = await adapter.get_account_status()
    assert status.can_withdraw is False
