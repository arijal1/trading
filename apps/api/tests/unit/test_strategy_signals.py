from __future__ import annotations

from app.schemas.strategy import SignalDirection
from app.schemas.technical_analysis import IndicatorSnapshot, TechnicalAnalysisResult
from app.services.strategy.signals import (
    breakout_signal,
    generate_all_signals,
    mean_reversion_signal,
    momentum_signal,
    pullback_signal,
    trend_following_signal,
)


def _ta(**overrides) -> TechnicalAnalysisResult:
    defaults = dict(
        symbol="BTC/USD",
        timeframe="1h",
        bar_count=80,
        trend_direction="SIDEWAYS",
        trend_score=50.0,
        momentum_score=50.0,
        volume_score=50.0,
        volatility_score=50.0,
        breakout_score=0.0,
        reversal_probability=0.0,
        support_levels=[],
        resistance_levels=[],
        indicators=IndicatorSnapshot(close=100.0, volume=100.0),
    )
    defaults.update(overrides)
    return TechnicalAnalysisResult(**defaults)


def test_trend_following_buys_strong_uptrend():
    ta = _ta(
        trend_direction="UPTREND",
        trend_score=90.0,
        indicators=IndicatorSnapshot(close=110.0, ema_20=105.0, volume=100.0),
    )
    signal = trend_following_signal(ta)
    assert signal.direction == SignalDirection.BUY
    assert signal.strength > 0
    assert "UPTREND_CONFIRMED" in signal.reason_codes


def test_trend_following_sells_strong_downtrend():
    ta = _ta(trend_direction="DOWNTREND", trend_score=10.0)
    signal = trend_following_signal(ta)
    assert signal.direction == SignalDirection.SELL


def test_trend_following_holds_sideways():
    ta = _ta(trend_direction="SIDEWAYS", trend_score=50.0)
    signal = trend_following_signal(ta)
    assert signal.direction == SignalDirection.HOLD
    assert signal.strength == 0.0


def test_momentum_buys_high_momentum():
    ta = _ta(
        momentum_score=80.0, indicators=IndicatorSnapshot(close=100, macd_histogram=1.5, volume=1)
    )
    signal = momentum_signal(ta)
    assert signal.direction == SignalDirection.BUY
    assert "MACD_POSITIVE" in signal.reason_codes


def test_momentum_sells_low_momentum():
    ta = _ta(momentum_score=20.0)
    signal = momentum_signal(ta)
    assert signal.direction == SignalDirection.SELL


def test_breakout_buys_with_volume_confirmation():
    ta = _ta(
        breakout_score=85.0, indicators=IndicatorSnapshot(close=100, volume=1, is_volume_spike=True)
    )
    signal = breakout_signal(ta)
    assert signal.direction == SignalDirection.BUY
    assert "VOLUME_CONFIRMATION" in signal.reason_codes
    assert signal.strength == 95.0  # 85 + 10, capped at 100


def test_breakout_penalizes_missing_volume_confirmation():
    confirmed = _ta(
        breakout_score=85.0,
        indicators=IndicatorSnapshot(close=100, volume=1, is_volume_spike=True),
    )
    unconfirmed = _ta(
        breakout_score=85.0,
        indicators=IndicatorSnapshot(close=100, volume=1, is_volume_spike=False),
    )
    assert breakout_signal(confirmed).strength > breakout_signal(unconfirmed).strength


def test_breakout_sells_on_breakdown_below_support():
    ta = _ta(
        breakout_score=0.0,
        support_levels=[95.0, 90.0],
        indicators=IndicatorSnapshot(close=89.0, volume=1),
    )
    signal = breakout_signal(ta)
    assert signal.direction == SignalDirection.SELL
    assert "BREAKDOWN_BELOW_SUPPORT" in signal.reason_codes


def test_pullback_buys_dip_to_ema20_in_uptrend():
    ta = _ta(
        trend_direction="UPTREND",
        indicators=IndicatorSnapshot(close=101.0, ema_20=100.0, rsi_14=45.0, volume=1),
    )
    signal = pullback_signal(ta)
    assert signal.direction == SignalDirection.BUY


def test_pullback_holds_when_far_from_ema20():
    ta = _ta(
        trend_direction="UPTREND",
        indicators=IndicatorSnapshot(close=130.0, ema_20=100.0, rsi_14=45.0, volume=1),
    )
    signal = pullback_signal(ta)
    assert signal.direction == SignalDirection.HOLD


def test_mean_reversion_buys_oversold_rsi():
    ta = _ta(
        reversal_probability=0.5, indicators=IndicatorSnapshot(close=100, rsi_14=25.0, volume=1)
    )
    signal = mean_reversion_signal(ta)
    assert signal.direction == SignalDirection.BUY
    assert "OVERSOLD" in signal.reason_codes


def test_mean_reversion_sells_overbought_rsi():
    ta = _ta(
        reversal_probability=0.5, indicators=IndicatorSnapshot(close=100, rsi_14=80.0, volume=1)
    )
    signal = mean_reversion_signal(ta)
    assert signal.direction == SignalDirection.SELL


def test_generate_all_signals_returns_one_per_strategy():
    ta = _ta()
    signals = generate_all_signals(ta)
    assert len(signals) == 5
    assert {s.strategy for s in signals} == {
        "trend_following",
        "momentum",
        "breakout",
        "pullback",
        "mean_reversion",
    }
