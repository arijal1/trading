"""Independent entry-strategy signal generators (brief Section 16).

Each function looks only at a `TechnicalAnalysisResult` and returns one
`StrategySignal` — it never sees the others, so `aggregator.py` is doing
real weighted combination rather than a single strategy dressed up as
five. Copy-trading is deliberately not here: it depends on trader-tracking
data that doesn't exist until Phase 4 (docs/ARCHITECTURE.md Section 9).
"""
from __future__ import annotations

from app.schemas.strategy import SignalDirection, StrategySignal
from app.schemas.technical_analysis import TechnicalAnalysisResult

_BUY = SignalDirection.BUY
_SELL = SignalDirection.SELL
_HOLD = SignalDirection.HOLD


def trend_following_signal(ta: TechnicalAnalysisResult) -> StrategySignal:
    if ta.trend_direction == "UPTREND" and ta.trend_score > 55:
        strength = min(100.0, (ta.trend_score - 50) * 2)
        reasons = ["UPTREND_CONFIRMED"]
        if ta.indicators.ema_20 is not None and ta.indicators.close > ta.indicators.ema_20:
            strength = min(100.0, strength + 10)
            reasons.append("PRICE_ABOVE_EMA20")
        return StrategySignal(
            strategy="trend_following", direction=_BUY, strength=strength, reason_codes=reasons
        )
    if ta.trend_direction == "DOWNTREND" and ta.trend_score < 45:
        strength = min(100.0, (50 - ta.trend_score) * 2)
        return StrategySignal(
            strategy="trend_following",
            direction=_SELL,
            strength=strength,
            reason_codes=["DOWNTREND_CONFIRMED"],
        )
    return StrategySignal(
        strategy="trend_following", direction=_HOLD, strength=0.0, reason_codes=["NO_CLEAR_TREND"]
    )


def momentum_signal(ta: TechnicalAnalysisResult) -> StrategySignal:
    if ta.momentum_score >= 60:
        strength = min(100.0, (ta.momentum_score - 50) * 2)
        reasons = ["MOMENTUM_BULLISH"]
        if ta.indicators.macd_histogram is not None and ta.indicators.macd_histogram > 0:
            reasons.append("MACD_POSITIVE")
        return StrategySignal(
            strategy="momentum", direction=_BUY, strength=strength, reason_codes=reasons
        )
    if ta.momentum_score <= 40:
        strength = min(100.0, (50 - ta.momentum_score) * 2)
        reasons = ["MOMENTUM_BEARISH"]
        if ta.indicators.macd_histogram is not None and ta.indicators.macd_histogram < 0:
            reasons.append("MACD_NEGATIVE")
        return StrategySignal(
            strategy="momentum", direction=_SELL, strength=strength, reason_codes=reasons
        )
    return StrategySignal(
        strategy="momentum", direction=_HOLD, strength=0.0, reason_codes=["MOMENTUM_NEUTRAL"]
    )


def breakout_signal(ta: TechnicalAnalysisResult) -> StrategySignal:
    if ta.breakout_score >= 70:
        strength = ta.breakout_score
        reasons = ["BREAKOUT_ABOVE_RESISTANCE"]
        if ta.indicators.is_volume_spike:
            strength = min(100.0, strength + 10)
            reasons.append("VOLUME_CONFIRMATION")
        else:
            strength = max(0.0, strength - 20)
            reasons.append("NO_VOLUME_CONFIRMATION")
        return StrategySignal(
            strategy="breakout", direction=_BUY, strength=strength, reason_codes=reasons
        )
    if ta.support_levels and ta.indicators.close < min(ta.support_levels):
        return StrategySignal(
            strategy="breakout",
            direction=_SELL,
            strength=70.0,
            reason_codes=["BREAKDOWN_BELOW_SUPPORT"],
        )
    return StrategySignal(
        strategy="breakout", direction=_HOLD, strength=0.0, reason_codes=["NO_BREAKOUT"]
    )


_PULLBACK_PROXIMITY = 0.02  # within 2% of EMA20 counts as "at" it


def pullback_signal(ta: TechnicalAnalysisResult) -> StrategySignal:
    """Buy a dip toward EMA20 within an uptrend; sell a rally toward it in a downtrend."""
    ema20 = ta.indicators.ema_20
    rsi = ta.indicators.rsi_14
    close = ta.indicators.close

    if ema20 is None or rsi is None or ema20 <= 0:
        return StrategySignal(
            strategy="pullback", direction=_HOLD, strength=0.0, reason_codes=["INSUFFICIENT_DATA"]
        )

    near_ema = abs(close - ema20) / ema20 <= _PULLBACK_PROXIMITY

    if ta.trend_direction == "UPTREND" and near_ema and 35 <= rsi <= 55:
        return StrategySignal(
            strategy="pullback",
            direction=_BUY,
            strength=60.0,
            reason_codes=["PULLBACK_TO_EMA20_IN_UPTREND", "RSI_NEUTRAL"],
        )
    if ta.trend_direction == "DOWNTREND" and near_ema and 45 <= rsi <= 65:
        return StrategySignal(
            strategy="pullback",
            direction=_SELL,
            strength=60.0,
            reason_codes=["RALLY_TO_EMA20_IN_DOWNTREND", "RSI_NEUTRAL"],
        )
    return StrategySignal(
        strategy="pullback", direction=_HOLD, strength=0.0, reason_codes=["NO_PULLBACK_SETUP"]
    )


def mean_reversion_signal(ta: TechnicalAnalysisResult) -> StrategySignal:
    """Contrarian: fade RSI/Bollinger extremes rather than follow them."""
    rsi = ta.indicators.rsi_14
    close = ta.indicators.close
    bb_lower = ta.indicators.bollinger_lower
    bb_upper = ta.indicators.bollinger_upper

    oversold = (rsi is not None and rsi < 30) or (bb_lower is not None and close <= bb_lower)
    overbought = (rsi is not None and rsi > 70) or (bb_upper is not None and close >= bb_upper)

    if oversold:
        strength = min(100.0, ta.reversal_probability * 100 + 20)
        return StrategySignal(
            strategy="mean_reversion", direction=_BUY, strength=strength, reason_codes=["OVERSOLD"]
        )
    if overbought:
        strength = min(100.0, ta.reversal_probability * 100 + 20)
        return StrategySignal(
            strategy="mean_reversion",
            direction=_SELL,
            strength=strength,
            reason_codes=["OVERBOUGHT"],
        )
    return StrategySignal(
        strategy="mean_reversion", direction=_HOLD, strength=0.0, reason_codes=["NO_EXTREME"]
    )


ALL_SIGNAL_GENERATORS = (
    trend_following_signal,
    momentum_signal,
    breakout_signal,
    pullback_signal,
    mean_reversion_signal,
)


def generate_all_signals(ta: TechnicalAnalysisResult) -> list[StrategySignal]:
    return [generator(ta) for generator in ALL_SIGNAL_GENERATORS]
