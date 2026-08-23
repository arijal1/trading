from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class ProfitManagerConfig(BaseModel):
    """Mirrors the Section 2 settings in app/core/config.py, kept as an
    explicit small model here so ProfitManager's core logic stays a pure,
    easily-testable function rather than depending on global Settings.
    """

    capital_recovery_enabled: bool = True
    capital_recovery_target: Decimal = Decimal("1.00")  # fraction of initial_capital to recover
    min_profit_before_recovery: Decimal = Decimal("0.15")  # unrealized profit fraction to trigger
    profit_position_enabled: bool = True
    trailing_stop_percent: Decimal = Decimal("0.05")
    min_position_value: Decimal = Decimal("10")
    max_slippage_percent: Decimal = Decimal("0.01")


class CapitalRecoveryProposal(BaseModel):
    should_recover: bool = False
    sell_quantity: Decimal = Decimal(0)
    estimated_proceeds: Decimal = Decimal(0)
    reason: str
