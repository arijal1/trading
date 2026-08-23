from __future__ import annotations

from app.schemas.strategy import SignalDirection, StrategySignal
from app.services.strategy.aggregator import StrategyAggregator


def _signal(strategy: str, direction: SignalDirection, strength: float) -> StrategySignal:
    return StrategySignal(
        strategy=strategy, direction=direction, strength=strength, reason_codes=[]
    )


def test_unanimous_strong_buy_produces_buy():
    aggregator = StrategyAggregator()
    signals = [
        _signal("trend_following", SignalDirection.BUY, 80),
        _signal("momentum", SignalDirection.BUY, 70),
        _signal("breakout", SignalDirection.BUY, 90),
    ]
    decision = aggregator.aggregate(signals)
    assert decision.direction == SignalDirection.BUY
    assert decision.score > 0
    assert decision.confidence > 0


def test_mixed_weak_signals_produce_hold():
    aggregator = StrategyAggregator(buy_threshold=25.0, sell_threshold=-25.0)
    signals = [
        _signal("trend_following", SignalDirection.BUY, 20),
        _signal("momentum", SignalDirection.SELL, 20),
        _signal("breakout", SignalDirection.HOLD, 0),
    ]
    decision = aggregator.aggregate(signals)
    assert decision.direction == SignalDirection.HOLD


def test_unanimous_sell_produces_sell():
    aggregator = StrategyAggregator()
    signals = [
        _signal("trend_following", SignalDirection.SELL, 80),
        _signal("momentum", SignalDirection.SELL, 70),
    ]
    decision = aggregator.aggregate(signals)
    assert decision.direction == SignalDirection.SELL
    assert decision.score < 0


def test_no_signals_is_hold_with_zero_confidence():
    aggregator = StrategyAggregator()
    decision = aggregator.aggregate([])
    assert decision.direction == SignalDirection.HOLD
    assert decision.score == 0.0
    assert decision.confidence == 0.0


def test_single_dissenter_does_not_flip_strong_consensus():
    """Not '3 indicators say buy therefore buy': but a lone weak dissent
    shouldn't overturn a strong, weighted majority either."""
    aggregator = StrategyAggregator()
    signals = [
        _signal("trend_following", SignalDirection.BUY, 90),
        _signal("momentum", SignalDirection.BUY, 90),
        _signal("breakout", SignalDirection.BUY, 90),
        _signal("mean_reversion", SignalDirection.SELL, 30),
    ]
    decision = aggregator.aggregate(signals)
    assert decision.direction == SignalDirection.BUY


def test_custom_weights_change_outcome():
    signals = [
        _signal("trend_following", SignalDirection.BUY, 40),
        _signal("mean_reversion", SignalDirection.SELL, 40),
    ]
    equal_weights = StrategyAggregator(weights={"trend_following": 1.0, "mean_reversion": 1.0})
    assert equal_weights.aggregate(signals).direction == SignalDirection.HOLD

    trend_favored = StrategyAggregator(weights={"trend_following": 5.0, "mean_reversion": 1.0})
    assert trend_favored.aggregate(signals).direction == SignalDirection.BUY


def test_reason_codes_are_prefixed_by_strategy():
    aggregator = StrategyAggregator()
    signals = [
        StrategySignal(
            strategy="momentum",
            direction=SignalDirection.BUY,
            strength=80,
            reason_codes=["MOMENTUM_BULLISH"],
        )
    ]
    decision = aggregator.aggregate(signals)
    assert "momentum:MOMENTUM_BULLISH" in decision.reason_codes
