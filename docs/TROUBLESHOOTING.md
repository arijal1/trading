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

### 2b. Image pulls fail with "TLS handshake timeout"

```
failed to resolve reference "docker.io/...": net/http: TLS handshake timeout
```

A transport failure, not a missing image. `docker compose up` pulls
several images in parallel, which on a slow or flaky link (a Pi on wifi
especially) opens multiple TLS sessions at once and times out.

```bash
bash scripts/pull.sh
```

Pulls one image at a time with retries. Docker keeps completed layers, so
each attempt resumes rather than restarting.

If it still fails, read *which* error repeats — they need different fixes:

| Error | Cause | Fix |
|---|---|---|
| `lookup registry-1.docker.io on 192.168.x.1:53: i/o timeout` | your router's DNS is too slow/flaky for the daemon | `sudo bash scripts/fix-docker-dns.sh` |
| `dial tcp [2600:...]:443: network is unreachable` | a AAAA record on a network that can't route IPv6 | same script (public IPv4 resolvers) |
| `TLS handshake timeout` | too many parallel connections | `scripts/pull.sh` already fixes this |
| `read: connection timed out` mid-download | genuinely slow link | retry; ethernet beats wifi |

`fix-docker-dns.sh` writes `/etc/docker/daemon.json` via a real JSON
parser (preserving any existing settings), validates it, and **restores
the previous state automatically if docker fails to come back**. Do not
hand-edit that file — a stray character stops the daemon and every
container with it.

It is safe to run twice: if the setting is already present it changes
nothing and **does not restart docker**. That matters because restarting
the daemon stops every container on the machine, including ones unrelated
to this project — a re-run of a fix script should not cost an unrelated
service an outage.

Prometheus is opt-in and not pulled by default, so a failure on
`prom/prometheus` never blocks the stack. Start it later with
`bash scripts/up.sh --profile monitoring up -d`.

### 2c. Docker won't start after editing `/etc/docker/daemon.json`

```
Job for docker.service failed because the control process exited with error code.
```

That file is **strict JSON** — no `#` comments, no trailing commas. One bad
character stops the daemon entirely, which takes down *every* container on
the machine, not just this project's.

The file is optional, so the fastest recovery is to delete it — **and to
clear systemd's lockout**, which is the step everyone misses:

```bash
sudo rm -f /etc/docker/daemon.json
sudo systemctl reset-failed docker.service
sudo systemctl start docker
```

`reset-failed` matters. After a few rapid failures systemd gives up:

```
docker.service: Start request repeated too quickly.
```

From then on it refuses to start the service *at all*, no matter what you
fix. Without `reset-failed` the repair looks like it did nothing, which
sends you hunting for a second, non-existent problem. Confirm the real
error first — systemd's own messages bury dockerd's:

```bash
sudo journalctl -u docker --no-pager -n 300 | grep -vE "^░░" | tail -30
```

The `grep -v` strips systemd's decorative `░░` explanation blocks, which
otherwise crowd out the one line that matters (dockerd's own `level=`
output).

To keep a setting, always validate before restarting:

```bash
sudo python3 -m json.tool /etc/docker/daemon.json
```

If that prints your config, it's valid. If it raises an error, the daemon
will refuse to start. Check with `sudo journalctl -xeu docker.service`.

Note the database image is `postgres:16-alpine`, not TimescaleDB. The
Phase 1 design named TimescaleDB, but nothing ever used it — there is not
one hypertable or `time_bucket` call in the code or migrations — so it was
a large download for no benefit. Set `POSTGRES_IMAGE` to switch back if
hypertables are ever adopted, but **not on an existing volume**: data
written by the timescaledb image will not start under plain Postgres.

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

### 4c. The dashboard shows a sign-in screen and you have no account

There is no sign-up form, on purpose (`docs/AUTH.md`). Create the first
admin from the CLI:

```bash
docker compose -f infrastructure/docker-compose.yml exec api \
  python -m app.cli create-admin you@example.com
```

If you set `AUTH_REQUIRED=true` before creating a user, this is exactly
the state you land in — locked out of your own dashboard. The CLI talks
to the database directly, so it still works.

To go back to the LAN posture, set `AUTH_REQUIRED=false` and restart the
api service. The dashboard follows automatically (it asks the API on
every load) and shows an amber "Unauthenticated mode" badge instead.

### 4d. Signing in fails with a CORS error rather than a 401

The browser sends a preflight for any request carrying an `Authorization`
header, and the API must list that header in its allowlist. It does — but
if you are running an older build of the api image, rebuild it:

```bash
docker compose -f infrastructure/docker-compose.yml up --build -d api
```

Also confirm `CORS_ALLOWED_ORIGINS` in `.env` names the exact origin you
browse from, port included.

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
