# API Design

Base path: `/api/v1`. All responses are JSON; all request/response bodies
are Pydantic models (no free-form dicts). Auth (JWT + RBAC) lands in Phase
5+; Phase 1 endpoints are unauthenticated but structurally isolated so auth
middleware can be added without reshaping routes.

## Implemented in Phase 1

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | Liveness probe: process is up. No DB dependency. |
| GET | `/api/v1/system/status` | Readiness: DB connectivity, current `TRADING_MODE`, emergency-stop / trading-halt state from `system_state`. |
| POST | `/api/v1/trading/emergency-stop` | Sets `system_state.is_emergency_stopped = true`, persists reason/actor, logs an `audit_logs` row, and dispatches a CRITICAL notification (Phase 5, `docs/NOTIFICATIONS.md`). Requires explicit manual reset — see below. |
| POST | `/api/v1/trading/resume` | Manual reset of `is_emergency_stopped` / `is_trading_halted`. Requires a reason; audited; dispatches an INFO notification. |
| POST | `/api/v1/trading/pause` | Sets `is_trading_halted = true` (softer than emergency-stop: no forced position closure); dispatches a WARNING notification. |

## Implemented in Phase 2

Market/asset rows are created directly in the DB for now — there is no
market/exchange onboarding endpoint yet (planned alongside real exchange
adapters in Phase 6). All data below currently comes from the mock
exchange adapter (`docs/EXCHANGE_ADAPTER.md`).

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/assets` | List registered assets. |
| GET | `/api/v1/markets` | List configured markets with exchange/base/quote names joined in. |
| GET | `/api/v1/markets/{id}/candles` | Stored OHLCV candles for a market (`timeframe`, `limit` query params), ascending by time. |
| POST | `/api/v1/markets/{id}/sync` | Fetches missing candles from the configured adapter into `candles` for the last `hours` (`timeframe`, `hours` query params). Idempotent — a fully-cached range makes no adapter call. |
| GET | `/api/v1/markets/{id}/technical-analysis` | Runs `TechnicalAnalysisEngine` over the market's stored candles (`timeframe`, `limit`). Returns `422` if fewer than `MIN_BARS_REQUIRED` (35) bars are stored. |

## Implemented in Phase 3

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/backtests` | Runs `BacktestEngine` over a market's stored candles (`market_id`, `timeframe`, `candle_limit`, optional `config` overrides — see `docs/BACKTESTING.md`). Synchronous (no worker queue yet). Persists to `backtests` against a get-or-created `technical_composite_v1` strategy row. Returns `422` if fewer than `MIN_BARS_REQUIRED + 1` (36) candles are available. |
| GET | `/api/v1/backtests/{id}` | Reads back a persisted backtest result. |

## Implemented in Phase 4

Accounts are created directly in the DB for now, matching the same
"no onboarding endpoint yet" pattern already established for
markets/exchanges in Phase 2 — every route below takes `account_id` as a
path parameter rather than deriving it from an authenticated session,
since auth lands in Phase 5+. See `docs/PAPER_TRADING.md`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/accounts/{id}` | Account balances/mode/starting equity. |
| GET | `/api/v1/accounts/{id}/portfolio` | DB-reconstructed `PortfolioState`: cash (from the fill ledger), equity, exposure by asset, peak/day-start/week-start equity. |
| GET | `/api/v1/accounts/{id}/positions` | Positions for the account, newest first (`status` query param to filter). |
| GET | `/api/v1/accounts/{id}/orders` | Order history, newest first (`limit`, capped at 1000). |
| GET | `/api/v1/accounts/{id}/trades` | Fill history, newest first (`limit`, capped at 1000). |
| POST | `/api/v1/accounts/{id}/paper/tick` | Runs one `PaperTradingSession.run_tick` decision cycle for `(account, market_id, timeframe)`. Requires `account.mode == "paper"` (`422` otherwise). Returns the `TickResult` — one of `OPENED` / `EXIT` / `CAPITAL_RECOVERED` / `HOLD` / `SKIPPED_RISK` / `SKIPPED_SIZE` / `NO_SIGNAL` / `INSUFFICIENT_DATA` — and always records a portfolio snapshot regardless of outcome. |

## Implemented in Phase 5

| Method | Path | Description |
|---|---|---|
| GET | `/metrics` | Prometheus text-format exposition. Deliberately unversioned (not under `/api/v1`) since scrape configs assume a fixed path. See `docs/MONITORING.md`. |

## Planned (documented now, implemented in later phases)

| Method | Path | Phase | Notes |
|---|---|---|---|
| GET | `/performance` | 5 | Sharpe/Sortino/drawdown/etc. for a live/paper account |
| GET | `/risk` | 5 | current risk-limit usage for a live/paper account |
| GET | `/signals` | 5 | latest per-strategy signals, persisted |
| GET | `/decisions` | 5 | AI decision log with explainability fields |
| GET | `/traders` | 5 | followed traders |
| GET | `/traders/{id}` | 5 | trader detail + metrics |
| GET | `/copy-trading` | 5 | copy-trading status/exposure |
| POST | `/copy-trading/follow` | 5 | start following a trader |
| DELETE | `/copy-trading/follow/{id}` | 5 | stop following |

Every planned endpoint returns data already modeled in
`docs/DATABASE_SCHEMA.md`, so no schema rework is expected when they're
implemented. The copy-trading *decision* engines (trader metrics, copy
candidate evaluation, consensus resolution) are already built —
`docs/COPY_TRADING.md` — but have no HTTP surface yet since there's no
live trader-data feed to drive them from.
