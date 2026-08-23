from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas.portfolio import RiskLimits


class TradeRecord(BaseModel):
    entry_ts: datetime
    exit_ts: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    side: Literal["LONG"] = "LONG"
    pnl: Decimal
    pnl_pct: float
    exit_trigger: str
    fees_paid: Decimal
    holding_bars: int


class PerformanceMetrics(BaseModel):
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    calmar_ratio: float
    win_rate: float
    loss_rate: float
    profit_factor: float
    expectancy: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    num_trades: int
    avg_holding_bars: float


class BacktestConfig(BaseModel):
    starting_equity: Decimal = Decimal("10000")
    risk_pct: Decimal = Decimal("0.01")
    atr_multiplier: Decimal = Decimal("2.0")
    trailing_stop_pct: Decimal | None = Decimal("0.05")
    take_profit_pct: Decimal | None = Decimal("0.10")
    max_hold_bars: int | None = 200
    min_position_value: Decimal = Decimal("10")
    risk_limits: RiskLimits = RiskLimits()
    strategy_weights: dict[str, float] | None = None
    buy_threshold: float = 25.0
    sell_threshold: float = -25.0
    slippage_pct: Decimal = Decimal("0.001")
    ta_window_bars: int = 120


class BacktestResult(BaseModel):
    symbol: str
    timeframe: str
    bar_count: int
    starting_equity: Decimal
    ending_equity: Decimal
    trades: list[TradeRecord]
    metrics: PerformanceMetrics
