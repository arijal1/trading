# Architecture Assessment & Design

Status: greenfield repository (no prior commits). This document is the design
reference for the AI crypto trading / copy-trading platform, produced before
Phase 1 implementation as required by the project brief. It stays intentionally
concrete about what exists today vs. what is planned.

## 1. Repository Assessment

- No existing code, dependencies, or CI. Nothing to preserve or migrate.
- Target stack (per project requirements): Python/FastAPI backend, Postgres
  (+TimescaleDB extension) for time-series and relational data, Redis for
  caching/queues, Next.js/TypeScript frontend (later phase), Docker Compose
  for local/dev infra, Prometheus/Grafana for observability, GitHub Actions
  for CI.

## 2. Proposed Architecture

The system is built as a **modular monolith** organized into service-like
Python packages under `apps/api/app/services/*`, not literal microservices.
This is a deliberate simplification of the brief's `/services/*` layout: at
this stage a monolith with clean module boundaries is far easier to keep
correct, testable, and auditable than a distributed system, and every module
is designed so it *can* be extracted into its own deployable service later
without changing its public interface. Given the safety requirements (never
let a component silently fail open into a trade), fewer moving parts early on
is the safer choice.

```
Market Data Event
   -> Signal Engine (technical / sentiment / risk / trader-tracking)
   -> Decision Engine (AI reasoning layer, structured output only)
   -> Policy Validator (hard limits; can reject any decision)
   -> Order Manager (idempotent)
   -> Exchange Adapter
   -> Fill Event
   -> Portfolio Manager
   -> Notification Service
```

Every arrow above is a typed, logged, and persisted transition (see
`docs/DATABASE_SCHEMA.md`), so any trade is reconstructible after the fact.

## 3. Technology Decisions

| Concern            | Choice                                   | Why |
|---------------------|-------------------------------------------|-----|
| API framework        | FastAPI + Pydantic v2                    | async, strict schema validation everywhere (needed to keep LLM output out of the execution path unchecked) |
| ORM / migrations     | SQLAlchemy 2.0 (async) + Alembic          | production-grade, explicit migrations, no magic |
| Primary DB           | PostgreSQL 16 + TimescaleDB extension     | relational integrity for orders/positions + efficient OHLCV time-series |
| Cache / queue broker | Redis 7                                   | rate-limit bookkeeping, caching, Celery broker |
| Background jobs      | Celery (or arq later) workers             | market data polling, indicator computation, position monitoring loops |
| Package/dep mgmt     | Poetry                                    | reproducible envs, dev/prod extras |
| Logging              | structlog -> JSON                         | machine-parseable, ships to any log backend |
| Testing              | pytest, pytest-asyncio, httpx AsyncClient | async-first stack |
| Frontend             | Next.js + TypeScript + Tailwind           | `apps/web`, Phase 5 — see docs/DASHBOARD.md |
| Infra (local)        | Docker Compose                            | Postgres, Redis, API, worker, (later) web |
| Observability        | Prometheus client + `/metrics`, Grafana provisioning later | per brief |
| CI                   | GitHub Actions: lint (ruff), type-check (mypy), pytest | |

## 4. Directory Structure (current)

```
apps/api/
  app/
    core/        settings, structured logging, (later) security
    api/v1/      versioned REST routers
    db/          session/engine, ORM models
    schemas/     Pydantic request/response + internal contracts
    services/    engine packages (exchanges, market_data, technical_analysis,
                 strategy, execution, portfolio, backtesting, ...)
    workers/     background job entrypoints (Phase 4+, once Celery is wired up)
  alembic/       migrations
  tests/
infrastructure/  docker-compose.yml, Dockerfiles, monitoring config
docs/            this document + schema/API/risk/security design notes
.github/workflows/  CI
```

`apps/web` (the Next.js dashboard, docs/DASHBOARD.md) was added in Phase 5;
the package boundary existed from Phase 1 so it dropped into place rather
than requiring a restructure.

## 5. Database Schema

See `docs/DATABASE_SCHEMA.md`. Phase 1 creates the full table set from the
brief (users, accounts, exchanges, assets, markets, candles, traders,
trader_metrics, trader_trades, copy_trade_signals, strategies, signals,
decisions, orders, order_events, fills, positions, position_events,
portfolio_snapshots, risk_events, sentiment_events, market_regimes, alerts,
system_events, audit_logs, backtests, model_versions, configuration) so
later phases only add columns/tables, not core structure. Tables are created
now with the columns we know we need; engines that populate them (technical
analysis, sentiment, copy-trading, AI decisioning) are implemented in later
phases.

## 6. API Design

See `docs/API_DESIGN.md`. Phase 1 implements `/health` and
`/system/status`; Phase 2 adds `/assets`, `/markets`, and the
candle/technical-analysis endpoints. Every other endpoint from the brief is
documented with its intended contract so the surface is stable as it's
filled in.

## 7. Trading State Machine

```
NEW -> VALIDATED -> SUBMITTED -> PARTIALLY_FILLED -> FILLED
                 \-> REJECTED
SUBMITTED -> CANCEL_REQUESTED -> CANCELLED
SUBMITTED -> TIMEOUT -> RECONCILING -> (FILLED | CANCELLED | REJECTED)
```

Position side:
```
OPENING -> OPEN -> (CAPITAL_RECOVERY_PENDING -> PROFIT_RUNNER) -> CLOSING -> CLOSED
OPEN -> CLOSING -> CLOSED   (direct exit, no capital-recovery phase)
```
Every transition is a `position_events` / `order_events` row — never an
in-place mutation without an event record.

## 8. Risk-Management Design

Hard, non-bypassable limits live in a `PolicyValidator` that sits between
the AI decision layer and the Order Manager (see section 15 of the brief).
It is implemented as plain deterministic Python — no LLM in this path — and
checks, per decision: max position size, max daily/weekly loss, max
portfolio exposure, max asset concentration, max token risk score, max
slippage, max copy-trading exposure, trading-halt/emergency-stop state, and
`TRADING_MODE`/live-trading guardrails (Section 39 of the brief). A rejected
decision is persisted with its reject reason; it never silently disappears.

## 9. Copy-Trading Design

`TraderTrackingEngine` maintains scored traders; `CopyTradeDecisionEngine`
turns a trader's trade into a candidate signal only if the trader passes
`MIN_TRADER_SCORE`, then applies per-trader and total exposure caps,
max price-deviation-since-original-entry checks (no chasing), and
multi-trader consensus resolution before a candidate signal ever reaches the
Decision Engine. Implemented in Phase 4 (paper-trading phase) per the
brief's phased plan — schema lands in Phase 1.

## 10. Capital-Recovery Design

`ProfitManager` tracks `initial_capital` per position. Once unrealized
profit passes `MIN_PROFIT_BEFORE_CAPITAL_RECOVERY`, it computes the unit
quantity whose sale — net of estimated fees and slippage — would return
`INITIAL_CAPITAL_RECOVERY_TARGET` fraction of the original capital. That
partial sell is proposed to the same Policy Validator as any other order.
The remainder becomes a `PROFIT_RUNNER` position managed purely by
trailing-stop / structure rules — never treated as "risk-free," per the
brief's explicit requirement. Implemented in Phase 4.

## 11. Backtesting Design

Deterministic, seedable simulator over historical candles with a fee,
slippage, latency, and partial-fill model; walk-forward validation to
control look-ahead bias; the exact same `ExchangeAdapter` interface used
live, backed by a `SimulatedExchangeAdapter`, so strategy code is identical
in backtest, paper, and live modes. Implemented in Phase 3.

## 12. Security Model

See `docs/SECURITY.md`. Highlights: secrets only via environment variables /
secret manager, never committed (`.env.example` documents names only);
exchange API keys stored encrypted at rest with withdrawal permissions
explicitly disallowed; JWT auth + RBAC for the API (Phase 5+); structured
audit log for every state-changing action; strict Pydantic validation on
every external input, including AI output — no free-form LLM text is ever
parsed into an order.

## 13. Implementation Roadmap

Phases follow the brief's Section 59 exactly:

- **Phase 1 (done)**: repo scaffold, Docker Compose, full DB schema
  + migrations, settings/config, structured logging, test framework, CI,
  `/health` + `/system/status`, emergency-stop persistence primitive.
- **Phase 2 (done)**: `ExchangeAdapter` interface + `MockExchangeAdapter`
  (docs/EXCHANGE_ADAPTER.md); `MarketDataEngine.sync_candles` — idempotent
  OHLCV ingestion into `candles` with gap detection logged to
  `system_events`; `TechnicalAnalysisEngine` (SMA/EMA/RSI/MACD/Bollinger/
  ATR/ADX/VWAP/StochRSI/volume/momentum/volatility/support-resistance/
  trend/breakout/reversal, all pure computation, no order placement) over
  `app/services/technical_analysis/indicators.py`; `GET /assets`,
  `GET /markets`, `GET /markets/{id}/candles`,
  `POST /markets/{id}/sync`, `GET /markets/{id}/technical-analysis`.
- **Phase 3 (done)**: `PortfolioRiskEngine` + position sizing
  (docs/STRATEGY_ENGINE.md) — pure, DB-agnostic checks against a
  `PortfolioState` snapshot (drawdown, daily/weekly loss, position size,
  portfolio exposure, asset concentration, max open positions);
  5 independent entry-strategy signal generators (trend following,
  momentum, breakout, pullback, mean reversion) + `StrategyAggregator`
  weighted combination; `ExitEngine` (ATR-based dynamic stop-loss,
  ratcheting trailing stop, take-profit, max-hold-time, trend-reversal,
  momentum-failure); performance metrics (Sharpe/Sortino/CAGR/Calmar/
  drawdown/win-rate/profit-factor/expectancy); `BacktestEngine`
  (docs/BACKTESTING.md) — no-look-ahead walk-forward simulator over
  stored candles tying all of the above together, with explicit fee/
  slippage modeling; `POST /backtests`, `GET /backtests/{id}`.
- **Phase 4 (done)**: `OrderManager` (docs/PAPER_TRADING.md) — idempotent
  order submission keyed on `client_order_id`, reconciliation via
  `get_order_status` before any retry, `OrderReconciliationRequiredError`
  raised rather than ever silently resubmitting; `PositionManager` —
  fills-to-positions bridge with weighted-average adds and persisted
  exit-engine state (stop/take-profit/trailing-stop/highest-price/
  max-hold, added to the `positions` table via migration
  `060db36f1e44`) so it survives between ticks; `ProfitManager`
  (docs/PAPER_TRADING.md) — capital-recovery partial exits that never
  liquidate a whole position or leave a dust remainder, transitioning
  the remainder to a trailing-stop-managed `PROFIT_RUNNER`; trader
  performance tracking + copy-trade decision engines
  (docs/COPY_TRADING.md) — dimensionless cross-trader-comparable metrics,
  price-deviation chase guard, weighted multi-trader consensus; a
  DB-backed `PortfolioState` builder reconstructing cash from the
  immutable fill ledger rather than a mutable balance column; the
  `PaperTradingSession` orchestrator tying market data, TA, strategy,
  sizing, risk, exits, and capital recovery into one per-tick decision
  cycle; `GET /accounts/{id}`, `GET /accounts/{id}/portfolio`,
  `GET /accounts/{id}/positions`, `GET /accounts/{id}/orders`,
  `GET /accounts/{id}/trades`, `POST /accounts/{id}/paper/tick`.
- **Phase 5 (done)**: `NotificationChannel` abstraction
  (docs/NOTIFICATIONS.md) — mirrors `ExchangeAdapter`'s pattern — plus
  `LogNotificationChannel` (always available) and
  `TelegramNotificationChannel` (public Bot API, added only when both
  credentials are configured); `NotificationService` fans one event out
  to every channel and persists an `alerts` row per attempt regardless of
  delivery outcome; wired into `PaperTradingSession` (position
  opened/exit/capital-recovered) and `system_state` (emergency-
  stop/pause/resume). Prometheus `GET /metrics` (docs/MONITORING.md) —
  order/position/risk/notification counters plus tick-duration and
  kill-switch gauges, all with bounded label sets; a documented starter
  Grafana panel list (no live Grafana instance in this environment to
  export a verified dashboard JSON against). `apps/web`
  (docs/DASHBOARD.md) — Next.js 16 dashboard: system status +
  emergency-stop/pause/resume controls, an account list, and a per-
  account portfolio/positions/orders/trades view with a "run a paper
  tick" control, talking directly to the API from the browser (added
  `CORSMiddleware` + `GET /accounts` list endpoint to support it).
  Verified with a live Playwright pass against a running API and real
  Postgres, since this phase has no automated frontend test suite yet.
- **Phase 6**: live exchange adapter, live order management, security
  hardening.
- **Phase 7**: production deployment, backup/recovery, docs.

No live-trading code is implemented until paper trading, risk controls,
order reconciliation, and tests for all of the above are complete and
passing, per the brief's explicit requirement.

## Assumptions made (documented per brief Section 62)

- No specific exchange was named and no credentials were provided, so Phase
  1 ships the `ExchangeAdapter` interface plus a schema-ready `mock`
  implementation only; a real adapter is added once a specific,
  API-key-bearing exchange is chosen (Section 4 of the brief explicitly
  forbids reverse-engineering private endpoints).
- Default `TRADING_MODE=PAPER`; live trading is structurally impossible
  until Phase 6+ code exists, regardless of configuration.
- Monolith-first over literal microservices (see Section 2) — a documented
  deviation from the brief's directory sketch, chosen for correctness and
  auditability at this stage.
