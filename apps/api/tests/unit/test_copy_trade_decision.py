from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.schemas.copy_trading import (
    CopyTradeCandidateStatus,
    TraderMetricsResult,
    WeightedDirection,
)
from app.services.copy_trading.copy_trade_decision import (
    compute_trader_score,
    evaluate_copy_candidate,
    resolve_consensus,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _metrics(**overrides) -> TraderMetricsResult:
    defaults = dict(
        num_trades=20,
        win_rate=0.6,
        avg_return_pct=0.05,
        max_drawdown_pct=0.1,
        profit_factor=2.0,
        avg_hold_time_seconds=3600,
        consistency_score=0.8,
        risk_score=20.0,
    )
    defaults.update(overrides)
    return TraderMetricsResult(**defaults)


def test_trader_score_zero_with_no_trade_history():
    assert compute_trader_score(_metrics(num_trades=0)) == 0.0


def test_trader_score_is_bounded():
    score = compute_trader_score(_metrics())
    assert 0 <= score <= 1


def test_trader_score_penalizes_drawdown():
    low_dd = compute_trader_score(_metrics(max_drawdown_pct=0.05))
    high_dd = compute_trader_score(_metrics(max_drawdown_pct=0.5))
    assert low_dd > high_dd


def test_trader_score_rewards_consistency():
    low_consistency = compute_trader_score(_metrics(consistency_score=0.2))
    high_consistency = compute_trader_score(_metrics(consistency_score=0.9))
    assert high_consistency > low_consistency


def test_evaluate_copy_candidate_skips_below_min_score():
    decision = evaluate_copy_candidate(
        trader_score=0.3,
        min_trader_score=0.6,
        trader_entry_price=Decimal("100"),
        current_price=Decimal("100"),
        max_price_deviation_pct=Decimal("0.03"),
        signal_ts=NOW,
        now=NOW,
    )
    assert decision.status == CopyTradeCandidateStatus.SKIPPED
    assert "trader_score" in decision.reason


def test_evaluate_copy_candidate_skips_when_price_has_moved_too_far():
    decision = evaluate_copy_candidate(
        trader_score=0.8,
        min_trader_score=0.6,
        trader_entry_price=Decimal("100"),
        current_price=Decimal("110"),  # 10% away
        max_price_deviation_pct=Decimal("0.03"),
        signal_ts=NOW,
        now=NOW,
    )
    assert decision.status == CopyTradeCandidateStatus.SKIPPED
    assert "not chasing" in decision.reason


def test_evaluate_copy_candidate_pending_when_eligible():
    decision = evaluate_copy_candidate(
        trader_score=0.8,
        min_trader_score=0.6,
        trader_entry_price=Decimal("100"),
        current_price=Decimal("101"),
        max_price_deviation_pct=Decimal("0.03"),
        signal_ts=NOW,
        now=NOW,
    )
    assert decision.status == CopyTradeCandidateStatus.PENDING
    assert decision.price_deviation_pct == Decimal("0.01")


def test_evaluate_copy_candidate_computes_latency():
    decision = evaluate_copy_candidate(
        trader_score=0.8,
        min_trader_score=0.6,
        trader_entry_price=Decimal("100"),
        current_price=Decimal("100"),
        max_price_deviation_pct=Decimal("0.03"),
        signal_ts=NOW,
        now=NOW + timedelta(milliseconds=500),
    )
    assert decision.latency_ms == 500


def test_resolve_consensus_no_trade_when_close():
    signals = [
        WeightedDirection(trader_id="a", direction="BUY", weight=0.5),
        WeightedDirection(trader_id="b", direction="SELL", weight=0.55),
    ]
    result = resolve_consensus(signals, min_consensus_difference=0.15)
    assert result.direction == "NO_TRADE"


def test_resolve_consensus_buy_when_weighted_majority():
    signals = [
        WeightedDirection(trader_id="a", direction="BUY", weight=0.9),
        WeightedDirection(trader_id="b", direction="BUY", weight=0.8),
        WeightedDirection(trader_id="c", direction="SELL", weight=0.3),
    ]
    result = resolve_consensus(signals, min_consensus_difference=0.15)
    assert result.direction == "BUY"


def test_resolve_consensus_sell_when_weighted_majority():
    signals = [
        WeightedDirection(trader_id="a", direction="SELL", weight=0.9),
        WeightedDirection(trader_id="b", direction="BUY", weight=0.2),
    ]
    result = resolve_consensus(signals, min_consensus_difference=0.15)
    assert result.direction == "SELL"


def test_resolve_consensus_empty_signals_is_no_trade():
    result = resolve_consensus([], min_consensus_difference=0.15)
    assert result.direction == "NO_TRADE"
