from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class AssetResponse(BaseModel):
    id: uuid.UUID
    symbol: str
    chain: str | None
    contract_address: str | None
    risk_score: int | None


class MarketResponse(BaseModel):
    id: uuid.UUID
    exchange_id: uuid.UUID
    exchange_name: str
    symbol: str
    base_asset_symbol: str
    quote_asset_symbol: str


class CandleResponse(BaseModel):
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class SyncCandlesResponse(BaseModel):
    requested_count: int
    already_stored_count: int
    fetched_count: int
    inserted_count: int
    gap_count: int
    adapter_called: bool
