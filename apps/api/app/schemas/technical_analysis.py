from __future__ import annotations

from pydantic import BaseModel


class IndicatorSnapshot(BaseModel):
    """Latest-bar raw indicator values, for explainability (Section 30)."""

    close: float
    sma_20: float | None = None
    sma_50: float | None = None
    ema_20: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bollinger_upper: float | None = None
    bollinger_middle: float | None = None
    bollinger_lower: float | None = None
    atr_14: float | None = None
    adx_14: float | None = None
    vwap: float | None = None
    stoch_rsi_k: float | None = None
    stoch_rsi_d: float | None = None
    volume: float
    volume_sma_20: float | None = None
    is_volume_spike: bool = False
    momentum_10: float | None = None
    volatility_20: float | None = None


class TechnicalAnalysisResult(BaseModel):
    symbol: str
    timeframe: str
    bar_count: int

    trend_direction: str
    trend_score: float  # 0-100, 50 = neutral
    momentum_score: float  # 0-100
    volume_score: float  # 0-100
    volatility_score: float  # 0-100
    breakout_score: float  # 0-100
    reversal_probability: float  # 0-1

    support_levels: list[float]
    resistance_levels: list[float]

    indicators: IndicatorSnapshot
