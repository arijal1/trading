"""Indicator math (brief Section 6).

Pure functions operating on pandas Series/DataFrames indexed by ascending
timestamp with float columns. Floats are used deliberately here — these
are statistical/analytical values, not money or order quantities, so
this module is exempt from the repo-wide "use Decimal for money" rule
(see docs/DATABASE_SCHEMA.md). Nothing in this module places an order or
touches the database; it only turns OHLCV into numbers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, min_periods=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.fillna(100).astype(float)


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    middle = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move.clip(lower=0)

    tr = true_range(df)
    smoothed_tr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    smoothed_plus_dm = plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    smoothed_minus_dm = minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    plus_di = 100 * (smoothed_plus_dm / smoothed_tr.replace(0, np.nan))
    minus_di = 100 * (smoothed_minus_dm / smoothed_tr.replace(0, np.nan))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().fillna(0).astype(float)


def vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_pv = (typical_price * df["volume"]).cumsum()
    cumulative_volume = df["volume"].cumsum().replace(0, np.nan)
    return (cumulative_pv / cumulative_volume).astype(float)


def stochastic_rsi(
    close: pd.Series, period: int = 14, smooth_k: int = 3, smooth_d: int = 3
) -> pd.DataFrame:
    rsi_series = rsi(close, period)
    min_rsi = rsi_series.rolling(window=period, min_periods=period).min()
    max_rsi = rsi_series.rolling(window=period, min_periods=period).max()
    denom = (max_rsi - min_rsi).replace(0, np.nan)
    raw_stoch_rsi = ((rsi_series - min_rsi) / denom).fillna(0.5) * 100
    k = raw_stoch_rsi.rolling(window=smooth_k, min_periods=smooth_k).mean()
    d = k.rolling(window=smooth_d, min_periods=smooth_d).mean()
    return pd.DataFrame({"k": k, "d": d})


def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    return sma(volume, period)


def is_volume_spike(volume: pd.Series, period: int = 20, threshold: float = 2.0) -> pd.Series:
    avg = volume_sma(volume, period)
    return (volume > avg * threshold).fillna(False)


def momentum(close: pd.Series, period: int = 10) -> pd.Series:
    return close.diff(period)


def volatility(close: pd.Series, period: int = 20) -> pd.Series:
    returns = close.pct_change()
    return returns.rolling(window=period, min_periods=period).std()


def find_pivots(df: pd.DataFrame, window: int = 5) -> tuple[list[float], list[float]]:
    """Local-extrema support/resistance levels over the last `window`-bar neighborhoods."""
    highs = df["high"]
    lows = df["low"]
    resistance_levels: list[float] = []
    support_levels: list[float] = []

    for i in range(window, len(df) - window):
        window_high = highs.iloc[i - window : i + window + 1]
        window_low = lows.iloc[i - window : i + window + 1]
        if highs.iloc[i] == window_high.max():
            resistance_levels.append(float(highs.iloc[i]))
        if lows.iloc[i] == window_low.min():
            support_levels.append(float(lows.iloc[i]))

    return sorted(set(support_levels)), sorted(set(resistance_levels))


def trend_direction(df: pd.DataFrame, lookback: int = 20) -> str:
    """Classify recent structure via swing highs/lows over the lookback window."""
    recent = df.tail(lookback)
    if len(recent) < 4:
        return "UNKNOWN"

    highs = recent["high"]
    lows = recent["low"]
    mid = len(recent) // 2
    first_half_high, second_half_high = highs.iloc[:mid].max(), highs.iloc[mid:].max()
    first_half_low, second_half_low = lows.iloc[:mid].min(), lows.iloc[mid:].min()

    higher_highs = second_half_high > first_half_high
    higher_lows = second_half_low > first_half_low
    lower_highs = second_half_high < first_half_high
    lower_lows = second_half_low < first_half_low

    if higher_highs and higher_lows:
        return "UPTREND"
    if lower_highs and lower_lows:
        return "DOWNTREND"
    return "SIDEWAYS"
