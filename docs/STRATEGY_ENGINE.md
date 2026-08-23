# Entry Strategies, Exit Engine, Risk & Portfolio Engines (Phase 3)

## Entry strategies (brief Section 16)

`app/services/strategy/signals.py` implements five independent,
rule-based signal generators, each looking only at a
`TechnicalAnalysisResult` (Phase 2):

- `trend_following_signal` — direction/strength of the current trend
- `momentum_signal` — RSI + MACD histogram
- `breakout_signal` — resistance breakout (with volume confirmation) or
  support breakdown
- `pullback_signal` — a dip toward EMA20 within an uptrend (or a rally
  toward it within a downtrend)
- `mean_reversion_signal` — contrarian fade of RSI/Bollinger extremes

Copy-trading is deliberately absent — it needs trader-tracking data that
doesn't exist until Phase 4.

`app/services/strategy/aggregator.py`'s `StrategyAggregator` combines
them: each signal's signed strength is weighted (`DEFAULT_STRATEGY_WEIGHTS`,
overridable) and averaged into a single -100..100 score. Only a score past
`buy_threshold`/`sell_threshold` becomes an actionable BUY/SELL — this is
the brief's explicit requirement to avoid "3 indicators say buy therefore
buy." A `HOLD` is the common case, not a failure mode.

## Exit engine (brief Sections 17-19)

`app/services/execution/exit_engine.py`:

- `compute_dynamic_stop_loss` sizes the initial stop off ATR, not a fixed
  percentage.
- `advance_position_state` ratchets a trailing stop up as price makes new
  highs — it never loosens a stop that's already tightened. Takes the
  bar's *high* (the actual intrabar peak), not its close.
- `ExitEngine.evaluate` checks, in order: stop/trailing-stop (against the
  bar's *low*), take-profit (against the bar's *high*), max-hold-time,
  trend-reversal, momentum-failure (all three against the bar's *close*)
  — returning the first trigger that fires. `ExitDecision.fills_intrabar`
  tells the caller whether the fill happens within the same bar (true for
  stop/trailing-stop/take-profit — they're resting orders, and the bar
  being evaluated is already fully known, so checking its high/low isn't
  look-ahead) or is deferred to the next bar's open (false for the
  close-based signal exits, exactly like entries).

  This intrabar check is not optional polish: checking only the close
  would let a bar that pierced the stop and recovered by its close skip
  the exit entirely, silently overstating backtested performance. That
  was a real bug in an earlier version of this module, found via review
  and fixed — see the regression tests in `tests/unit/test_exit_engine.py`
  (`test_evaluate_detects_intrabar_stop_hit_even_when_close_recovers_above_stop`
  and its take-profit counterpart).

Scope note: Section 19 describes a multi-stage break-even -> profit-lock
-> trail progression, and Section 2/42 describe capital-recovery partial
exits. Both need a `ProfitManager` tracking initial capital per position —
Phase 4. This module ships the single-parameter ratcheting trailing stop
Phase 4 builds on, not the full staged progression.

## Position sizing (brief Section 20)

`app/services/portfolio/position_sizing.py`:

- `fixed_fractional_size` — quantity such that a stop-loss fill loses
  exactly `equity * risk_pct`.
- `volatility_adjusted_size` — same idea, sized directly off ATR rather
  than a pre-computed stop distance.
- `calculate_position_size` — the entrypoint: applies the fixed-fractional
  formula, caps by `max_position_value_pct`, and returns a zero quantity
  (a skip, not an error) when the resulting notional is below
  `min_position_value`.

## Portfolio risk engine (brief Section 21)

`app/services/portfolio/risk_engine.py`'s `PortfolioRiskEngine` is pure
and DB-agnostic: it takes a `PortfolioState` snapshot and `RiskLimits`,
and answers whether trading is currently allowed
(`check_trading_allowed`: drawdown, daily loss, weekly loss, emergency
stop, trading halt) and whether a specific proposed position would breach
a limit (`check_new_position`: position size, portfolio exposure, asset
concentration, max open positions). Every rejection names the specific
check(s) that failed.

It has no opinion about where the `PortfolioState` came from — the
backtesting engine builds one in memory per bar; a future live/paper
engine (Phase 4) will build one from the `positions`/`portfolio_snapshots`
tables. Backtests never consult live `system_state` (there's no live
trading to halt during a historical run).
