from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.technical_analysis.engine import (
    MIN_BARS_REQUIRED,
    InsufficientDataError,
    TechnicalAnalysisEngine,
)


def _sample_df(n: int = 60, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(100 + np.cumsum(rng.normal(size=n)), index=idx)
    high = close + rng.random(n)
    low = close - rng.random(n)
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(rng.random(n) * 1000 + 100, index=idx)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def test_engine_raises_on_insufficient_data():
    engine = TechnicalAnalysisEngine()
    df = _sample_df(n=MIN_BARS_REQUIRED - 1)
    with pytest.raises(InsufficientDataError):
        engine.analyze(df, symbol="BTC/USD", timeframe="1h")


def test_engine_scores_are_within_documented_bounds():
    engine = TechnicalAnalysisEngine()
    df = _sample_df(n=80)
    result = engine.analyze(df, symbol="BTC/USD", timeframe="1h")

    assert 0 <= result.trend_score <= 100
    assert 0 <= result.momentum_score <= 100
    assert 0 <= result.volume_score <= 100
    assert 0 <= result.volatility_score <= 100
    assert 0 <= result.breakout_score <= 100
    assert 0 <= result.reversal_probability <= 1
    assert result.trend_direction in {"UPTREND", "DOWNTREND", "SIDEWAYS", "UNKNOWN"}
    assert result.bar_count == 80
    assert result.symbol == "BTC/USD"
    assert result.timeframe == "1h"


def test_engine_detects_strong_uptrend_and_high_momentum():
    idx = pd.date_range("2026-01-01", periods=60, freq="1h", tz="UTC")
    close = pd.Series([100 + i * 3 for i in range(60)], index=idx, dtype=float)
    high = close + 1
    low = close - 1
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(500.0, index=idx)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})

    engine = TechnicalAnalysisEngine()
    result = engine.analyze(df, symbol="BTC/USD", timeframe="1h")

    assert result.trend_direction == "UPTREND"
    assert result.trend_score > 50
    assert result.momentum_score > 50


def test_engine_flags_reversal_risk_after_relentless_rally():
    idx = pd.date_range("2026-01-01", periods=40, freq="1h", tz="UTC")
    close = pd.Series([100 + i * 5 for i in range(40)], index=idx, dtype=float)
    high = close + 0.5
    low = close - 0.5
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(300.0, index=idx)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})

    engine = TechnicalAnalysisEngine()
    result = engine.analyze(df, symbol="BTC/USD", timeframe="1h")

    assert result.indicators.rsi_14 > 70
    assert result.reversal_probability > 0
