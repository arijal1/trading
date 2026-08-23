from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class TraderMetricsResult(BaseModel):
    num_trades: int
    win_rate: float
    avg_return_pct: float
    max_drawdown_pct: float
    profit_factor: float
    avg_hold_time_seconds: float
    consistency_score: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=100)


class CopyTradeCandidateStatus(StrEnum):
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"


class CopyTradeCandidateDecision(BaseModel):
    status: CopyTradeCandidateStatus
    trader_score: float
    price_deviation_pct: Decimal
    latency_ms: int
    reason: str


class WeightedDirection(BaseModel):
    trader_id: str
    direction: str  # "BUY" or "SELL"
    weight: float  # the trader's score


class ConsensusResult(BaseModel):
    direction: str  # "BUY", "SELL", or "NO_TRADE"
    buy_score: float
    sell_score: float
    reason: str
