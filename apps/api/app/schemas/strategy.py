from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SignalDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class StrategySignal(BaseModel):
    strategy: str
    direction: SignalDirection
    strength: float = Field(ge=0, le=100)  # how strong this individual signal is
    reason_codes: list[str] = Field(default_factory=list)


class AggregateDecision(BaseModel):
    direction: SignalDirection
    score: float  # -100..100 weighted signed score across strategies
    confidence: float = Field(ge=0, le=1)
    signals: list[StrategySignal]
    reason_codes: list[str] = Field(default_factory=list)
