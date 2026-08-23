"""Weighted signal aggregation (brief Section 16).

Deliberately not "N strategies say BUY therefore BUY": each strategy's
signed strength is weighted and averaged into a single -100..100 score,
and only a score past a configurable threshold becomes an actionable
BUY/SELL. A HOLD is not a failure state — most bars, most strategies
should have nothing to say.
"""
from __future__ import annotations

from app.schemas.strategy import AggregateDecision, SignalDirection, StrategySignal

DEFAULT_STRATEGY_WEIGHTS: dict[str, float] = {
    "trend_following": 1.0,
    "momentum": 1.0,
    "breakout": 1.0,
    "pullback": 0.75,
    "mean_reversion": 0.75,
}


class StrategyAggregator:
    def __init__(
        self,
        weights: dict[str, float] | None = None,
        buy_threshold: float = 25.0,
        sell_threshold: float = -25.0,
    ) -> None:
        self.weights = weights or DEFAULT_STRATEGY_WEIGHTS
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def aggregate(self, signals: list[StrategySignal]) -> AggregateDecision:
        weighted_sum = 0.0
        weight_total = 0.0
        reason_codes: list[str] = []

        for signal in signals:
            weight = self.weights.get(signal.strategy, 1.0)
            signed_strength = {
                SignalDirection.BUY: signal.strength,
                SignalDirection.SELL: -signal.strength,
                SignalDirection.HOLD: 0.0,
            }[signal.direction]
            weighted_sum += weight * signed_strength
            weight_total += weight
            reason_codes.extend(f"{signal.strategy}:{code}" for code in signal.reason_codes)

        score = weighted_sum / weight_total if weight_total else 0.0

        if score >= self.buy_threshold:
            direction = SignalDirection.BUY
        elif score <= self.sell_threshold:
            direction = SignalDirection.SELL
        else:
            direction = SignalDirection.HOLD

        confidence = min(1.0, abs(score) / 100.0)

        return AggregateDecision(
            direction=direction,
            score=score,
            confidence=confidence,
            signals=signals,
            reason_codes=reason_codes,
        )
