# AI Crypto Trading & Copy-Trading Platform

Status: **Phase 6 — live-trading safety layer and security hardening**.
See `docs/ARCHITECTURE.md` for the full architecture assessment,
technology decisions, and phased roadmap (Phases 1-7). This is not yet a
live trading system: there is no AI decision layer and no order-execution
path against real money — everything that executes an order today is
paper trading against a mock exchange adapter. Phases 1-4 deliver the
schema, config, safety primitives (emergency stop), CI, an
exchange-agnostic adapter interface (mock implementation only — no
exchange has been chosen), OHLCV ingestion, a technical analysis engine,
five rule-based entry strategies with weighted aggregation, a dynamic
stop-loss/trailing-stop exit engine, a portfolio risk engine, a
no-look-ahead backtesting engine, and a full paper-trading loop (order
manager, position manager, capital-recovery profit manager, copy-trading
decision engines, and the orchestrator tying them together) — all real,
tested, and exercised end-to-end, nothing simulated in the plumbing sense.
Phase 5 adds a notification service (log + Telegram channels), Prometheus
metrics, and a Next.js dashboard (`apps/web`). Phase 6 adds the
live-trading safety layer: an encrypted credential vault, a
non-bypassable Section 39 pre-flight guard, JWT auth + RBAC, secret
redaction in logs, and a resilient venue-agnostic adapter base.

Trading mode defaults to `paper`, and **no exchange venue is integrated**,
so there is currently no code capable of placing a real order regardless
of configuration. Even with a venue, the default configuration refuses
live trading at five independent gates — see `docs/LIVE_TRADING.md`,
`docs/SECURITY.md`, and `docs/RISK_MANAGEMENT.md`.

## Documentation

- `docs/ARCHITECTURE.md` — architecture assessment, tech decisions, roadmap
- `docs/DATABASE_SCHEMA.md` — full table reference
- `docs/API_DESIGN.md` — implemented + planned endpoints
- `docs/EXCHANGE_ADAPTER.md` — exchange abstraction + mock adapter
- `docs/STRATEGY_ENGINE.md` — entry strategies, exit engine, position sizing, portfolio risk engine
- `docs/BACKTESTING.md` — backtesting engine design and scope
- `docs/PAPER_TRADING.md` — order manager, position manager, profit manager, paper-trading orchestrator
- `docs/COPY_TRADING.md` — trader performance tracking, copy-trade decisioning
- `docs/NOTIFICATIONS.md` — notification channels, dispatch points
- `docs/MONITORING.md` — Prometheus metrics, suggested Grafana panels
- `docs/DASHBOARD.md` — Next.js dashboard architecture and scope
- `docs/LIVE_TRADING.md` — live-trading guardrails, credential vault, why no venue is wired up
- `docs/AUTH.md` — JWT auth, RBAC, admin bootstrap
- `docs/TROUBLESHOOTING.md` — when it won't start or won't connect
- `docs/RISK_MANAGEMENT.md` — risk-control layering
- `docs/SECURITY.md` — secrets, auth, AI-safety boundary

## Repository layout

```
apps/api/           FastAPI backend
apps/web/            Next.js dashboard (docs/DASHBOARD.md)
infrastructure/      docker-compose.yml, Dockerfiles, monitoring config
docs/                architecture and design docs
.github/workflows/   CI
```

## Quickstart

Requires Docker + Docker Compose. From a clean clone:

```bash
cp .env.example .env
docker compose -f infrastructure/docker-compose.yml up --build -d

# One-time: create the demo exchange, markets, and a paper account.
# (There is no onboarding endpoint yet — see docs/API_DESIGN.md.)
docker compose -f infrastructure/docker-compose.yml exec api \
  python -m app.cli seed-demo
```

Then open **http://localhost:3000**. You should see the system-status
panel and one "Demo Paper Account".

**If anything doesn't come up**, run the doctor — it checks Docker, ports,
`.env`, container health, and reachability, then prints the exact command
to fix what it finds:

```bash
bash scripts/doctor.sh
```

See `docs/TROUBLESHOOTING.md` for the full list of causes. The two most
common by far: Docker Desktop installed but not *running*, and port 5432
already owned by a locally-installed Postgres (fix:
`POSTGRES_PORT=5433 docker compose -f infrastructure/docker-compose.yml up -d`).

To make it actually trade (paper only — nothing here can touch real
money), click into the account and:

1. Sync some price history first, or the tick has nothing to analyse:
   ```bash
   curl http://localhost:8000/api/v1/markets          # copy a market id
   curl -X POST "http://localhost:8000/api/v1/markets/<MARKET_ID>/sync?timeframe=1h&hours=300"
   ```
2. Press **Run paper tick** on the account page.

Each tick is one decision cycle. Most ticks return `HOLD` — that is the
strategy declining to trade, not a failure. Ticking repeatedly as new
candles arrive is what produces entries and exits.

The API is at http://localhost:8000 (`/docs` for interactive OpenAPI),
Prometheus metrics at http://localhost:8000/metrics, and Prometheus
itself at http://localhost:9090.

### Key endpoints

- `GET /api/v1/health` — liveness
- `GET /api/v1/system/status` — DB connectivity, trading mode, emergency-stop state
- `POST /api/v1/trading/emergency-stop` — kill switch (`{"reason": "...", "actor": "..."}`)
- `POST /api/v1/trading/resume` / `POST /api/v1/trading/pause`
- `GET /api/v1/trading/live-readiness?account_id=...` — why live trading is (correctly) refused
- `GET /api/v1/assets`, `GET /api/v1/markets`, `GET /api/v1/accounts`
- `POST /api/v1/markets/{id}/sync?timeframe=1h&hours=300` — ingest OHLCV via the mock adapter
- `GET /api/v1/markets/{id}/technical-analysis?timeframe=1h`
- `POST /api/v1/backtests` — backtest over stored candles
- `POST /api/v1/accounts/{id}/paper/tick` — one paper-trading decision cycle

Assets/exchanges/markets/accounts beyond the demo seed have no creation
endpoint yet (that lands with real exchange onboarding, which is blocked
on choosing a venue — see `docs/LIVE_TRADING.md`); insert rows directly
via `psql` for now.

## Running without Docker

```bash
cd apps/api
poetry install
poetry run alembic upgrade head          # requires Postgres reachable at DATABASE_URL
poetry run uvicorn app.main:app --reload
```

```bash
cd apps/web
cp .env.example .env.local
npm install
npm run dev
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

`MASTER_ENCRYPTION_KEY` and `JWT_SECRET_KEY` have no defaults by design —
generate both with:

```bash
cd apps/api && poetry run python -m app.cli generate-keys
```

An unset encryption key makes storing exchange credentials fail loudly
rather than silently writing plaintext; a default signing key would be a
publicly-known key anyone could forge admin tokens with.
