#!/usr/bin/env bash
# Diagnose "I can't connect to the server".
#
# Pure bash + standard tools on purpose: this has to run when the app is
# completely broken, so it must not depend on Python, Poetry, npm, or a
# running container.
#
#   bash scripts/doctor.sh
#
# Exits 0 if everything checks out, 1 if any check failed.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/infrastructure/docker-compose.yml"

# Read what scripts/setup.sh actually chose for THIS machine.
#
# This previously defaulted to 8000/3000 and only ever looked at the base
# compose file. On any machine where setup.sh had to move a port — a Pi
# already running something on 3000 is the common case — the doctor then
# probed the wrong port and the wrong compose project: it would report
# "Web port 3000 is free" and "cannot reach the dashboard at
# localhost:3000" while the dashboard was up and healthy on 3001. That is
# worse than no diagnosis, because it sends you to fix a working service.
#
# An explicitly exported variable still wins, so `WEB_PORT=3005 bash
# scripts/doctor.sh` remains usable for a one-off check.
from_setup() {   # from_setup <KEY> -> value from infrastructure/.env, or empty
  [ -f "$REPO_ROOT/infrastructure/.env" ] || return 0
  sed -n "s/^$1=//p" "$REPO_ROOT/infrastructure/.env" | tail -1
}

SETUP_RAN=0
[ -f "$REPO_ROOT/infrastructure/.env" ] && SETUP_RAN=1

API_PORT="${API_PORT:-$(from_setup API_PORT)}";              API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-$(from_setup WEB_PORT)}";              WEB_PORT="${WEB_PORT:-3000}"
POSTGRES_PORT="${POSTGRES_PORT:-$(from_setup POSTGRES_PORT)}"; POSTGRES_PORT="${POSTGRES_PORT:-5432}"
REDIS_PORT="${REDIS_PORT:-$(from_setup REDIS_PORT)}";        REDIS_PORT="${REDIS_PORT:-6379}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-$(from_setup PROMETHEUS_PORT)}"; PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
PUBLIC_HOST="${PUBLIC_HOST:-$(from_setup PUBLIC_HOST)}";     PUBLIC_HOST="${PUBLIC_HOST:-localhost}"

# The Pi overlay changes which services and limits apply, so `compose ps`
# must be asked with the same -f arguments the stack was started with.
COMPOSE_ARGS="-f $COMPOSE_FILE"
if [ -f "$REPO_ROOT/.compose-args" ]; then
  read -r saved < "$REPO_ROOT/.compose-args"
  [ -n "${saved:-}" ] && COMPOSE_ARGS="$saved"
fi

FAILED=0
if [ -t 1 ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
else
  R=""; G=""; Y=""; B=""; N=""
fi

ok()    { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
warn()  { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
fail()  { printf '  %s✗%s %s\n' "$R" "$N" "$1"; FAILED=1; }
fix()   { printf '      %s→ %s%s\n' "$Y" "$1" "$N"; }
head_() { printf '\n%s%s%s\n' "$B" "$1" "$N"; }

# Checks every available probe rather than only the first one that exists.
# Raspberry Pi OS ships without lsof, and an earlier version treated "no
# tool available" as "port is free" — which reported every port free while
# containers were bound to them. Absence of evidence is now its own state.
port_in_use() {
  local port="$1"
  if docker info >/dev/null 2>&1 &&
     docker ps --format '{{.Ports}}' 2>/dev/null | grep -qE "(^|[^0-9])$port->"; then
    return 0
  fi
  command -v lsof >/dev/null 2>&1 &&
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  command -v ss >/dev/null 2>&1 &&
    ss -ltn 2>/dev/null | grep -qE "[:.]$port[[:space:]]" && return 0
  command -v netstat >/dev/null 2>&1 &&
    netstat -an 2>/dev/null | grep -qE "[:.]$port[[:space:]].*LISTEN" && return 0
  return 1
}

port_owner() {
  local port="$1" name
  if docker info >/dev/null 2>&1; then
    name="$(docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null \
            | grep -E "(^|[^0-9])$port->" | awk '{print $1}' | head -1)"
    [ -n "$name" ] && { echo "container '$name'"; return; }
  fi
  if command -v lsof >/dev/null 2>&1; then
    name="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1}')"
    [ -n "$name" ] && { echo "$name"; return; }
  fi
  echo "unknown"
}

# shellcheck disable=SC2086
compose() { (cd "$REPO_ROOT" && docker compose $COMPOSE_ARGS "$@" 2>/dev/null); }

printf '%sTrading platform — connection doctor%s\n' "$B" "$N"
printf 'repo: %s\n' "$REPO_ROOT"
if [ "$SETUP_RAN" = "1" ]; then
  printf 'using settings from infrastructure/.env (written by scripts/setup.sh)\n'
  printf 'ports: api=%s web=%s postgres=%s  public host: %s\n' \
    "$API_PORT" "$WEB_PORT" "$POSTGRES_PORT" "$PUBLIC_HOST"
else
  printf '%sinfrastructure/.env not found — assuming default ports.%s\n' "$Y" "$N"
  printf 'If you have not run it yet:  bash scripts/setup.sh\n'
fi

# ---------------------------------------------------------------- prerequisites
head_ "1. Prerequisites"

if command -v docker >/dev/null 2>&1; then
  ok "docker installed ($(docker --version | cut -d, -f1))"
else
  fail "docker is not installed"
  fix "Install Docker Desktop: https://docs.docker.com/get-docker/"
  printf '\n%sStopping: nothing else can work without Docker.%s\n' "$R" "$N"
  exit 1
fi

if timeout 20 docker info >/dev/null 2>&1; then
  ok "docker daemon is running"
else
  fail "docker is installed but the daemon is NOT running"
  fix "Start Docker Desktop (or: sudo systemctl start docker) and re-run."
  printf '\n%sThis is the most common cause of \"cannot connect\".%s\n' "$R" "$N"
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  ok "docker compose available ($(docker compose version --short 2>/dev/null))"
else
  fail "the 'docker compose' plugin is missing"
  fix "Update Docker Desktop, or install the compose-plugin package."
fi

# ------------------------------------------------------- small-board / ARM host
# Checked before anything else that could fail *because* of these, so the
# real cause is reported rather than a downstream symptom.
ARCH="$(uname -m 2>/dev/null || echo unknown)"
IS_PI=0
if [ -r /proc/device-tree/model ] && tr -d '\0' < /proc/device-tree/model 2>/dev/null | grep -qi raspberry; then
  IS_PI=1
fi

if [ "$IS_PI" = "1" ] || [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armv6l" ]; then
  head_ "1b. Small-board host"
  model="$( (tr -d '\0' < /proc/device-tree/model) 2>/dev/null || echo "ARM host")"
  ok "detected: $model ($ARCH)"

  case "$ARCH" in
    armv7l|armv6l)
      fail "this is a 32-bit OS — numpy/pandas have no prebuilt 32-bit ARM wheels"
      fix "Reflash with the 64-bit Raspberry Pi OS. On 32-bit they compile from source and usually fail."
      ;;
    aarch64)
      ok "64-bit OS — all required images and Python wheels have arm64 builds"
      ;;
  esac

  mem_kb="$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)"
  swap_kb="$(awk '/SwapTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)"
  mem_mb=$(( mem_kb / 1024 )); swap_mb=$(( swap_kb / 1024 ))
  total_mb=$(( mem_mb + swap_mb ))

  if [ "$mem_mb" -gt 0 ]; then
    ok "RAM: ${mem_mb}MB, swap: ${swap_mb}MB"
    if [ "$total_mb" -lt 3000 ]; then
      warn "under ~3GB RAM+swap — 'next build' is likely to be OOM-killed (exit code 137)"
      fix "Add swap:  sudo dphys-swapfile swapoff && sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile && sudo dphys-swapfile setup && sudo dphys-swapfile swapon"
      fix "Or skip building the dashboard on the Pi and run the API only (see docs/RASPBERRY_PI.md)."
    fi
  fi

  root_dev="$(findmnt -no SOURCE / 2>/dev/null || echo "")"
  case "$root_dev" in
    /dev/mmcblk*)
      warn "running from an SD card — Postgres/Prometheus writes will wear it out over months"
      fix "Use the Pi overlay to cut write volume:  -f infrastructure/docker-compose.pi.yml"
      fix "Better: boot from a USB3 SSD."
      ;;
    "") : ;;
    *) ok "root filesystem is on $root_dev (not an SD card)" ;;
  esac
fi

# ------------------------------------------------------------------------ files
head_ "2. Repository files"

[ -f "$COMPOSE_FILE" ] && ok "docker-compose.yml found" \
  || { fail "docker-compose.yml missing at $COMPOSE_FILE"; fix "Are you running this from inside the repo?"; }

if [ -f "$REPO_ROOT/.env" ]; then
  ok ".env exists"
else
  fail ".env is missing — compose will refuse to start the api service"
  fix "cp .env.example .env"
fi

[ -f "$REPO_ROOT/.dockerignore" ] && ok ".dockerignore present (keeps host node_modules out of the image)" \
  || warn ".dockerignore missing — image builds may copy host node_modules and fail"

if compose config >/dev/null 2>&1; then
  ok "compose file parses cleanly"
else
  fail "compose file is invalid or .env is unreadable"
  fix "docker compose -f infrastructure/docker-compose.yml config"
fi

# ------------------------------------------------------------------------ ports
head_ "3. Host port availability"

running_ids="$(compose ps -q 2>/dev/null | tr '\n' ' ')"
ours_up=0
[ -n "${running_ids// /}" ] && ours_up=1

check_port() {
  local port="$1" label="$2"
  if port_in_use "$port"; then
    if [ "$ours_up" = "1" ]; then
      ok "$label port $port in use (expected — this stack is running)"
    else
      local owner; owner="$(port_owner "$port")"
      fail "$label port $port is already in use by another process ($owner)"
      fix "Stop whatever owns it, or let setup pick a free port:  bash scripts/setup.sh"
    fi
  else
    ok "$label port $port is free"
  fi
}

check_port "$POSTGRES_PORT" "Postgres"
check_port "$REDIS_PORT"    "Redis"
check_port "$API_PORT"      "API"
check_port "$WEB_PORT"      "Web"
check_port "$PROMETHEUS_PORT" "Prometheus"

# ------------------------------------------------------------------- containers
head_ "4. Container state"

if [ "$ours_up" = "0" ]; then
  fail "no containers are running for this project"
  fix "bash scripts/up.sh"
  fix "First run on a Pi builds the images and takes 15-40 minutes."
else
  for svc in postgres redis api web; do
    cid="$(compose ps -q "$svc")"
    if [ -z "$cid" ]; then
      fail "service '$svc' is not running"
      fix "bash scripts/up.sh up -d $svc"
      continue
    fi
    state="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)"
    restarts="$(docker inspect -f '{{.RestartCount}}' "$cid" 2>/dev/null)"
    if [ "$state" = "running" ] && [ "${restarts:-0}" -lt 3 ]; then
      ok "$svc: running"
    elif [ "$state" = "running" ]; then
      warn "$svc: running but has restarted ${restarts} times (crash loop?)"
      fix "bash scripts/up.sh logs --tail=50 $svc"
    else
      fail "$svc: $state"
      fix "bash scripts/up.sh logs --tail=50 $svc"
    fi
  done

  # Prometheus is behind the "monitoring" compose profile, so it is
  # absent by default and that is correct, not a fault. Reporting it as a
  # failed service sent people chasing a container they never asked for.
  if [ -n "$(compose ps -q prometheus)" ]; then
    ok "prometheus: running (monitoring profile)"
  else
    ok "prometheus: not running (opt-in — bash scripts/up.sh --profile monitoring up -d)"
  fi
fi

# ---------------------------------------------------------------------- reaching
head_ "5. Can we actually reach it?"

if ! command -v curl >/dev/null 2>&1; then
  warn "curl not installed — skipping reachability checks"
else
  if curl -fsS --max-time 5 "http://localhost:$API_PORT/api/v1/health" >/dev/null 2>&1; then
    ok "API healthy at http://localhost:$API_PORT"

    # /accounts requires a token when AUTH_REQUIRED=true, so a 401 here
    # is a correct, healthy answer — not a fault. Ask the public config
    # endpoint what posture we are in before interpreting anything.
    auth_cfg="$(curl -fsS --max-time 5 "http://localhost:$API_PORT/api/v1/auth/config" 2>/dev/null)"
    case "$auth_cfg" in
      *'"auth_required":true'*)
        ok "authentication is ON — the dashboard will ask you to sign in"
        fix "No account yet?  bash scripts/up.sh exec api python -m app.cli create-admin you@example.com"
        ;;
      *)
        accounts="$(curl -fsS --max-time 5 "http://localhost:$API_PORT/api/v1/accounts" 2>/dev/null)"
        if [ "$accounts" = "[]" ]; then
          warn "API works but there are no accounts — the dashboard will look empty"
          fix "bash scripts/up.sh exec api python -m app.cli seed-demo"
        elif [ -n "$accounts" ]; then
          ok "seed data present (at least one account)"
        fi
        ;;
    esac
  else
    fail "cannot reach the API at http://localhost:$API_PORT/api/v1/health"
    fix "bash scripts/up.sh logs --tail=50 api"
    fix "A DB connection error here usually means migrations failed to run."
  fi

  if curl -fsS --max-time 8 -o /dev/null "http://localhost:$WEB_PORT" 2>/dev/null; then
    ok "dashboard responding at http://localhost:$WEB_PORT"
  else
    fail "cannot reach the dashboard at http://localhost:$WEB_PORT"
    fix "bash scripts/up.sh logs --tail=50 web"
    fix "If the web image is still building, this is expected — wait for it."
  fi
fi

# ------------------------------------------------------------- the right URL
# The single most common "it isn't working": browsing to localhost:PORT
# from a laptop while the stack runs on a Pi. "localhost" is always the
# machine running the *browser*, so it can never reach another host, and
# the failure looks identical to the server being down.
head_ "6. The URL to open"

if [ "$PUBLIC_HOST" = "localhost" ] || [ "$PUBLIC_HOST" = "127.0.0.1" ]; then
  printf '  On THIS machine:  %shttp://localhost:%s%s\n' "$B" "$WEB_PORT" "$N"
  warn "PUBLIC_HOST is 'localhost', so the dashboard only works in a browser on this machine"
  fix "Browsing from another computer or a phone? Re-run: bash scripts/setup.sh"
  fix "then rebuild:  bash scripts/up.sh up --build -d web"
else
  printf '  From any machine on your network:  %shttp://%s:%s%s\n' "$B" "$PUBLIC_HOST" "$WEB_PORT" "$N"
  printf '  On this machine only:              http://localhost:%s\n' "$WEB_PORT"
  warn "http://localhost:$WEB_PORT will NOT work from another computer — 'localhost' means whichever machine the browser is on"
fi

# The dashboard is a different origin from the API, so the API must allow
# the exact origin the browser will use. A mismatch is a silent "every
# panel stuck on Loading…" with nothing in the API log.
#
# Asked of the running API with a real CORS preflight rather than read out
# of .env: the file is only one of the inputs (there is a default in
# app/core/config.py, and the container may predate an edit), so a file
# check produces both false alarms and false all-clears. The preflight is
# the same question the browser will ask.
if command -v curl >/dev/null 2>&1 &&
   curl -fsS --max-time 5 "http://localhost:$API_PORT/api/v1/health" >/dev/null 2>&1; then
  want="http://${PUBLIC_HOST}:${WEB_PORT}"
  # -i so the response headers are readable; the body is irrelevant here.
  allowed="$(curl -sS -i --max-time 5 -X OPTIONS "http://localhost:$API_PORT/api/v1/accounts" \
      -H "Origin: $want" \
      -H "Access-Control-Request-Method: GET" \
      -H "Access-Control-Request-Headers: authorization,content-type" 2>/dev/null \
      | tr -d '\r' | sed -n 's/^[Aa]ccess-[Cc]ontrol-[Aa]llow-[Oo]rigin: //p')"

  if [ -n "$allowed" ]; then
    ok "the API accepts browser requests from $want"
  else
    fail "the API will reject browser requests from $want — panels will sit on 'Loading…'"
    fix "Add it to CORS_ALLOWED_ORIGINS in .env, or just:  bash scripts/setup.sh"
    fix "then restart the API:  bash scripts/up.sh up -d api"
  fi
fi

# ----------------------------------------------------------------------- verdict
head_ "Verdict"
if [ "$FAILED" = "0" ]; then
  printf '  %sEverything checks out.%s Open %shttp://%s:%s%s\n\n' \
    "$G" "$N" "$B" "$PUBLIC_HOST" "$WEB_PORT" "$N"
  exit 0
fi
printf '  %sSomething is wrong — see the ✗ lines above.%s\n' "$R" "$N"
printf '  Full logs:  bash scripts/up.sh logs\n'
printf '  Start over: bash scripts/up.sh down -v && bash scripts/up.sh up --build -d\n\n'
exit 1
