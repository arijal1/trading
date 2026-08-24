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

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
REDIS_PORT="${REDIS_PORT:-6379}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"

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

compose() { docker compose -f "$COMPOSE_FILE" "$@" 2>/dev/null; }

printf '%sTrading platform — connection doctor%s\n' "$B" "$N"
printf 'repo: %s\n' "$REPO_ROOT"

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
      case "$label" in
        Postgres) fix "Stop it, or run with a different port:  POSTGRES_PORT=5433 docker compose -f infrastructure/docker-compose.yml up -d" ;;
        Redis)    fix "Stop it, or:  REDIS_PORT=6380 docker compose -f infrastructure/docker-compose.yml up -d" ;;
        API)      fix "Stop it, or:  API_PORT=8001 docker compose -f infrastructure/docker-compose.yml up -d --build" ;;
        Web)      fix "Stop it, or:  WEB_PORT=3001 docker compose -f infrastructure/docker-compose.yml up -d" ;;
        *)        fix "Stop whatever owns port $port, then retry." ;;
      esac
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
  fix "docker compose -f infrastructure/docker-compose.yml up --build -d"
else
  for svc in postgres redis api web prometheus; do
    cid="$(compose ps -q "$svc")"
    if [ -z "$cid" ]; then
      fail "service '$svc' is not running"
      fix "docker compose -f infrastructure/docker-compose.yml up -d $svc"
      continue
    fi
    state="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)"
    restarts="$(docker inspect -f '{{.RestartCount}}' "$cid" 2>/dev/null)"
    if [ "$state" = "running" ] && [ "${restarts:-0}" -lt 3 ]; then
      ok "$svc: running"
    elif [ "$state" = "running" ]; then
      warn "$svc: running but has restarted ${restarts} times (crash loop?)"
      fix "docker compose -f infrastructure/docker-compose.yml logs --tail=50 $svc"
    else
      fail "$svc: $state"
      fix "docker compose -f infrastructure/docker-compose.yml logs --tail=50 $svc"
    fi
  done
fi

# ---------------------------------------------------------------------- reaching
head_ "5. Can we actually reach it?"

if ! command -v curl >/dev/null 2>&1; then
  warn "curl not installed — skipping reachability checks"
else
  if curl -fsS --max-time 5 "http://localhost:$API_PORT/api/v1/health" >/dev/null 2>&1; then
    ok "API healthy at http://localhost:$API_PORT"

    accounts="$(curl -fsS --max-time 5 "http://localhost:$API_PORT/api/v1/accounts" 2>/dev/null)"
    if [ "$accounts" = "[]" ]; then
      warn "API works but there are no accounts — the dashboard will look empty"
      fix "docker compose -f infrastructure/docker-compose.yml exec api python -m app.cli seed-demo"
    elif [ -n "$accounts" ]; then
      ok "seed data present (at least one account)"
    fi
  else
    fail "cannot reach the API at http://localhost:$API_PORT/api/v1/health"
    fix "docker compose -f infrastructure/docker-compose.yml logs --tail=50 api"
    fix "A DB connection error here usually means migrations failed to run."
  fi

  if curl -fsS --max-time 8 -o /dev/null "http://localhost:$WEB_PORT" 2>/dev/null; then
    ok "dashboard responding at http://localhost:$WEB_PORT"
  else
    fail "cannot reach the dashboard at http://localhost:$WEB_PORT"
    fix "docker compose -f infrastructure/docker-compose.yml logs --tail=50 web"
  fi
fi

# ----------------------------------------------------------------------- verdict
head_ "Verdict"
if [ "$FAILED" = "0" ]; then
  printf '  %sEverything checks out.%s Open http://localhost:%s\n\n' "$G" "$N" "$WEB_PORT"
  exit 0
fi
printf '  %sSomething is wrong — see the ✗ lines above.%s\n' "$R" "$N"
printf '  Full logs:  docker compose -f infrastructure/docker-compose.yml logs\n'
printf '  Start over: docker compose -f infrastructure/docker-compose.yml down -v && \\\n'
printf '              docker compose -f infrastructure/docker-compose.yml up --build -d\n\n'
exit 1
