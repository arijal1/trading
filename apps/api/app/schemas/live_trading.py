from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class GuardCheck(StrEnum):
    """Every condition that must hold before a live order may be placed.

    Named individually (rather than a single boolean) so a refusal always
    says exactly which gate closed — the brief's Section 39 requires the
    guardrails be auditable, not just effective.
    """

    TRADING_MODE_IS_LIVE = "TRADING_MODE_IS_LIVE"
    LIVE_TRADING_ENABLED = "LIVE_TRADING_ENABLED"
    TRADING_CONFIRMATION = "TRADING_CONFIRMATION"
    VALID_EXCHANGE_CREDENTIALS = "VALID_EXCHANGE_CREDENTIALS"
    RISK_LIMITS_VALID = "RISK_LIMITS_VALID"
    EMERGENCY_STOP_AVAILABLE = "EMERGENCY_STOP_AVAILABLE"
    NOT_EMERGENCY_STOPPED = "NOT_EMERGENCY_STOPPED"
    NOT_TRADING_HALTED = "NOT_TRADING_HALTED"
    WITHDRAWALS_DISABLED = "WITHDRAWALS_DISABLED"
    WITHIN_MAX_LIVE_CAPITAL = "WITHIN_MAX_LIVE_CAPITAL"
    ACCOUNT_IS_LIVE_MODE = "ACCOUNT_IS_LIVE_MODE"


class LiveTradingDecision(BaseModel):
    allowed: bool
    failed_checks: list[GuardCheck] = Field(default_factory=list)
    reason: str

    @property
    def summary(self) -> str:
        if self.allowed:
            return "live trading permitted"
        return f"live trading refused: {self.reason}"


class LiveReadinessResponse(BaseModel):
    """Operator-facing view of why live trading is or isn't currently possible."""

    allowed: bool
    failed_checks: list[GuardCheck]
    reason: str
    max_live_capital: Decimal
