from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.exit import ExitTrigger, PositionExitState
from app.schemas.technical_analysis import IndicatorSnapshot, TechnicalAnalysisResult
from app.services.execution.exit_engine import (
    ExitEngine,
    InvalidATRError,
    advance_position_state,
    compute_dynamic_stop_loss,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _state(**overrides) -> PositionExitState:
    defaults = dict(
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        take_profit_price=Decimal("120"),
        trailing_stop_pct=None,
        highest_price_since_entry=Decimal("100"),
        opened_at=NOW,
        max_hold_seconds=None,
    )
    defaults.update(overrides)
    return PositionExitState(**defaults)


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


def test_compute_dynamic_stop_loss_hand_computed():
    stop = compute_dynamic_stop_loss(
        entry_price=Decimal("100"), atr=Decimal("2"), atr_multiplier=Decimal("2.5")
    )
    assert stop == Decimal("95")


def test_compute_dynamic_stop_loss_rejects_nonpositive_atr():
    with pytest.raises(InvalidATRError):
        compute_dynamic_stop_loss(entry_price=Decimal("100"), atr=Decimal("0"))


def test_advance_position_state_tracks_new_high():
    state = _state(highest_price_since_entry=Decimal("100"))
    advanced = advance_position_state(state, Decimal("110"))
    assert advanced.highest_price_since_entry == Decimal("110")


def test_advance_position_state_ratchets_trailing_stop_upward():
    state = _state(stop_price=Decimal("95"), trailing_stop_pct=Decimal("0.05"))
    advanced = advance_position_state(state, Decimal("120"))
    # 120 * (1 - 0.05) = 114, which is above the original stop of 95.
    assert advanced.stop_price == Decimal("114.00")


def test_advance_position_state_never_lowers_stop():
    state = _state(stop_price=Decimal("114"), trailing_stop_pct=Decimal("0.05"))
    # Price drops back down; trailing calc would suggest a lower stop, but
    # the ratchet must not loosen it.
    advanced = advance_position_state(state, Decimal("100"))
    assert advanced.stop_price == Decimal("114")


def test_evaluate_triggers_stop_loss_at_initial_stop():
    engine = ExitEngine()
    state = _state(stop_price=Decimal("95"))
    decision = engine.evaluate(state, current_price=Decimal("94"), current_ts=NOW)
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.STOP_LOSS


def test_evaluate_triggers_trailing_stop_when_stop_above_entry():
    engine = ExitEngine()
    state = _state(entry_price=Decimal("100"), stop_price=Decimal("110"))
    decision = engine.evaluate(state, current_price=Decimal("109"), current_ts=NOW)
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.TRAILING_STOP


def test_evaluate_triggers_take_profit():
    engine = ExitEngine()
    state = _state(take_profit_price=Decimal("120"))
    decision = engine.evaluate(state, current_price=Decimal("121"), current_ts=NOW)
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.TAKE_PROFIT


def test_evaluate_triggers_max_hold_time():
    engine = ExitEngine()
    state = _state(max_hold_seconds=3600)
    decision = engine.evaluate(
        state, current_price=Decimal("101"), current_ts=NOW + timedelta(hours=2)
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.MAX_HOLD_TIME


def test_evaluate_does_not_trigger_max_hold_time_early():
    engine = ExitEngine()
    state = _state(max_hold_seconds=3600)
    decision = engine.evaluate(
        state, current_price=Decimal("101"), current_ts=NOW + timedelta(minutes=10)
    )
    assert decision.should_exit is False


def test_evaluate_triggers_trend_reversal():
    engine = ExitEngine()
    state = _state()
    ta = _ta(trend_direction="DOWNTREND")
    decision = engine.evaluate(state, current_price=Decimal("101"), current_ts=NOW, ta=ta)
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.TREND_REVERSAL


def test_evaluate_triggers_momentum_failure():
    engine = ExitEngine(momentum_failure_score=25.0)
    state = _state()
    ta = _ta(trend_direction="SIDEWAYS", momentum_score=10.0)
    decision = engine.evaluate(state, current_price=Decimal("101"), current_ts=NOW, ta=ta)
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.MOMENTUM_FAILURE


def test_evaluate_no_exit_when_healthy():
    engine = ExitEngine()
    state = _state()
    ta = _ta(trend_direction="UPTREND", momentum_score=70.0)
    decision = engine.evaluate(state, current_price=Decimal("105"), current_ts=NOW, ta=ta)
    assert decision.should_exit is False
    assert decision.trigger == ExitTrigger.NONE


def test_stop_loss_takes_priority_over_trend_reversal():
    engine = ExitEngine()
    state = _state(stop_price=Decimal("95"))
    ta = _ta(trend_direction="DOWNTREND")
    decision = engine.evaluate(state, current_price=Decimal("94"), current_ts=NOW, ta=ta)
    assert decision.trigger == ExitTrigger.STOP_LOSS
