# AI Crypto Trading & Copy-Trading Platform

Status: **Phase 3 — backtesting, strategy, and risk engines**. See
`docs/ARCHITECTURE.md` for the full architecture assessment, technology
decisions, and phased roadmap (Phases 1-7). This is not yet a trading
system: there is no AI decision layer, no paper/live order execution, and
no order-execution path against real money. Phases 1-3 deliver the
schema, config, safety primitives (emergency stop), CI, an
exchange-agnostic adapter interface (mock implementation only — no
exchange has been chosen), OHLCV ingestion, a technical analysis engine,
five rule-based entry strategies with weighted aggregation, a dynamic
stop-loss/trailing-stop exit engine, a portfolio risk engine, and a
no-look-ahead backtesting engine — all real, tested, and exercised
end-to-end, nothing simulated in the plumbing sense.

Trading mode defaults to `paper` and there is currently no code capable of
placing a real order regardless of configuration (see
`docs/SECURITY.md` and `docs/RISK_MANAGEMENT.md`).

## Documentation

- `docs/ARCHITECTURE.md` — architecture assessment, tech decisions, roadmap
- `docs/DATABASE_SCHEMA.md` — full table reference
- `docs/API_DESIGN.md` — implemented + planned endpoints
- `docs/EXCHANGE_ADAPTER.md` — exchange abstraction + mock adapter
- `docs/STRATEGY_ENGINE.md` — entry strategies, exit engine, position sizing, portfolio risk engine
- `docs/BACKTESTING.md` — backtesting engine design and scope
- `docs/RISK_MANAGEMENT.md` — risk-control layering
- `docs/SECURITY.md` — secrets, auth, AI-safety boundary

## Repository layout

```
apps/api/          FastAPI backend (this phase's only running service)
infrastructure/     docker-compose.yml, Dockerfiles, monitoring config
docs/               architecture and design docs
.github/workflows/  CI
```

## Running locally

Requires Docker + Docker Compose.

```bash
cp .env.example .env
docker compose -f infrastructure/docker-compose.yml up --build
```

The API is then available at `http://localhost:8000`:

- `GET /api/v1/health` — liveness
- `GET /api/v1/system/status` — DB connectivity, trading mode, emergency-stop state
- `POST /api/v1/trading/emergency-stop` — kill switch (`{"reason": "...", "actor": "..."}`)
- `POST /api/v1/trading/resume` — clears emergency-stop / halt state
- `POST /api/v1/trading/pause` — halts new trades without full emergency stop
- `GET /api/v1/assets`, `GET /api/v1/markets` — registered assets/markets
- `POST /api/v1/markets/{id}/sync?timeframe=1h&hours=72` — ingest OHLCV via the mock exchange adapter
- `GET /api/v1/markets/{id}/candles?timeframe=1h` — stored candles
- `GET /api/v1/markets/{id}/technical-analysis?timeframe=1h` — indicator scores over stored candles
- `POST /api/v1/backtests` — run a backtest over a market's stored candles (`{"market_id": "...", "timeframe": "1h", "candle_limit": 300}`)
- `GET /api/v1/backtests/{id}` — read back a backtest result

Markets/assets/exchanges currently have no creation endpoint (Phase 6 adds
one alongside real exchange onboarding) — insert rows directly for now,
e.g. via `psql` against the `exchanges`, `assets`, and `markets` tables.

## Running without Docker (API only)

```bash
cd apps/api
poetry install
poetry run alembic upgrade head          # requires Postgres reachable at DATABASE_URL
poetry run uvicorn app.main:app --reload
```

## Tests

```bash
cd apps/api
poetry install
poetry run pytest                 # unit tests need no external services
# integration tests additionally need Postgres reachable at DATABASE_URL,
# e.g.: docker compose -f ../../infrastructure/docker-compose.yml up -d postgres
```

## Migrations

```bash
cd apps/api
poetry run alembic revision --autogenerate -m "message"
poetry run alembic upgrade head
```

## Configuration

All runtime configuration is environment variables — see `.env.example`
for the full list (trading mode, live-trading guardrails, capital-recovery
parameters, copy-trading limits, portfolio risk limits). Never commit a
real `.env` file.
