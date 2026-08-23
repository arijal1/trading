"""Response contracts for the read-only account/portfolio/positions/orders/
trades endpoints (Phase 4, `docs/API_DESIGN.md`'s "Planned" table).

Accounts are created directly in the DB for now, matching the same
pattern already established for markets/exchanges in Phase 2 — there is
no account-onboarding endpoint yet (real auth/user-management lands in
Phase 5+, per `docs/API_DESIGN.md`'s header note).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.exchange import Timeframe
from app.schemas.paper_trading import TickResult


class AccountResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    mode: str
    base_currency: str
    starting_equity: Decimal
    created_at: datetime


class PositionResponse(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    status: str
    initial_capital: Decimal
    quantity: Decimal
    avg_entry_price: Decimal
    capital_recovered: Decimal
    profit_locked: Decimal
    stop_price: Decimal | None
    take_profit_price: Decimal | None
    trailing_stop_pct: Decimal | None
    highest_price_since_entry: Decimal | None
    created_at: datetime
    updated_at: datetime


class OrderResponse(BaseModel):
    id: uuid.UUID
    client_order_id: str
    exchange_order_id: str | None
    asset_id: uuid.UUID
    side: str
    type: str
    quantity: Decimal
    limit_price: Decimal | None
    status: str
    error: str | None
    created_at: datetime


class TradeResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    price: Decimal
    quantity: Decimal
    fee: Decimal
    slippage: Decimal | None
    filled_at: datetime


class PaperTickRequest(BaseModel):
    market_id: uuid.UUID
    timeframe: Timeframe = Timeframe.H1


class PaperTickResponse(BaseModel):
    result: TickResult
