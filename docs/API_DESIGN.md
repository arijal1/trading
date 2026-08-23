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
| POST | `/api/v1/trading/emergency-stop` | Sets `system_state.is_emergency_stopped = true`, persists reason/actor, logs an `audit_logs` row. Requires explicit manual reset — see below. |
| POST | `/api/v1/trading/resume` | Manual reset of `is_emergency_stopped` / `is_trading_halted`. Requires a reason; audited. |
| POST | `/api/v1/trading/pause` | Sets `is_trading_halted = true` (softer than emergency-stop: no forced position closure). |

## Planned (documented now, implemented in later phases)

| Method | Path | Phase | Notes |
|---|---|---|---|
| GET | `/account` | 4 | balances, mode |
| GET | `/portfolio` | 3 | equity, exposure, P&L |
| GET | `/positions` | 4 | open/closed positions |
| GET | `/orders` | 4 | order history |
| GET | `/trades` | 4 | fill history |
| GET | `/performance` | 3 | Sharpe/Sortino/drawdown/etc. |
| GET | `/risk` | 3 | current risk-limit usage |
| GET | `/markets` | 2 | configured markets |
| GET | `/assets` | 2 | asset registry + risk scores |
| GET | `/signals` | 3 | latest per-strategy signals |
| GET | `/decisions` | 3 | AI decision log with explainability fields |
| GET | `/traders` | 4 | followed traders |
| GET | `/traders/{id}` | 4 | trader detail + metrics |
| GET | `/copy-trading` | 4 | copy-trading status/exposure |
| POST | `/copy-trading/follow` | 4 | start following a trader |
| DELETE | `/copy-trading/follow/{id}` | 4 | stop following |
| POST | `/backtests` | 3 | launch a backtest run |
| GET | `/backtests/{id}` | 3 | backtest result |

Every planned endpoint returns data already modeled in
`docs/DATABASE_SCHEMA.md`, so no schema rework is expected when they're
implemented.
