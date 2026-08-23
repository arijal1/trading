# Database Schema (Phase 1)

PostgreSQL, intended to run with the TimescaleDB extension enabled (candles
table is a natural hypertable candidate; not converted to a hypertable in
Phase 1 to keep the first migration portable to plain Postgres for local
dev — revisit once volume requires it).

All tables use a UUID primary key (`id`) and `created_at`/`updated_at`
timestamps unless noted. Money/quantity columns use `NUMERIC` (never
float) to avoid rounding drift in P&L math.

| Table | Purpose | Key columns |
|---|---|---|
| `users` | platform users | email, hashed_password, role |
| `accounts` | a user's trading account (paper or live) | user_id, name, mode (paper/shadow/live), base_currency |
| `exchanges` | configured exchange/broker connections | name, adapter_type, api_key_encrypted, api_secret_encrypted, withdrawals_disabled |
| `assets` | tradable assets | symbol, chain, contract_address, decimals |
| `markets` | tradable pairs per exchange | exchange_id, base_asset_id, quote_asset_id, symbol, trading_rules (jsonb) |
| `candles` | OHLCV time series | market_id, timeframe, ts, open, high, low, close, volume |
| `traders` | followed traders/wallets | wallet_address, display_name, source, strategy_classification, risk_score, consistency_score |
| `trader_metrics` | rolling performance stats per trader | trader_id, win_rate, avg_return, max_drawdown, profit_factor, avg_hold_time, num_trades, last_activity_at |
| `trader_trades` | observed trades by a followed trader | trader_id, asset_id, side, entry_price, exit_price, size, opened_at, closed_at, realized_pnl |
| `copy_trade_signals` | candidate copy-trade signals derived from trader_trades | trader_id, account_id, source_trade_id, status, latency_ms, price_deviation_pct |
| `strategies` | strategy registry | name, version, parameters (jsonb), enabled |
| `signals` | per-strategy raw signals feeding the decision engine | strategy_id, asset_id, direction, score, data_timestamp, data_age_ms |
| `decisions` | AI/decision-engine output (structured, schema-validated) | account_id, asset_id, action, confidence, reason_codes (jsonb), risk_score, expected_reward, expected_risk, position_size, entry_price, stop_loss, take_profit, trailing_stop, strategy, supporting_signals (jsonb), model_version, policy_result |
| `orders` | order intents/records | account_id, decision_id, client_order_id (unique, idempotency key), exchange_order_id, asset_id, side, type, quantity, limit_price, stop_price, status |
| `order_events` | append-only order status transitions | order_id, event_type, payload (jsonb), occurred_at |
| `fills` | executed fill records | order_id, price, quantity, fee, slippage, filled_at |
| `positions` | open/closed positions | account_id, asset_id, status (OPENING/OPEN/CAPITAL_RECOVERY_PENDING/PROFIT_RUNNER/CLOSING/CLOSED), initial_capital, quantity, avg_entry_price, capital_recovered, profit_locked |
| `position_events` | append-only position lifecycle events | position_id, event_type, payload (jsonb), occurred_at |
| `portfolio_snapshots` | periodic portfolio state | account_id, equity, cash, exposure, unrealized_pnl, realized_pnl, drawdown, snapshot_at |
| `risk_events` | risk-limit breaches / halts | account_id, event_type, details (jsonb), occurred_at |
| `sentiment_events` | sentiment engine outputs | asset_id, source, sentiment_score, confidence, velocity, occurred_at |
| `market_regimes` | regime classification over time | market_id, regime, confidence, detected_at |
| `alerts` | user-facing notifications log | account_id, type, payload (jsonb), sent_at, channel |
| `system_events` | infra/system-level events (disconnects, outages) | component, event_type, details (jsonb), occurred_at |
| `audit_logs` | full audit trail of state-changing actions | actor, action, entity_type, entity_id, before (jsonb), after (jsonb), occurred_at |
| `backtests` | backtest run metadata + results | strategy_id, parameters (jsonb), date_range, seed, metrics (jsonb) |
| `model_versions` | AI/strategy/parameter version registry | component, version, parameters (jsonb), approved, approved_at |
| `configuration` | runtime-editable config overrides (audited) | key, value (jsonb), updated_by, updated_at |
| `system_state` | singleton emergency-stop / trading-halt state | is_emergency_stopped, is_trading_halted, reason, set_by, set_at |

Notes:
- `orders.client_order_id` carries the idempotency guarantee described in
  Section 25/47 of the brief: the Order Manager always checks for an
  existing order by this key before submitting, and always queries status
  before retrying after a timeout.
- `order_events` and `position_events` are append-only by convention
  (enforced at the application layer in Phase 2+) so every state change is
  reconstructible — this is what Section 57 ("Auditability") requires.
- Money columns are `NUMERIC(38, 18)` to safely hold crypto-precision
  quantities and fiat-precision prices in the same schema.
