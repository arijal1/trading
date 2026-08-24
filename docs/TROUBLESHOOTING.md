# Troubleshooting

## Start here

**Before installing anything** — see what's already on the machine
(read-only, changes nothing, works without the repo cloned):

```bash
bash scripts/precheck.sh
```

**Once the repo is cloned and you've tried to start it:**

```bash
bash scripts/doctor.sh
```

It checks Docker, `.env`, port conflicts, container health, and whether
the API and dashboard actually answer — then prints the specific command
to fix whatever it found. Pure bash, so it works even when nothing else
does.

---

## "Can't connect to the server"

In rough order of how often each one is the actual cause.

### 1. Docker isn't running

The single most common cause. Docker Desktop being *installed* is not the
same as the daemon *running*.

```bash
docker info      # errors → the daemon is down
```

Start Docker Desktop, or on Linux `sudo systemctl start docker`.

### 2. Port 5432 is already taken

Very common: if you have Postgres installed locally it already owns 5432,
so the container can't bind and `compose up` fails — which reads as "the
app won't start" rather than "a port is busy".

```bash
POSTGRES_PORT=5433 docker compose -f infrastructure/docker-compose.yml up -d
```

Same pattern for `REDIS_PORT`, `API_PORT`, `WEB_PORT`, `PROMETHEUS_PORT`.

These are **shell** environment variables, not `.env` entries. Compose
resolves `${VAR}` in the compose file from a `.env` next to *that file*
(`infrastructure/`), not the repo root, so setting them in the root `.env`
will not work. Prefix the command as above, or use
`--env-file infrastructure/.env`.

Note: if you change `API_PORT`, also update `CORS_ALLOWED_ORIGINS` in
`.env` and rebuild the web image — the dashboard's API URL is baked in at
build time (see below).

### 3. No `.env` file

The api service declares `env_file: ../.env`. Without it compose refuses
to start that service.

```bash
cp .env.example .env
```

### 4. The web image was built with the wrong API URL

Every dashboard fetch runs **in your browser**, so `NEXT_PUBLIC_API_BASE_URL`
must be the URL your browser uses — and Next.js bakes it in at *build*
time, not run time. Changing it in `.env` and restarting does nothing; the
image has to be rebuilt.

```bash
docker compose -f infrastructure/docker-compose.yml up --build -d web
```

Symptom: the dashboard loads, but panels sit on "Loading…" forever. Open
your browser's devtools Network tab — you'll see failed requests to
whatever URL got baked in.

### 4b. Running on a Pi/server you browse to from another machine

The default bakes `http://localhost:8000` into the dashboard. If the
browser is on a different machine from the stack, `localhost` is *the
browser's* machine — so every request fails. Set `PUBLIC_HOST` to the
host's LAN IP and add the matching origin to `CORS_ALLOWED_ORIGINS`:

```bash
# in .env
CORS_ALLOWED_ORIGINS=http://192.168.1.50:3001

PUBLIC_HOST=192.168.1.50 WEB_PORT=3001 \
  docker compose -f infrastructure/docker-compose.yml up --build -d
```

`PUBLIC_HOST` is read at *build* time, so it needs `--build`, not just a
restart.

### 5. The dashboard loads but every panel says "Loading…"

Usually CORS. The dashboard is a different origin from the API, so the API
must allow it. Check `CORS_ALLOWED_ORIGINS` in `.env` includes the exact
origin you're browsing from — `http://localhost:3000` and
`http://127.0.0.1:3000` are *different* origins to a browser, and the
default only lists both because that mismatch is so easy to hit.

### 6. Containers start then immediately die

```bash
docker compose -f infrastructure/docker-compose.yml logs --tail=50 api
docker compose -f infrastructure/docker-compose.yml logs --tail=50 web
```

- API exits complaining about the database → migrations failed. The api
  service runs `alembic upgrade head` on start; if Postgres wasn't ready
  or the volume is from an incompatible older schema, see "Start over".
- Web fails during build with a native-module or platform error → you're
  likely missing `.dockerignore`, so the build copied your host's
  `node_modules` (with macOS/Windows binaries) into a Linux image. Confirm
  `.dockerignore` exists at the repo root, then rebuild with
  `--no-cache`.

### 7. Everything is up but the dashboard is empty

That's not an error — a fresh database has no accounts or markets, and
there's no onboarding endpoint yet.

```bash
docker compose -f infrastructure/docker-compose.yml exec api \
  python -m app.cli seed-demo
```

---

## "I ran a tick and nothing happened"

Expected. Most ticks return `HOLD` — that's the strategy declining to
trade, not a failure.

Two things to check:

1. **Did you sync candles?** With no price history the tick returns
   `INSUFFICIENT_DATA`. It needs at least 35 bars.
   ```bash
   curl http://localhost:8000/api/v1/markets      # copy a market id
   curl -X POST "http://localhost:8000/api/v1/markets/<ID>/sync?timeframe=1h&hours=300"
   ```
2. **One tick is one decision.** Entries and exits appear when you tick
   repeatedly as new candles arrive, not from a single click.

Every outcome is explicit — `OPENED`, `EXIT`, `CAPITAL_RECOVERED`,
`HOLD`, `SKIPPED_RISK`, `SKIPPED_SIZE`, `NO_SIGNAL`, `INSUFFICIENT_DATA` —
so the `detail` field tells you exactly why nothing happened.

---

## "Live trading won't turn on"

Working as designed. See `docs/LIVE_TRADING.md`. To see precisely which
gates are closed:

```bash
curl "http://localhost:8000/api/v1/trading/live-readiness?account_id=<ID>"
```

Note that **no exchange venue is integrated**, so live trading cannot work
regardless of configuration — that is the first blocker, before any of the
guardrails.

---

## Start over from scratch

Destroys the database volume — you'll lose all local trading history and
need to re-seed.

```bash
docker compose -f infrastructure/docker-compose.yml down -v
docker compose -f infrastructure/docker-compose.yml up --build -d
docker compose -f infrastructure/docker-compose.yml exec api python -m app.cli seed-demo
```

---

## Running without Docker

Useful when you want to see tracebacks directly.

```bash
# Terminal 1 — needs Postgres reachable at DATABASE_URL
cd apps/api
poetry install
poetry run alembic upgrade head
poetry run python -m app.cli seed-demo
poetry run uvicorn app.main:app --reload

# Terminal 2
cd apps/web
cp .env.example .env.local
npm install
npm run dev
```

One gotcha specific to `next dev`: it treats `localhost` and `127.0.0.1`
as **different origins** and returns 403 on JS chunks for the mismatched
one, which silently prevents hydration — the page sits on "Loading…" with
no console error explaining why. Use `localhost` consistently. This
affects the dev server only, not the Docker/production build.
