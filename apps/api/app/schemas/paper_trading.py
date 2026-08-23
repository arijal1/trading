from __future__ import annotations

import uuid
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from app.schemas.portfolio import RiskLimits
from app.schemas.profit import ProfitManagerConfig


class TickAction(StrEnum):
    OPENED = "OPENED"
    EXIT = "EXIT"
    CAPITAL_RECOVERED = "CAPITAL_RECOVERED"
    HOLD = "HOLD"
    SKIPPED_RISK = "SKIPPED_RISK"
    SKIPPED_SIZE = "SKIPPED_SIZE"
    NO_SIGNAL = "NO_SIGNAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class TickResult(BaseModel):
    action: TickAction
    detail: str
    order_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None


class PaperTradingConfig(BaseModel):
    risk_limits: RiskLimits = RiskLimits()
    profit_manager: ProfitManagerConfig = ProfitManagerConfig()
    strategy_weights: dict[str, float] | None = None
    buy_threshold: float = 25.0
    sell_threshold: float = -25.0
    risk_pct: Decimal = Decimal("0.01")
    atr_multiplier: Decimal = Decimal("2.0")
    trailing_stop_pct: Decimal | None = Decimal("0.05")
    take_profit_pct: Decimal | None = Decimal("0.10")
    max_hold_bars: int | None = 200
    min_position_value: Decimal = Decimal("10")
    ta_window_bars: int = 200
