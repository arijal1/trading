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


def _evaluate(
    engine: ExitEngine,
    state: PositionExitState,
    *,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    ts: datetime = NOW,
    ta: TechnicalAnalysisResult | None = None,
):
    return engine.evaluate(
        state, current_high=high, current_low=low, current_close=close, current_ts=ts, ta=ta
    )


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
    decision = _evaluate(engine, state, high=Decimal("96"), low=Decimal("94"), close=Decimal("94"))
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.STOP_LOSS
    assert decision.fills_intrabar is True


def test_evaluate_detects_intrabar_stop_hit_even_when_close_recovers_above_stop():
    """The core fidelity fix: a bar whose low pierced the stop but whose
    close recovered above it must still trigger — the stop is a resting
    order, not a close-only check."""
    engine = ExitEngine()
    state = _state(stop_price=Decimal("95"))
    decision = _evaluate(
        engine, state, high=Decimal("101"), low=Decimal("90"), close=Decimal("99")
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.STOP_LOSS
    assert decision.exit_price == Decimal("95")
    assert decision.fills_intrabar is True


def test_evaluate_detects_intrabar_take_profit_even_when_close_pulls_back():
    engine = ExitEngine()
    state = _state(take_profit_price=Decimal("120"))
    decision = _evaluate(
        engine, state, high=Decimal("125"), low=Decimal("115"), close=Decimal("116")
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.TAKE_PROFIT
    assert decision.exit_price == Decimal("120")
    assert decision.fills_intrabar is True


def test_evaluate_stop_takes_priority_when_both_touched_in_same_bar():
    """Conservative assumption: if a bar's range spans both the stop and
    the take-profit, assume the worse outcome (stop) fired first."""
    engine = ExitEngine()
    state = _state(stop_price=Decimal("95"), take_profit_price=Decimal("120"))
    decision = _evaluate(
        engine, state, high=Decimal("121"), low=Decimal("94"), close=Decimal("110")
    )
    assert decision.trigger == ExitTrigger.STOP_LOSS


def test_evaluate_triggers_trailing_stop_when_stop_above_entry():
    engine = ExitEngine()
    state = _state(entry_price=Decimal("100"), stop_price=Decimal("110"))
    decision = _evaluate(
        engine, state, high=Decimal("112"), low=Decimal("109"), close=Decimal("109")
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.TRAILING_STOP


def test_evaluate_triggers_take_profit():
    engine = ExitEngine()
    state = _state(take_profit_price=Decimal("120"))
    decision = _evaluate(
        engine, state, high=Decimal("121"), low=Decimal("119"), close=Decimal("121")
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.TAKE_PROFIT


def test_evaluate_triggers_max_hold_time():
    engine = ExitEngine()
    state = _state(max_hold_seconds=3600)
    decision = _evaluate(
        engine,
        state,
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        ts=NOW + timedelta(hours=2),
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.MAX_HOLD_TIME
    assert decision.fills_intrabar is False


def test_evaluate_does_not_trigger_max_hold_time_early():
    engine = ExitEngine()
    state = _state(max_hold_seconds=3600)
    decision = _evaluate(
        engine,
        state,
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        ts=NOW + timedelta(minutes=10),
    )
    assert decision.should_exit is False


def test_evaluate_triggers_trend_reversal():
    engine = ExitEngine()
    state = _state()
    ta = _ta(trend_direction="DOWNTREND")
    decision = _evaluate(
        engine, state, high=Decimal("102"), low=Decimal("100"), close=Decimal("101"), ta=ta
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.TREND_REVERSAL
    assert decision.fills_intrabar is False


def test_evaluate_triggers_momentum_failure():
    engine = ExitEngine(momentum_failure_score=25.0)
    state = _state()
    ta = _ta(trend_direction="SIDEWAYS", momentum_score=10.0)
    decision = _evaluate(
        engine, state, high=Decimal("102"), low=Decimal("100"), close=Decimal("101"), ta=ta
    )
    assert decision.should_exit is True
    assert decision.trigger == ExitTrigger.MOMENTUM_FAILURE


def test_evaluate_no_exit_when_healthy():
    engine = ExitEngine()
    state = _state()
    ta = _ta(trend_direction="UPTREND", momentum_score=70.0)
    decision = _evaluate(
        engine, state, high=Decimal("106"), low=Decimal("104"), close=Decimal("105"), ta=ta
    )
    assert decision.should_exit is False
    assert decision.trigger == ExitTrigger.NONE


def test_stop_loss_takes_priority_over_trend_reversal():
    engine = ExitEngine()
    state = _state(stop_price=Decimal("95"))
    ta = _ta(trend_direction="DOWNTREND")
    decision = _evaluate(
        engine, state, high=Decimal("96"), low=Decimal("94"), close=Decimal("94"), ta=ta
    )
    assert decision.trigger == ExitTrigger.STOP_LOSS
