"""Data contracts exchanged with an ExchangeAdapter (brief Section 4).

Every adapter — mock or real — speaks these types. Nothing downstream
(market data engine, order manager) ever sees an exchange's native
response shape directly; that keeps the execution layer exchange-agnostic
per the brief's requirement.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 5 * 60,
    Timeframe.M15: 15 * 60,
    Timeframe.M30: 30 * 60,
    Timeframe.H1: 60 * 60,
    Timeframe.H4: 4 * 60 * 60,
    Timeframe.D1: 24 * 60 * 60,
}


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OHLCVBar(BaseModel):
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class OrderBookLevel(BaseModel):
    price: Decimal
    quantity: Decimal


class OrderBook(BaseModel):
    symbol: str
    ts: datetime
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]


class Balance(BaseModel):
    asset: str
    free: Decimal
    locked: Decimal


class ExchangePosition(BaseModel):
    symbol: str
    quantity: Decimal
    avg_entry_price: Decimal


class TradingRules(BaseModel):
    symbol: str
    min_quantity: Decimal
    max_quantity: Decimal
    quantity_step: Decimal
    min_notional: Decimal
    price_step: Decimal


class FeeSchedule(BaseModel):
    symbol: str
    maker_fee_pct: Decimal
    taker_fee_pct: Decimal


class AccountStatus(BaseModel):
    account_id: str
    can_trade: bool
    can_withdraw: bool  # live-trading credentials must have this False (Section 33/39)


class OrderRequest(BaseModel):
    client_order_id: str
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None


class OrderResult(BaseModel):
    client_order_id: str
    exchange_order_id: str
    symbol: str
    side: OrderSide
    type: OrderType
    status: OrderStatus
    quantity: Decimal
    filled_quantity: Decimal
    avg_fill_price: Decimal | None = None
    fee: Decimal = Decimal(0)
    created_at: datetime
