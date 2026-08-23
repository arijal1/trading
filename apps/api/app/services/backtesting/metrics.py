"""Performance metrics (brief Section 37).

Computed from an equity curve (one mark-to-market value per bar) and a
trade list. `periods_per_year` annualizes Sharpe/Sortino/CAGR correctly
for whatever timeframe the backtest ran on — a 1h bar and a 1d bar need
very different scaling factors.

Profit factor is capped at `_UNBOUNDED_PROFIT_FACTOR` when there are wins
and no losses, rather than returned as infinity (which isn't valid JSON
and breaks API responses).
"""
from __future__ import annotations

import math

from app.schemas.backtest import PerformanceMetrics, TradeRecord

_UNBOUNDED_PROFIT_FACTOR = 999.0

TIMEFRAME_PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _bar_returns(equity_curve: list[float]) -> list[float]:
    returns = []
    for prev, curr in zip(equity_curve, equity_curve[1:], strict=False):
        if prev > 0:
            returns.append((curr - prev) / prev)
    return returns


# Below this horizon, raising the period return to the 1/years power
# extrapolates wildly (or overflows) from a handful of bars. Below the
# threshold we report the raw, un-annualized return instead of a
# meaningless projection.
_MIN_YEARS_FOR_ANNUALIZATION = 1 / 365


def _annualized_return_pct(start_equity: float, end_equity: float, years: float) -> float:
    total_return_pct = (end_equity / start_equity - 1) * 100.0
    if years < _MIN_YEARS_FOR_ANNUALIZATION:
        return total_return_pct
    try:
        return ((end_equity / start_equity) ** (1 / years) - 1) * 100.0
    except OverflowError:
        return total_return_pct


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    peak = equity_curve[0] if equity_curve else 0.0
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown = (peak - value) / peak
            max_dd = max(max_dd, drawdown)
    return max_dd * 100.0


def compute_performance_metrics(
    equity_curve: list[float],
    trades: list[TradeRecord],
    *,
    timeframe: str,
) -> PerformanceMetrics:
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        raise ValueError("equity_curve needs at least 2 points with a positive starting value")

    periods_per_year = TIMEFRAME_PERIODS_PER_YEAR.get(timeframe, 365 * 24)

    total_return_pct = (equity_curve[-1] / equity_curve[0] - 1) * 100.0

    num_bars = len(equity_curve) - 1
    years = num_bars / periods_per_year
    cagr_pct = _annualized_return_pct(equity_curve[0], equity_curve[-1], years)

    returns = _bar_returns(equity_curve)
    mean_return = sum(returns) / len(returns) if returns else 0.0
    std_return = _stdev(returns)
    sharpe_ratio = (
        (mean_return / std_return) * math.sqrt(periods_per_year) if std_return > 0 else 0.0
    )

    downside_returns = [r for r in returns if r < 0]
    downside_std = _stdev(downside_returns)
    sortino_ratio = (
        (mean_return / downside_std) * math.sqrt(periods_per_year) if downside_std > 0 else 0.0
    )

    max_drawdown_pct = _max_drawdown_pct(equity_curve)
    calmar_ratio = (cagr_pct / max_drawdown_pct) if max_drawdown_pct > 0 else 0.0

    pnls = [float(t.pnl) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    num_trades = len(trades)

    win_rate = len(wins) / num_trades if num_trades else 0.0
    loss_rate = len(losses) / num_trades if num_trades else 0.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = _UNBOUNDED_PROFIT_FACTOR
    else:
        profit_factor = 0.0

    expectancy = sum(pnls) / num_trades if num_trades else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    largest_win = max(wins) if wins else 0.0
    largest_loss = min(losses) if losses else 0.0
    avg_holding_bars = (
        sum(t.holding_bars for t in trades) / num_trades if num_trades else 0.0
    )

    return PerformanceMetrics(
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        max_drawdown_pct=max_drawdown_pct,
        calmar_ratio=calmar_ratio,
        win_rate=win_rate,
        loss_rate=loss_rate,
        profit_factor=profit_factor,
        expectancy=expectancy,
        avg_win=avg_win,
        avg_loss=avg_loss,
        largest_win=largest_win,
        largest_loss=largest_loss,
        num_trades=num_trades,
        avg_holding_bars=avg_holding_bars,
    )
