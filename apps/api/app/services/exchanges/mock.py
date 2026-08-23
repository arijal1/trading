"""Deterministic mock exchange adapter.

Used for local development, tests, and (later) paper trading before a
real, officially-supported exchange API is wired up. All data is
synthetic and computed as a pure function of (symbol, timeframe,
timestamp) — the same request always returns the same bars, which keeps
market-data sync idempotent and makes indicator tests reproducible. No
network calls, no scraping, nothing resembling a real venue's private API.
"""
from __future__ import annotations

import hashlib
import math
import uuid
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal

from app.schemas.exchange import (
    TIMEFRAME_SECONDS,
    AccountStatus,
    Balance,
    ExchangePosition,
    FeeSchedule,
    OHLCVBar,
    OrderBook,
    OrderBookLevel,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Timeframe,
    TradingRules,
)
from app.services.exchanges.base import ExchangeAdapter, OrderNotFoundError


def _seeded_unit_interval(*parts: str) -> float:
    """Deterministic pseudo-random float in [0, 1) from arbitrary string parts."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:16], 16) / 0xFFFFFFFFFFFFFFFF


def _base_price(symbol: str) -> Decimal:
    # Spread base prices across a believable range so different symbols
    # don't collide, e.g. "BTC/USD" -> low thousands.
    return Decimal(1 + _seeded_unit_interval(symbol, "base") * 999).quantize(Decimal("0.01"))


def _price_at(symbol: str, ts: datetime) -> Decimal:
    base = float(_base_price(symbol))
    seconds = ts.timestamp()
    # Slow sinusoidal drift plus small per-timestamp noise: bounded,
    # reproducible, and never crosses zero for any base price above ~1.
    drift = math.sin(seconds / 86_400.0) * base * 0.05
    noise = (_seeded_unit_interval(symbol, str(int(seconds))) - 0.5) * base * 0.01
    price = max(base + drift + noise, base * 0.5)
    return Decimal(str(round(price, 8)))


class MockExchangeAdapter(ExchangeAdapter):
    name = "mock"

    def __init__(self) -> None:
        self._orders: dict[str, OrderResult] = {}

    async def get_balance(self, asset: str | None = None) -> list[Balance]:
        balances = [
            Balance(asset="USD", free=Decimal("10000"), locked=Decimal("0")),
            Balance(asset="BTC", free=Decimal("0"), locked=Decimal("0")),
        ]
        if asset:
            return [b for b in balances if b.asset == asset]
        return balances

    async def get_positions(self) -> list[ExchangePosition]:
        return []

    async def get_market_price(self, symbol: str) -> Decimal:
        return _price_at(symbol, datetime.now(UTC))

    async def get_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        now = datetime.now(UTC)
        mid = _price_at(symbol, now)
        tick = mid * Decimal("0.0005")
        bids = [
            OrderBookLevel(price=mid - tick * (i + 1), quantity=Decimal("1"))
            for i in range(depth)
        ]
        asks = [
            OrderBookLevel(price=mid + tick * (i + 1), quantity=Decimal("1"))
            for i in range(depth)
        ]
        return OrderBook(symbol=symbol, ts=now, bids=bids, asks=asks)

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        since: datetime,
        until: datetime,
    ) -> list[OHLCVBar]:
        interval = TIMEFRAME_SECONDS[timeframe]
        bars: list[OHLCVBar] = []
        ts = since
        while ts < until:
            next_ts = datetime.fromtimestamp(ts.timestamp() + interval, tz=ts.tzinfo)
            open_price = _price_at(symbol, ts)
            close_price = _price_at(symbol, next_ts)
            jitter = abs(close_price - open_price) * Decimal("0.5") + open_price * Decimal("0.001")
            high = max(open_price, close_price) + jitter
            low = min(open_price, close_price) - jitter
            volume_seed = _seeded_unit_interval(symbol, str(timeframe), str(int(ts.timestamp())))
            volume = Decimal(str(round(1 + volume_seed * 100, 4)))
            bars.append(
                OHLCVBar(
                    ts=ts, open=open_price, high=high, low=low, close=close_price, volume=volume
                )
            )
            ts = next_ts
        return bars

    async def _fill_order(self, request: OrderRequest, fill_price: Decimal) -> OrderResult:
        fee_schedule = await self.get_fees(request.symbol)
        fee_pct = fee_schedule.taker_fee_pct
        fee = (request.quantity * fill_price * fee_pct / Decimal(100)).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )
        result = OrderResult(
            client_order_id=request.client_order_id,
            exchange_order_id=str(uuid.uuid4()),
            symbol=request.symbol,
            side=request.side,
            type=request.type,
            status=OrderStatus.FILLED,
            quantity=request.quantity,
            filled_quantity=request.quantity,
            avg_fill_price=fill_price,
            fee=fee,
            created_at=datetime.now(UTC),
        )
        self._orders[request.client_order_id] = result
        return result

    async def place_market_buy(self, request: OrderRequest) -> OrderResult:
        price = await self.get_market_price(request.symbol)
        return await self._fill_order(request, price)

    async def place_market_sell(self, request: OrderRequest) -> OrderResult:
        price = await self.get_market_price(request.symbol)
        return await self._fill_order(request, price)

    async def place_limit_buy(self, request: OrderRequest) -> OrderResult:
        price = await self.get_market_price(request.symbol)
        if request.limit_price is not None and request.limit_price >= price:
            return await self._fill_order(request, request.limit_price)
        return self._open_order(request)

    async def place_limit_sell(self, request: OrderRequest) -> OrderResult:
        price = await self.get_market_price(request.symbol)
        if request.limit_price is not None and request.limit_price <= price:
            return await self._fill_order(request, request.limit_price)
        return self._open_order(request)

    def _open_order(self, request: OrderRequest) -> OrderResult:
        result = OrderResult(
            client_order_id=request.client_order_id,
            exchange_order_id=str(uuid.uuid4()),
            symbol=request.symbol,
            side=request.side,
            type=request.type,
            status=OrderStatus.SUBMITTED,
            quantity=request.quantity,
            filled_quantity=Decimal("0"),
            created_at=datetime.now(UTC),
        )
        self._orders[request.client_order_id] = result
        return result

    async def cancel_order(self, symbol: str, exchange_order_id: str) -> OrderResult:
        for order in self._orders.values():
            if order.exchange_order_id == exchange_order_id:
                cancelled = order.model_copy(update={"status": OrderStatus.CANCELLED})
                self._orders[order.client_order_id] = cancelled
                return cancelled
        raise OrderNotFoundError(exchange_order_id)

    async def get_order_status(self, symbol: str, exchange_order_id: str) -> OrderResult:
        for order in self._orders.values():
            if order.exchange_order_id == exchange_order_id:
                return order
        raise OrderNotFoundError(exchange_order_id)

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]:
        open_statuses = {OrderStatus.NEW, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
        return [
            o
            for o in self._orders.values()
            if o.status in open_statuses and (symbol is None or o.symbol == symbol)
        ]

    async def get_trading_rules(self, symbol: str) -> TradingRules:
        return TradingRules(
            symbol=symbol,
            min_quantity=Decimal("0.0001"),
            max_quantity=Decimal("1000000"),
            quantity_step=Decimal("0.0001"),
            min_notional=Decimal("1"),
            price_step=Decimal("0.01"),
        )

    async def get_symbols(self) -> list[str]:
        return ["BTC/USD", "ETH/USD", "SOL/USD"]

    async def get_fees(self, symbol: str) -> FeeSchedule:
        return FeeSchedule(
            symbol=symbol, maker_fee_pct=Decimal("0.10"), taker_fee_pct=Decimal("0.15")
        )

    async def get_account_status(self) -> AccountStatus:
        return AccountStatus(account_id="mock-account", can_trade=True, can_withdraw=False)
