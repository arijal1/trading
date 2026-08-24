#!/usr/bin/env bash
# One-time setup: work out this machine's correct settings and write them
# down, so every later command is short and paste-safe.
#
#   bash scripts/setup.sh
#
# Why this exists: the settings that vary per machine (LAN IP, which ports
# are free, whether this is a Pi) were previously passed as long
# `VAR=x VAR=y docker compose -f a -f b ...` command lines. Those are easy
# to mis-paste — a broken line-continuation silently runs half a command —
# and easy to forget on the *next* invocation, which then builds with the
# wrong settings. Writing them to infrastructure/.env fixes both: Compose
# reads that file automatically for ${VAR} substitution, because it sits
# beside the compose file.
#
# Safe to re-run. Asks before overwriting anything.

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [ -t 1 ]; then
  G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; N=$'\033[0m'
else
  G=""; Y=""; R=""; B=""; N=""
fi
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
inf()  { printf '  %s·%s %s\n' "$Y" "$N" "$1"; }
err()  { printf '  %s✗%s %s\n' "$R" "$N" "$1"; }
hdr()  { printf '\n%s%s%s\n' "$B" "$1" "$N"; }

printf '%s=== Setup ===%s\n' "$B" "$N"

# ---------------------------------------------------------------- port probe
# Checks every available method rather than the first one present: a Pi
# has no lsof, and treating "no tool" as "port free" would hand out a port
# that is already bound.
port_busy() {
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

first_free() {          # first_free <preferred> -> echoes a free port
  local p="$1" tries=0
  while port_busy "$p" && [ "$tries" -lt 40 ]; do
    p=$((p + 1)); tries=$((tries + 1))
  done
  echo "$p"
}

# Is the Docker daemon reachable?
#
# The timeout matters: a half-started Docker Desktop can leave `docker
# info` hanging instead of failing. But `timeout` is GNU coreutils and is
# NOT present on macOS — there, `timeout 20 docker info` dies with
# "command not found" and returns 127, which reads as "the daemon is
# down" on a machine where Docker is running perfectly. That produced the
# worst possible symptom: local.sh (which called docker directly) said
# "Docker is running" and setup.sh said the opposite, one line apart.
#
# So: use timeout where it exists, gtimeout if coreutils came from
# Homebrew, and otherwise just ask docker directly. Losing the timeout is
# a far smaller problem than never working on macOS at all.
docker_daemon_ok() {
  if command -v timeout >/dev/null 2>&1; then
    timeout 20 docker info >/dev/null 2>&1
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout 20 docker info >/dev/null 2>&1
  else
    docker info >/dev/null 2>&1
  fi
}

# ---------------------------------------------------------------- prereqs
hdr "Checking Docker"
if ! command -v docker >/dev/null 2>&1; then
  err "docker is not installed — install it first, then re-run this."
  exit 1
fi
if ! docker_daemon_ok; then
  err "the docker daemon is not running — start it, then re-run this."
  exit 1
fi
ok "docker is installed and running"

# ---------------------------------------------------------------- host
hdr "This machine"
ARCH="$(uname -m)"
IS_PI=0
if [ -r /proc/device-tree/model ] &&
   tr -d '\0' < /proc/device-tree/model 2>/dev/null | grep -qi raspberry; then
  IS_PI=1
  ok "Raspberry Pi detected — will use the Pi overlay"
fi
case "$ARCH" in
  armv6l|armv7l)
    err "32-bit ARM: numpy/pandas have no wheels for this. Reflash with the 64-bit OS."
    exit 1
    ;;
esac
ok "architecture: $ARCH"

# LAN IP, needed because the dashboard's API URL is baked in at build time
# and "localhost" would mean the browsing machine, not this one.
LAN_IP=""
if command -v hostname >/dev/null 2>&1; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi
[ -z "$LAN_IP" ] && command -v ip >/dev/null 2>&1 &&
  LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')"

if [ -n "$LAN_IP" ]; then
  ok "LAN IP: $LAN_IP"
else
  LAN_IP="localhost"
  inf "could not detect a LAN IP — falling back to localhost"
  inf "(fine if you browse from this machine; otherwise edit infrastructure/.env)"
fi

# Allow an explicit override, e.g. a Tailscale name.
if [ -n "${PUBLIC_HOST:-}" ]; then
  LAN_IP="$PUBLIC_HOST"
  ok "using PUBLIC_HOST from your environment: $LAN_IP"
fi

# ---------------------------------------------------------------- ports
hdr "Choosing ports"
API_PORT="$(first_free 8000)"
WEB_PORT="$(first_free 3000)"
PG_PORT="$(first_free 5432)"
REDIS_PORT="$(first_free 6379)"
PROM_PORT="$(first_free 9090)"

report_port() {   # label wanted chosen
  if [ "$2" = "$3" ]; then ok "$1: $3"
  else inf "$1: $2 was taken → using $3"; fi
}
report_port "API       " 8000 "$API_PORT"
report_port "Dashboard " 3000 "$WEB_PORT"
report_port "Postgres  " 5432 "$PG_PORT"
report_port "Redis     " 6379 "$REDIS_PORT"
report_port "Prometheus" 9090 "$PROM_PORT"

# ---------------------------------------------------------------- write cfg
hdr "Writing configuration"

confirm_overwrite() {   # returns 0 to proceed
  [ -f "$1" ] || return 0
  printf '  %s%s already exists. Overwrite? [y/N] %s' "$Y" "$1" "$N"
  read -r reply </dev/tty 2>/dev/null || reply="n"
  case "$reply" in [yY]*) return 0 ;; *) return 1 ;; esac
}

# infrastructure/.env — Compose reads this automatically for ${VAR}
# substitution because it lives beside the compose file. The repo-root
# .env is a different thing (it is passed *into* the api container).
if confirm_overwrite "infrastructure/.env"; then
  cat > infrastructure/.env <<EOF
# Written by scripts/setup.sh — machine-specific settings.
# Compose reads this automatically because it sits beside the compose file.
PUBLIC_HOST=$LAN_IP
API_PORT=$API_PORT
WEB_PORT=$WEB_PORT
POSTGRES_PORT=$PG_PORT
REDIS_PORT=$REDIS_PORT
PROMETHEUS_PORT=$PROM_PORT
EOF
  ok "wrote infrastructure/.env"
else
  inf "kept your existing infrastructure/.env"
fi

# Repo-root .env — application config, passed into the api container.
if [ ! -f .env ]; then
  cp .env.example .env
  ok "created .env from .env.example"
else
  inf ".env already exists — leaving it, only updating CORS"
fi

# The dashboard is a different origin from the API, so the API has to
# allow the exact origin the browser will use.
ORIGIN="http://${LAN_IP}:${WEB_PORT}"
ORIGINS="$ORIGIN,http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT}"
if grep -q '^CORS_ALLOWED_ORIGINS=' .env 2>/dev/null; then
  tmp="$(mktemp)"
  sed "s|^CORS_ALLOWED_ORIGINS=.*|CORS_ALLOWED_ORIGINS=$ORIGINS|" .env > "$tmp" && mv "$tmp" .env
else
  printf '\nCORS_ALLOWED_ORIGINS=%s\n' "$ORIGINS" >> .env
fi
ok "CORS origins set to: $ORIGINS"

# ---------------------------------------------------------------- overlay
COMPOSE_ARGS="-f infrastructure/docker-compose.yml"
if [ "$IS_PI" = "1" ]; then
  COMPOSE_ARGS="$COMPOSE_ARGS -f infrastructure/docker-compose.pi.yml"
fi
printf '%s\n' "$COMPOSE_ARGS" > .compose-args
ok "compose files: $COMPOSE_ARGS"

# ---------------------------------------------------------------- done
hdr "Next"
cat <<EOF
  Start everything (one line, safe to paste):

      bash scripts/up.sh

  Then seed the demo data:

      bash scripts/up.sh exec api python -m app.cli seed-demo

  Then open:  ${B}http://${LAN_IP}:${WEB_PORT}${N}

  The first build takes 15-40 minutes on a Raspberry Pi. It has not hung.
EOF
