"""Abstract exchange/broker interface (brief Section 4).

Every method here returns one of the typed schemas in
`app.schemas.exchange` — never a raw exchange response — so the rest of
the system (market data engine, order manager, portfolio engine) is
exchange-agnostic and can run unmodified against the mock adapter, a
future real adapter, or the backtesting simulator's adapter.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from app.schemas.exchange import (
    AccountStatus,
    Balance,
    ExchangePosition,
    FeeSchedule,
    OHLCVBar,
    OrderBook,
    OrderRequest,
    OrderResult,
    Timeframe,
    TradingRules,
)


class ExchangeAdapterError(Exception):
    """Base class for adapter-level failures (network, rate limit, rejected order)."""


class OrderNotFoundError(ExchangeAdapterError):
    pass


class ExchangeAdapter(ABC):
    """Contract every exchange/broker integration must implement."""

    name: str

    @abstractmethod
    async def get_balance(self, asset: str | None = None) -> list[Balance]: ...

    @abstractmethod
    async def get_positions(self) -> list[ExchangePosition]: ...

    @abstractmethod
    async def get_market_price(self, symbol: str) -> Decimal: ...

    @abstractmethod
    async def get_order_book(self, symbol: str, depth: int = 20) -> OrderBook: ...

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        since: datetime,
        until: datetime,
    ) -> list[OHLCVBar]: ...

    @abstractmethod
    async def place_market_buy(self, request: OrderRequest) -> OrderResult: ...

    @abstractmethod
    async def place_market_sell(self, request: OrderRequest) -> OrderResult: ...

    @abstractmethod
    async def place_limit_buy(self, request: OrderRequest) -> OrderResult: ...

    @abstractmethod
    async def place_limit_sell(self, request: OrderRequest) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, symbol: str, exchange_order_id: str) -> OrderResult: ...

    @abstractmethod
    async def get_order_status(self, symbol: str, exchange_order_id: str) -> OrderResult: ...

    @abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]: ...

    @abstractmethod
    async def get_trading_rules(self, symbol: str) -> TradingRules: ...

    @abstractmethod
    async def get_symbols(self) -> list[str]: ...

    @abstractmethod
    async def get_fees(self, symbol: str) -> FeeSchedule: ...

    @abstractmethod
    async def get_account_status(self) -> AccountStatus: ...
