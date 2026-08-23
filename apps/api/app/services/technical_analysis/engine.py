"""Technical analysis engine (brief Section 6).

Turns a candle history into a structured `TechnicalAnalysisResult`. This
engine only computes numbers — it never places an order and is not
consulted directly by the (not-yet-built) execution layer; its output is
one input among several that a future decision engine combines (Section
14).

The 0-100 scoring formulas below are a documented Phase-2 heuristic
baseline, not a statistically validated model — Phase 3's backtesting
engine is where these get calibrated against real outcomes.
"""
from __future__ import annotations

import pandas as pd

from app.db.models.core import Candle
from app.schemas.technical_analysis import IndicatorSnapshot, TechnicalAnalysisResult
from app.services.technical_analysis import indicators as ind

MIN_BARS_REQUIRED = 35

# Heuristic scaling constants (see module docstring: revisit in Phase 3).
# 5% rolling stdev of per-bar returns is treated as "maximally volatile".
MAX_EXPECTED_VOLATILITY = 0.05
# Being within 5% of resistance starts contributing to breakout_score.
BREAKOUT_PROXIMITY_WINDOW = 0.05


class InsufficientDataError(ValueError):
    pass


def candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    """Convert ascending-time ORM candle rows into a float-typed OHLCV frame."""
    rows = sorted(candles, key=lambda c: c.ts)
    df = pd.DataFrame(
        {
            "ts": [c.ts for c in rows],
            "open": [float(c.open) for c in rows],
            "high": [float(c.high) for c in rows],
            "low": [float(c.low) for c in rows],
            "close": [float(c.close) for c in rows],
            "volume": [float(c.volume) for c in rows],
        }
    )
    return df.set_index("ts")


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _safe_last(series: pd.Series) -> float | None:
    if series.empty:
        return None
    value = series.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


class TechnicalAnalysisEngine:
    def analyze(self, df: pd.DataFrame, *, symbol: str, timeframe: str) -> TechnicalAnalysisResult:
        if len(df) < MIN_BARS_REQUIRED:
            raise InsufficientDataError(
                f"need at least {MIN_BARS_REQUIRED} bars, got {len(df)}"
            )

        close = df["close"]
        volume = df["volume"]

        sma_20 = ind.sma(close, 20)
        sma_50 = ind.sma(close, 50) if len(df) >= 50 else pd.Series(dtype=float)
        ema_20 = ind.ema(close, 20)
        rsi_14 = ind.rsi(close, 14)
        macd_df = ind.macd(close)
        bb = ind.bollinger_bands(close, 20)
        atr_14 = ind.atr(df, 14)
        adx_14 = ind.adx(df, 14)
        vwap_series = ind.vwap(df)
        stoch = ind.stochastic_rsi(close)
        vol_sma_20 = ind.volume_sma(volume, 20)
        volume_spike = ind.is_volume_spike(volume, 20)
        momentum_10 = ind.momentum(close, 10)
        volatility_20 = ind.volatility(close, 20)

        support_levels, resistance_levels = ind.find_pivots(df)
        trend = ind.trend_direction(df)

        last_close = float(close.iloc[-1])
        last_rsi = _safe_last(rsi_14) or 50.0
        last_macd_hist = _safe_last(macd_df["histogram"]) or 0.0
        last_adx = _safe_last(adx_14) or 0.0
        last_stoch_k = _safe_last(stoch["k"])
        last_volatility = _safe_last(volatility_20) or 0.0
        last_volume = float(volume.iloc[-1])
        last_vol_sma = _safe_last(vol_sma_20)
        last_bb_upper = _safe_last(bb["upper"])
        last_bb_lower = _safe_last(bb["lower"])

        # --- trend_score: direction + ADX-scaled strength around a neutral 50 ---
        direction_sign = {"UPTREND": 1, "DOWNTREND": -1, "SIDEWAYS": 0, "UNKNOWN": 0}[trend]
        strength = min(last_adx, 50.0) / 50.0 * 40.0  # 0-40
        trend_score = _clip(50 + direction_sign * strength)

        # --- momentum_score: RSI as the primary oscillator, MACD histogram as a tilt ---
        macd_tilt = 5.0 if last_macd_hist > 0 else (-5.0 if last_macd_hist < 0 else 0.0)
        momentum_score = _clip(last_rsi + macd_tilt)

        # --- volume_score: current bar vs its rolling average ---
        volume_ratio = (last_volume / last_vol_sma) if last_vol_sma else 1.0
        volume_score = _clip(volume_ratio * 50.0)

        # --- volatility_score: rolling stdev of returns against a documented ceiling ---
        volatility_score = _clip((last_volatility / MAX_EXPECTED_VOLATILITY) * 100.0)

        # --- breakout_score: proximity to / breach of nearest resistance ---
        breakout_score = 0.0
        if resistance_levels:
            above = [r for r in resistance_levels if last_close > r]
            if above:
                breakout_score = 100.0
            else:
                nearest = min((r for r in resistance_levels if r >= last_close), default=None)
                if nearest and nearest > 0:
                    distance_pct = (nearest - last_close) / nearest
                    if distance_pct <= BREAKOUT_PROXIMITY_WINDOW:
                        breakout_score = _clip(
                            (1 - distance_pct / BREAKOUT_PROXIMITY_WINDOW) * 100.0
                        )

        # --- reversal_probability: agreement across three overbought/oversold signals ---
        reversal_signals = 0
        reversal_total = 0
        if last_rsi is not None:
            reversal_total += 1
            if last_rsi > 70 or last_rsi < 30:
                reversal_signals += 1
        if last_stoch_k is not None:
            reversal_total += 1
            if last_stoch_k > 80 or last_stoch_k < 20:
                reversal_signals += 1
        if last_bb_upper is not None and last_bb_lower is not None:
            reversal_total += 1
            if last_close >= last_bb_upper or last_close <= last_bb_lower:
                reversal_signals += 1
        reversal_probability = (reversal_signals / reversal_total) if reversal_total else 0.0

        snapshot = IndicatorSnapshot(
            close=last_close,
            sma_20=_safe_last(sma_20),
            sma_50=_safe_last(sma_50) if len(sma_50) else None,
            ema_20=_safe_last(ema_20),
            rsi_14=last_rsi,
            macd=_safe_last(macd_df["macd"]),
            macd_signal=_safe_last(macd_df["signal"]),
            macd_histogram=last_macd_hist,
            bollinger_upper=last_bb_upper,
            bollinger_middle=_safe_last(bb["middle"]),
            bollinger_lower=last_bb_lower,
            atr_14=_safe_last(atr_14),
            adx_14=last_adx,
            vwap=_safe_last(vwap_series),
            stoch_rsi_k=last_stoch_k,
            stoch_rsi_d=_safe_last(stoch["d"]),
            volume=last_volume,
            volume_sma_20=last_vol_sma,
            is_volume_spike=bool(volume_spike.iloc[-1]) if len(volume_spike) else False,
            momentum_10=_safe_last(momentum_10),
            volatility_20=last_volatility,
        )

        return TechnicalAnalysisResult(
            symbol=symbol,
            timeframe=timeframe,
            bar_count=len(df),
            trend_direction=trend,
            trend_score=trend_score,
            momentum_score=momentum_score,
            volume_score=volume_score,
            volatility_score=volatility_score,
            breakout_score=breakout_score,
            reversal_probability=reversal_probability,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            indicators=snapshot,
        )
