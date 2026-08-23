from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.backtest import TradeRecord
from app.services.backtesting.metrics import compute_performance_metrics

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _trade(pnl: float, holding_bars: int = 5) -> TradeRecord:
    return TradeRecord(
        entry_ts=NOW,
        exit_ts=NOW + timedelta(hours=holding_bars),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + Decimal(str(pnl)) / Decimal("10"),
        quantity=Decimal("10"),
        pnl=Decimal(str(pnl)),
        pnl_pct=pnl / 1000,
        exit_trigger="TAKE_PROFIT" if pnl > 0 else "STOP_LOSS",
        fees_paid=Decimal("1"),
        holding_bars=holding_bars,
    )


def test_total_return_pct_hand_computed():
    equity_curve = [1000.0, 1100.0]  # +10%
    metrics = compute_performance_metrics(equity_curve, [], timeframe="1h")
    assert metrics.total_return_pct == pytest.approx(10.0)


def test_max_drawdown_hand_computed():
    # Peak 1000 -> drops to 800 -> recovers to 900. Max DD = 20%.
    equity_curve = [1000.0, 800.0, 900.0]
    metrics = compute_performance_metrics(equity_curve, [], timeframe="1h")
    assert metrics.max_drawdown_pct == pytest.approx(20.0)


def test_flat_equity_curve_has_zero_sharpe_and_drawdown():
    equity_curve = [1000.0] * 10
    metrics = compute_performance_metrics(equity_curve, [], timeframe="1h")
    assert metrics.sharpe_ratio == 0.0
    assert metrics.max_drawdown_pct == 0.0
    assert metrics.total_return_pct == 0.0


def test_monotonically_increasing_equity_has_positive_sharpe():
    equity_curve = [1000.0 + i * 5 for i in range(50)]
    metrics = compute_performance_metrics(equity_curve, [], timeframe="1h")
    assert metrics.sharpe_ratio > 0
    assert metrics.sortino_ratio == 0.0  # no negative returns at all


def test_win_rate_and_profit_factor_hand_computed():
    trades = [_trade(100), _trade(100), _trade(-50)]
    equity_curve = [1000.0, 1100.0, 1200.0, 1150.0]
    metrics = compute_performance_metrics(equity_curve, trades, timeframe="1h")
    assert metrics.num_trades == 3
    assert metrics.win_rate == pytest.approx(2 / 3)
    assert metrics.loss_rate == pytest.approx(1 / 3)
    # gross_profit=200, gross_loss=50 -> profit_factor=4
    assert metrics.profit_factor == pytest.approx(4.0)
    assert metrics.avg_win == pytest.approx(100.0)
    assert metrics.avg_loss == pytest.approx(-50.0)
    assert metrics.largest_win == pytest.approx(100.0)
    assert metrics.largest_loss == pytest.approx(-50.0)
    # expectancy = (100+100-50)/3
    assert metrics.expectancy == pytest.approx(150 / 3)


def test_profit_factor_capped_when_no_losses():
    trades = [_trade(100), _trade(50)]
    equity_curve = [1000.0, 1100.0, 1150.0]
    metrics = compute_performance_metrics(equity_curve, trades, timeframe="1h")
    assert metrics.profit_factor == 999.0


def test_no_trades_gives_zero_trade_metrics():
    equity_curve = [1000.0, 1010.0]
    metrics = compute_performance_metrics(equity_curve, [], timeframe="1h")
    assert metrics.num_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.expectancy == 0.0


def test_rejects_degenerate_equity_curve():
    with pytest.raises(ValueError):
        compute_performance_metrics([1000.0], [], timeframe="1h")
    with pytest.raises(ValueError):
        compute_performance_metrics([0.0, 100.0], [], timeframe="1h")


def test_avg_holding_bars_hand_computed():
    trades = [_trade(10, holding_bars=4), _trade(10, holding_bars=6)]
    equity_curve = [1000.0, 1010.0, 1020.0]
    metrics = compute_performance_metrics(equity_curve, trades, timeframe="1h")
    assert metrics.avg_holding_bars == pytest.approx(5.0)
