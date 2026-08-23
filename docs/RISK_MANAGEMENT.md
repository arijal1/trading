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
