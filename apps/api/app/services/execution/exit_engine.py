"""Exit engine (brief Sections 17-19).

`compute_dynamic_stop_loss` sizes the initial stop off ATR rather than a
fixed percentage (Section 18). `advance_position_state` ratchets the stop
up as price makes new highs (Section 19's trailing-stop mechanic) — it
never loosens a stop that's already been tightened. `ExitEngine.evaluate`
checks all configured exit triggers and returns the first one that fires.

Stop-loss, trailing-stop, and take-profit are resting orders: they fill
the instant the bar's low/high crosses them, not at the bar's close. A
caller evaluating an already-closed historical bar knows its full
high/low, so checking them is not look-ahead — it's the same bar whose
close is already being used for every other check here. Missing this
would let a bar that dipped through the stop and recovered by its close
silently avoid the stop, understating realized risk. If both the stop and
the take-profit are crossed within the same bar, we conservatively assume
the stop was hit first (no tick-level intrabar sequencing is available).

Signal-based exits (max hold time, trend reversal, momentum failure) are
decisions made from the bar's close, exactly like entries, so their fill
is deferred to the next bar's open by the caller (see
`ExitDecision.fills_intrabar` and `app/services/backtesting/engine.py`).

Scope note: Section 19 describes a multi-stage break-even -> profit-lock
-> trail progression, and Section 2/42 describe capital-recovery partial
exits. Both depend on a `ProfitManager` tracking initial capital per
position, which is explicitly a Phase 4 concern (paper trading + profit
management, per docs/ARCHITECTURE.md Section 13). This module implements
the single-parameter ratcheting trailing stop that Phase 4's ProfitManager
will build on, not the full staged progression.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.schemas.exit import ExitDecision, ExitTrigger, PositionExitState
from app.schemas.technical_analysis import TechnicalAnalysisResult

DEFAULT_ATR_MULTIPLIER = Decimal("2.0")


class InvalidATRError(ValueError):
    pass


def compute_dynamic_stop_loss(
    entry_price: Decimal, atr: Decimal, atr_multiplier: Decimal = DEFAULT_ATR_MULTIPLIER
) -> Decimal:
    """LONG-only initial stop: entry minus a volatility-scaled distance."""
    if atr <= 0:
        raise InvalidATRError("atr must be positive")
    return entry_price - (atr * atr_multiplier)


def advance_position_state(state: PositionExitState, current_high: Decimal) -> PositionExitState:
    """Update the running high and ratchet the trailing stop upward only.

    Takes the bar's high (the actual intrabar peak), not its close —
    price genuinely reached that level, so the trailing stop should react
    to it.
    """
    new_highest = max(state.highest_price_since_entry, current_high)
    new_stop = state.stop_price
    if state.trailing_stop_pct is not None:
        trail_stop = new_highest * (1 - state.trailing_stop_pct)
        new_stop = max(state.stop_price, trail_stop)
    return state.model_copy(
        update={"highest_price_since_entry": new_highest, "stop_price": new_stop}
    )


class ExitEngine:
    def __init__(self, momentum_failure_score: float = 25.0) -> None:
        self.momentum_failure_score = momentum_failure_score

    def evaluate(
        self,
        state: PositionExitState,
        *,
        current_high: Decimal,
        current_low: Decimal,
        current_close: Decimal,
        current_ts: datetime,
        ta: TechnicalAnalysisResult | None = None,
    ) -> ExitDecision:
        if current_low <= state.stop_price:
            is_trailing = state.stop_price > state.entry_price
            trigger = ExitTrigger.TRAILING_STOP if is_trailing else ExitTrigger.STOP_LOSS
            return ExitDecision(
                should_exit=True,
                trigger=trigger,
                exit_price=state.stop_price,
                reason=f"low {current_low} <= stop {state.stop_price}",
                fills_intrabar=True,
            )

        if state.take_profit_price is not None and current_high >= state.take_profit_price:
            return ExitDecision(
                should_exit=True,
                trigger=ExitTrigger.TAKE_PROFIT,
                exit_price=state.take_profit_price,
                reason=f"high {current_high} reached take-profit {state.take_profit_price}",
                fills_intrabar=True,
            )

        if state.max_hold_seconds is not None:
            held_seconds = (current_ts - state.opened_at).total_seconds()
            if held_seconds >= state.max_hold_seconds:
                return ExitDecision(
                    should_exit=True,
                    trigger=ExitTrigger.MAX_HOLD_TIME,
                    exit_price=current_close,
                    reason=f"held {held_seconds:.0f}s >= max {state.max_hold_seconds}s",
                )

        if ta is not None:
            if ta.trend_direction == "DOWNTREND":
                return ExitDecision(
                    should_exit=True,
                    trigger=ExitTrigger.TREND_REVERSAL,
                    exit_price=current_close,
                    reason="trend reversed to DOWNTREND",
                )
            if ta.momentum_score <= self.momentum_failure_score:
                return ExitDecision(
                    should_exit=True,
                    trigger=ExitTrigger.MOMENTUM_FAILURE,
                    exit_price=current_close,
                    reason=f"momentum_score {ta.momentum_score} <= {self.momentum_failure_score}",
                )

        return ExitDecision(
            should_exit=False,
            trigger=ExitTrigger.NONE,
            exit_price=None,
            reason="no exit condition met",
        )
