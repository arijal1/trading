"""Copy-trade decisioning (brief Sections 11-13).

`compute_trader_score` reduces the brief's Section 11 formula sketch
(`performance * consistency * risk_adjusted_return * liquidity *
execution_quality - drawdown_penalty - volatility_penalty -
suspicious_activity_penalty - concentration_penalty`) to the subset
actually computable from `trader_trades` history: performance,
consistency, and a drawdown/volatility penalty. Liquidity, execution
quality, suspicious-activity detection, and wallet-concentration all need
external market-depth or on-chain data this project doesn't have a
source for yet — the same class of gap Section 9's Token Risk Engine has
(see docs/ARCHITECTURE.md). This is documented, not silently dropped.

`evaluate_copy_candidate` gates eligibility on `MIN_TRADER_SCORE` and
guards against chasing a trade whose price has already moved too far
(Section 12). `resolve_consensus` implements Section 13's weighted
conflict resolution when multiple followed traders disagree on the same
asset — never "first signal wins."
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.schemas.copy_trading import (
    ConsensusResult,
    CopyTradeCandidateDecision,
    CopyTradeCandidateStatus,
    TraderMetricsResult,
    WeightedDirection,
)


def compute_trader_score(metrics: TraderMetricsResult) -> float:
    """0-1 composite score. Returns 0 for a trader with no closed-trade
    history — there's nothing to score yet, not a passing grade."""
    if metrics.num_trades == 0:
        return 0.0

    performance_score = max(0.0, min(1.0, metrics.win_rate * min(metrics.profit_factor, 3.0) / 3.0))
    drawdown_penalty = min(1.0, metrics.max_drawdown_pct)
    score = performance_score * metrics.consistency_score * (1 - drawdown_penalty)
    return max(0.0, min(1.0, score))


def evaluate_copy_candidate(
    *,
    trader_score: float,
    min_trader_score: float,
    trader_entry_price: Decimal,
    current_price: Decimal,
    max_price_deviation_pct: Decimal,
    signal_ts: datetime,
    now: datetime,
) -> CopyTradeCandidateDecision:
    latency_ms = int((now - signal_ts).total_seconds() * 1000)
    price_deviation_pct = (
        abs(current_price - trader_entry_price) / trader_entry_price
        if trader_entry_price
        else Decimal(0)
    )

    if trader_score < min_trader_score:
        return CopyTradeCandidateDecision(
            status=CopyTradeCandidateStatus.SKIPPED,
            trader_score=trader_score,
            price_deviation_pct=price_deviation_pct,
            latency_ms=latency_ms,
            reason=f"trader_score {trader_score:.2f} below MIN_TRADER_SCORE {min_trader_score:.2f}",
        )

    if price_deviation_pct > max_price_deviation_pct:
        return CopyTradeCandidateDecision(
            status=CopyTradeCandidateStatus.SKIPPED,
            trader_score=trader_score,
            price_deviation_pct=price_deviation_pct,
            latency_ms=latency_ms,
            reason=(
                f"price has already moved {price_deviation_pct:.2%} since the trader's "
                f"entry, exceeding MAX_COPY_PRICE_DEVIATION_PERCENT {max_price_deviation_pct:.2%} "
                "— not chasing"
            ),
        )

    return CopyTradeCandidateDecision(
        status=CopyTradeCandidateStatus.PENDING,
        trader_score=trader_score,
        price_deviation_pct=price_deviation_pct,
        latency_ms=latency_ms,
        reason="eligible: trader score and price deviation both within limits",
    )


def resolve_consensus(
    signals: list[WeightedDirection], *, min_consensus_difference: float
) -> ConsensusResult:
    buy_score = sum(s.weight for s in signals if s.direction == "BUY")
    sell_score = sum(s.weight for s in signals if s.direction == "SELL")

    if abs(buy_score - sell_score) < min_consensus_difference:
        return ConsensusResult(
            direction="NO_TRADE",
            buy_score=buy_score,
            sell_score=sell_score,
            reason=(
                f"weighted consensus too close (buy={buy_score:.2f}, sell={sell_score:.2f}, "
                f"diff < {min_consensus_difference:.2f})"
            ),
        )

    direction = "BUY" if buy_score > sell_score else "SELL"
    return ConsensusResult(
        direction=direction,
        buy_score=buy_score,
        sell_score=sell_score,
        reason=f"{direction} consensus: buy={buy_score:.2f}, sell={sell_score:.2f}",
    )
