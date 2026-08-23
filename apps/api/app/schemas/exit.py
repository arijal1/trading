from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class ExitTrigger(StrEnum):
    NONE = "NONE"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    MAX_HOLD_TIME = "MAX_HOLD_TIME"
    TREND_REVERSAL = "TREND_REVERSAL"
    MOMENTUM_FAILURE = "MOMENTUM_FAILURE"


class PositionExitState(BaseModel):
    """Mutable per-position tracking the exit engine advances bar by bar.

    LONG-only for now — this is a spot-buy/spot-sell platform per the
    brief's scope; short positions are not modeled.
    """

    side: Literal["LONG"] = "LONG"
    entry_price: Decimal
    stop_price: Decimal
    take_profit_price: Decimal | None = None
    trailing_stop_pct: Decimal | None = None
    highest_price_since_entry: Decimal
    opened_at: datetime
    max_hold_seconds: int | None = None


class ExitDecision(BaseModel):
    should_exit: bool
    trigger: ExitTrigger
    exit_price: Decimal | None = None
    reason: str
    # True for stop-loss/trailing-stop/take-profit: these are resting
    # orders that fill the moment the bar's high/low crosses them, i.e.
    # within the same (already-closed, fully-known) bar being evaluated.
    # False for signal-based exits (max hold time, trend reversal,
    # momentum failure): those are decisions made from the bar's close,
    # like entries, and fill at the next bar's open to avoid look-ahead.
    fills_intrabar: bool = False
