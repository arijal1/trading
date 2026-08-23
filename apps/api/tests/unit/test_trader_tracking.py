from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.copy_trading.trader_tracking import ClosedTrade, compute_trader_metrics

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _trade(pnl: str, *, entry_price="100", size="1", hold_hours=24) -> ClosedTrade:
    return ClosedTrade(
        entry_price=Decimal(entry_price),
        size=Decimal(size),
        realized_pnl=Decimal(pnl),
        opened_at=NOW,
        closed_at=NOW + timedelta(hours=hold_hours),
    )


def test_no_trades_gives_zero_metrics():
    metrics = compute_trader_metrics([])
    assert metrics.num_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0


def test_win_rate_hand_computed():
    trades = [_trade("10"), _trade("10"), _trade("-5")]
    metrics = compute_trader_metrics(trades)
    assert metrics.num_trades == 3
    assert metrics.win_rate == 2 / 3


def test_profit_factor_hand_computed():
    trades = [_trade("20"), _trade("-10")]
    metrics = compute_trader_metrics(trades)
    assert metrics.profit_factor == 2.0


def test_profit_factor_capped_when_no_losses():
    trades = [_trade("10"), _trade("20")]
    metrics = compute_trader_metrics(trades)
    assert metrics.profit_factor == 999.0


def test_avg_return_pct_hand_computed():
    # entry_price=100, size=1 -> notional=100. pnl=10 -> 10% return.
    trades = [_trade("10"), _trade("30")]
    metrics = compute_trader_metrics(trades)
    assert metrics.avg_return_pct == 0.2


def test_avg_hold_time_hand_computed():
    trades = [_trade("10", hold_hours=10), _trade("10", hold_hours=20)]
    metrics = compute_trader_metrics(trades)
    assert metrics.avg_hold_time_seconds == 15 * 3600


def test_max_drawdown_is_zero_for_all_winning_trades():
    trades = [_trade("10"), _trade("10"), _trade("10")]
    metrics = compute_trader_metrics(trades)
    assert metrics.max_drawdown_pct == 0.0


def test_max_drawdown_detects_a_losing_streak():
    # +50%, then two -30% legs in a row: equity 1.5 -> 1.05 -> 0.735.
    # Drawdown from peak 1.5 to trough 0.735 = 0.51 (51%).
    trades = [
        _trade("50", entry_price="100", size="1"),  # +50%
        _trade("-30", entry_price="100", size="1"),  # -30%
        _trade("-30", entry_price="100", size="1"),  # -30%
    ]
    metrics = compute_trader_metrics(trades)
    assert metrics.max_drawdown_pct > 0.5
    assert metrics.max_drawdown_pct < 0.52


def test_consistency_score_is_bounded():
    trades = [_trade("10"), _trade("-100"), _trade("50"), _trade("-5")]
    metrics = compute_trader_metrics(trades)
    assert 0 <= metrics.consistency_score <= 1


def test_risk_score_is_bounded():
    trades = [_trade("10"), _trade("-100"), _trade("50"), _trade("-5")]
    metrics = compute_trader_metrics(trades)
    assert 0 <= metrics.risk_score <= 100


def test_drawdown_ordering_respects_closed_at_not_list_order():
    # Listed out of chronological order; the function must sort by
    # closed_at before building the equity curve.
    winning_then_losing = _trade("50", hold_hours=1)
    winning_then_losing.closed_at = NOW + timedelta(hours=1)
    losing = _trade("-30", hold_hours=2)
    losing.closed_at = NOW + timedelta(hours=2)

    out_of_order = compute_trader_metrics([losing, winning_then_losing])
    in_order = compute_trader_metrics([winning_then_losing, losing])
    assert out_of_order.max_drawdown_pct == in_order.max_drawdown_pct
