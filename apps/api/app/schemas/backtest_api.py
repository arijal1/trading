from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.backtest import BacktestConfig, BacktestResult
from app.schemas.exchange import Timeframe


class BacktestRunRequest(BaseModel):
    market_id: uuid.UUID
    timeframe: Timeframe = Timeframe.H1
    candle_limit: int = Field(default=500, ge=50, le=5000)
    config: BacktestConfig = Field(default_factory=BacktestConfig)


class BacktestRecordResponse(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    status: str
    date_range: dict
    result: BacktestResult
    created_at: datetime
