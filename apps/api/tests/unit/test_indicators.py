from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.technical_analysis import indicators as ind


def _ohlcv(close: pd.Series, volume: pd.Series | None = None) -> pd.DataFrame:
    high = close + 0.5
    low = close - 0.5
    open_ = close.shift(1).fillna(close.iloc[0])
    if volume is None:
        volume = pd.Series(100.0, index=close.index)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=len(values), freq="1h", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_sma_of_constant_series_equals_constant():
    s = _series([10.0] * 30)
    result = ind.sma(s, 5)
    assert result.dropna().eq(10.0).all()


def test_sma_matches_hand_computed_window():
    s = _series([1, 2, 3, 4, 5])
    result = ind.sma(s, 3)
    assert result.iloc[2] == pytest.approx(2.0)  # mean(1,2,3)
    assert result.iloc[3] == pytest.approx(3.0)  # mean(2,3,4)
    assert result.iloc[4] == pytest.approx(4.0)  # mean(3,4,5)


def test_rsi_monotonic_increase_approaches_100():
    s = _series([100 + i for i in range(40)])  # strictly increasing
    result = ind.rsi(s, period=14)
    assert result.dropna().iloc[-1] > 95


def test_rsi_monotonic_decrease_approaches_0():
    s = _series([200 - i for i in range(40)])  # strictly decreasing
    result = ind.rsi(s, period=14)
    assert result.dropna().iloc[-1] < 5


def test_rsi_is_bounded_0_100():
    rng = np.random.default_rng(1)
    s = _series(list(100 + np.cumsum(rng.normal(size=60))))
    result = ind.rsi(s, period=14).dropna()
    assert (result >= 0).all()
    assert (result <= 100).all()


def test_bollinger_bands_widen_with_volatility():
    calm = _series([100.0] * 30)
    rng = np.random.default_rng(2)
    volatile = _series(list(100 + rng.normal(scale=5, size=30)))

    calm_bb = ind.bollinger_bands(calm, period=20)
    volatile_bb = ind.bollinger_bands(volatile, period=20)

    calm_width = (calm_bb["upper"] - calm_bb["lower"]).dropna().iloc[-1]
    volatile_width = (volatile_bb["upper"] - volatile_bb["lower"]).dropna().iloc[-1]

    assert calm_width == pytest.approx(0.0, abs=1e-9)
    assert volatile_width > calm_width


def test_atr_is_nonnegative():
    rng = np.random.default_rng(3)
    close = _series(list(100 + np.cumsum(rng.normal(size=40))))
    df = _ohlcv(close)
    result = ind.atr(df, period=14).dropna()
    assert (result >= 0).all()


def test_vwap_of_flat_price_equals_price():
    close = _series([50.0] * 20)
    volume = pd.Series(100.0, index=close.index)
    df = _ohlcv(close, volume)
    result = ind.vwap(df)
    assert result.dropna().eq(50.0).all()


def test_volume_spike_detected_above_threshold():
    volume = pd.Series([100.0] * 25 + [1000.0])
    idx = pd.date_range("2026-01-01", periods=len(volume), freq="1h", tz="UTC")
    volume.index = idx
    result = ind.is_volume_spike(volume, period=20, threshold=2.0)
    assert bool(result.iloc[-1]) is True
    assert bool(result.iloc[10]) is False


def test_momentum_matches_hand_computed_diff():
    s = _series([1, 2, 4, 7, 11, 16])
    result = ind.momentum(s, period=2)
    assert result.iloc[2] == pytest.approx(3.0)  # 4 - 1
    assert result.iloc[5] == pytest.approx(9.0)  # 16 - 7


def test_trend_direction_detects_uptrend():
    close = _series([100 + i * 2 for i in range(30)])
    df = _ohlcv(close)
    assert ind.trend_direction(df) == "UPTREND"


def test_trend_direction_detects_downtrend():
    close = _series([200 - i * 2 for i in range(30)])
    df = _ohlcv(close)
    assert ind.trend_direction(df) == "DOWNTREND"


def test_find_pivots_returns_sorted_unique_levels():
    rng = np.random.default_rng(4)
    close = _series(list(100 + np.cumsum(rng.normal(size=60))))
    df = _ohlcv(close)
    support, resistance = ind.find_pivots(df, window=3)
    assert support == sorted(support)
    assert resistance == sorted(resistance)
    assert len(support) == len(set(support))
    assert len(resistance) == len(set(resistance))
