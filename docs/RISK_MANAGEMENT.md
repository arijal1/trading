# Risk Management Design

## Layers (outer to inner, per `docs/ARCHITECTURE.md` Section 2)

1. **Token/asset risk screen** — rejects assets whose computed risk score
   exceeds `MAX_TOKEN_RISK_SCORE` before any signal is even generated.
2. **FOMO / anti-pump screen** — blocks entries into already-vertical moves,
   abnormal volume spikes, or coordinated-pump patterns (Sections 22-23).
3. **Strategy/signal layer** — each strategy produces an independent signal;
   never a single-indicator "3 things say buy" rule (Section 16).
4. **Copy-trade eligibility** — a trader must clear `MIN_TRADER_SCORE`
   before its trades become copy-signal candidates; multi-trader conflicts
   resolve via weighted consensus, not first-signal-wins (Sections 11-13).
5. **AI decision layer** — combines all of the above into a structured,
   schema-validated decision (never free-form text).
6. **Policy Validator (hard limits, deterministic, cannot be bypassed by
   the AI layer)** — checks, per decision:
   - `MAX_POSITION_SIZE`, `MAX_PORTFOLIO_EXPOSURE`, `MAX_ASSET_CONCENTRATION`
   - `MAX_DAILY_LOSS`, `MAX_WEEKLY_LOSS`, `MAX_DRAWDOWN`
   - `MAX_COPY_TRADING_EXPOSURE`, `MAX_OPEN_POSITIONS`
   - `MAX_SLIPPAGE_PERCENT`, `MAX_TOKEN_RISK_SCORE`
   - current `system_state` (emergency-stop / trading-halt)
   - live-trading guardrails when `TRADING_MODE=LIVE`
   A rejection is persisted with a reason; it is never a silent no-op.
7. **Order Manager** — idempotent submission (`client_order_id`), status
   check before any retry, reconciliation on reconnect (Sections 24-25).
8. **Exit Engine** — continuously re-evaluates open positions for stop-loss,
   take-profit, trailing-stop, regime change, or risk-limit triggers
   (Section 17), independent of whether a new entry signal exists.

## Capital-preservation specific rules (Section 2 of the brief)

- `INITIAL_CAPITAL_RECOVERY_ENABLED`, `INITIAL_CAPITAL_RECOVERY_TARGET`,
  `MIN_PROFIT_BEFORE_CAPITAL_RECOVERY`, `PROFIT_POSITION_ENABLED`,
  `TRAILING_STOP_PERCENT`, `MIN_POSITION_VALUE`, `MAX_SLIPPAGE_PERCENT`,
  `TAKE_PROFIT_LEVELS` are all runtime-configurable (see `.env.example`).
- Capital recovery is a *proposal* (a partial sell sized to approximately
  recover initial capital net of estimated fees/slippage), validated by the
  same Policy Validator as any other order — it is not a bypass path.
- A "profit runner" remainder is never treated as risk-free; it is managed
  by the same trailing-stop / exit-engine machinery as any open position.

## Breach response

On any hard-limit breach: halt new trade entries
(`system_state.is_trading_halted = true`), record a `risk_events` row,
notify via the configured channel (Telegram, Phase 5), and optionally
close risky positions if `EMERGENCY_CLOSE_POSITIONS_ON_BREACH` is enabled.
Resuming trading always requires an explicit, audited manual action —
never an automatic timeout-based resume.

## `system_state` is a true singleton, not just "usually one row"

`app/services/system_state.py`'s `get_or_create_state` upserts against a
fixed, well-known primary key (`SYSTEM_STATE_ID`) rather than doing a
plain "SELECT ... LIMIT 1, insert if empty" check. That distinction
matters specifically because this table backs the kill switch: a naive
check-then-insert lets two concurrent first-ever callers (e.g. two
near-simultaneous `POST /trading/emergency-stop` requests before any row
exists) both see nothing and both insert a row — and a later
`SELECT ... LIMIT 1` elsewhere would then return an arbitrary one of the
two, meaning an emergency stop set on one row could be silently invisible
to code that happens to read the other. This was found via review and
fixed; a regression test
(`test_concurrent_first_callers_never_create_a_second_row`) fires 10 real
concurrent DB sessions at it and confirms exactly one row survives, and
the same behavior was verified with 10 genuinely concurrent HTTP requests
against a running server.

## Audit/event timestamps were silently frozen — also found and fixed

`audit_logs.occurred_at`, `risk_events.occurred_at`, `system_events.occurred_at`,
`alerts.sent_at`, and eight other event-timestamp columns used
`server_default="now()"` — a bare Python string. Postgres treats a quoted
string default as a constant and freezes it at the moment the column's
DEFAULT is set, rather than the intended "evaluate `now()` fresh on every
insert" you get from `server_default=func.now()` (a well-known Postgres
pitfall, and the pattern every other timestamp column in this schema
already used correctly via `TimestampMixin`). Every row inserted into
those tables recorded the same fixed timestamp regardless of when it was
actually created — found live, while manually exercising the running
platform, when three separate emergency-stop/resume audit rows all came
back with the identical `occurred_at`. Fixed for all 14 affected columns
across 5 model files via migration `815708821b74`, with
`compare_server_default=True` now enabled in `alembic/env.py` so
autogenerate catches this class of drift in the future (it doesn't by
default), and a regression test
(`test_audit_log_occurred_at_advances_across_separate_commits`) that was
verified to fail against the old code before the fix and pass after.
