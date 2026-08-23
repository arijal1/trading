"""Portfolio/risk data contracts (brief Sections 20-21).

`PortfolioState` is a plain snapshot — it carries no opinion about how it
was produced. The backtesting engine builds one in memory as it walks
forward; a future live/paper engine (Phase 4) builds one from the
`positions`/`portfolio_snapshots` tables. Either way it's fed into the
same `PortfolioRiskEngine` checks.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class PortfolioState(BaseModel):
    equity: Decimal
    cash: Decimal
    open_position_count: int = 0
    exposure_by_asset: dict[str, Decimal] = Field(default_factory=dict)
    total_exposure: Decimal = Decimal(0)
    peak_equity: Decimal
    day_start_equity: Decimal
    week_start_equity: Decimal
    is_emergency_stopped: bool = False
    is_trading_halted: bool = False


class RiskLimits(BaseModel):
    max_position_size: Decimal = Decimal("0.10")  # fraction of equity per position
    max_portfolio_exposure: Decimal = Decimal("0.80")  # fraction of equity, all positions
    max_asset_concentration: Decimal = Decimal("0.25")  # fraction of equity, single asset
    max_open_positions: int = 20
    max_daily_loss: Decimal = Decimal("0.05")  # fraction of day_start_equity
    max_weekly_loss: Decimal = Decimal("0.12")  # fraction of week_start_equity
    max_drawdown: Decimal = Decimal("0.20")  # fraction below peak_equity


class RiskCheckResult(BaseModel):
    approved: bool
    reason: str | None = None
    checks: dict[str, bool] = Field(default_factory=dict)


class PositionSizeRequest(BaseModel):
    equity: Decimal
    entry_price: Decimal
    stop_price: Decimal
    risk_pct: Decimal = Decimal("0.01")  # fraction of equity risked if stop is hit
    max_position_value_pct: Decimal = Decimal("0.10")
    min_position_value: Decimal = Decimal("10")


class PositionSizeResult(BaseModel):
    quantity: Decimal
    notional_value: Decimal
    risk_amount: Decimal
    capped_by: str | None = None
