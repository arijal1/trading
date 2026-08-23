# AI Crypto Trading & Copy-Trading Platform

Status: **Phase 1 — foundation**. See `docs/ARCHITECTURE.md` for the full
architecture assessment, technology decisions, and phased roadmap (Phases
1-7). This is not yet a trading system: there is no market data ingestion,
no strategy logic, and no order execution path. Phase 1 delivers the
skeleton everything else builds on: schema, config, safety primitives
(emergency stop), and CI — all real and tested, nothing simulated.

Trading mode defaults to `paper` and there is currently no code capable of
placing a real order regardless of configuration (see
`docs/SECURITY.md` and `docs/RISK_MANAGEMENT.md`).

## Documentation

- `docs/ARCHITECTURE.md` — architecture assessment, tech decisions, roadmap
- `docs/DATABASE_SCHEMA.md` — full table reference
- `docs/API_DESIGN.md` — implemented + planned endpoints
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
