#!/usr/bin/env bash
# Run the trading platform on your own machine.
#
#   bash scripts/local.sh start     # start it (first run builds; ~5-10 min)
#   bash scripts/local.sh stop      # stop it, keep the data
#   bash scripts/local.sh status    # is it healthy? what's the URL?
#   bash scripts/local.sh logs api  # follow a service's logs
#   bash scripts/local.sh reset     # wipe the database and start fresh
#
# Everything runs in Docker and stops when you say so. Nothing is
# installed outside Docker, nothing starts at boot, and closing your
# laptop just pauses it.
#
# This is the laptop counterpart to setup.sh + up.sh, which exist for
# always-on hosts where the LAN IP, port collisions and build-time API URL
# all matter. On a machine where you run the browser yourself, "localhost"
# is simply correct, so one command can do the whole job.

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

compose_args() {
  if [ -f .compose-args ]; then read -r a < .compose-args; echo "$a"
  else echo "-f infrastructure/docker-compose.yml"; fi
}
dc() { # shellcheck disable=SC2046,SC2086
  docker compose $(compose_args) "$@"; }

web_port() { sed -n 's/^WEB_PORT=//p' infrastructure/.env 2>/dev/null | tail -1; }
api_port() { sed -n 's/^API_PORT=//p' infrastructure/.env 2>/dev/null | tail -1; }

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker is not installed."
    case "$(uname -s)" in
      Darwin) inf "Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/" ;;
      Linux)  inf "Install Docker: https://docs.docker.com/engine/install/" ;;
      *)      inf "Install Docker Desktop: https://docs.docker.com/get-docker/" ;;
    esac
    exit 1
  fi
  if ! timeout 20 docker info >/dev/null 2>&1; then
    err "Docker is installed but not running."
    case "$(uname -s)" in
      Darwin) inf "Open the Docker Desktop app, wait for the whale icon to settle, then re-run." ;;
      Linux)  inf "sudo systemctl start docker" ;;
      *)      inf "Start Docker Desktop, then re-run." ;;
    esac
    exit 1
  fi
}

cmd_start() {
  require_docker
  ok "Docker is running"

  # setup.sh works out free ports and writes infrastructure/.env. On a
  # laptop it also correctly resolves the public host to "localhost",
  # because the machine serving the app is the one browsing it.
  if [ ! -f infrastructure/.env ]; then
    hdr "First-time setup"
    bash scripts/setup.sh >/dev/null 2>&1 || { err "setup failed"; bash scripts/setup.sh; exit 1; }
    ok "configuration written"
  fi
  [ -f .env ] || { cp .env.example .env; ok "created .env"; }

  WEB="$(web_port)"; WEB="${WEB:-3000}"
  API="$(api_port)"; API="${API:-8000}"

  hdr "Starting"
  inf "First run builds the images and takes about 5-10 minutes."
  inf "Later runs take a few seconds."
  if ! dc up --build -d; then
    err "compose failed to start — see the output above"
    exit 1
  fi

  hdr "Waiting for the API"
  # Two separate waits, because they fail for different reasons.
  #
  # /health is liveness only: it deliberately does not touch the database,
  # so that an outage in a dependency is not reported as a dead process
  # (see docs/AUTH.md). That makes it the right thing to wait on first —
  # and the wrong thing to declare "ready" on. Waiting on /health alone
  # printed "Ready" while Postgres was still refusing connections, handing
  # over a dashboard whose every panel then errored.
  for i in $(seq 1 90); do
    if curl -fsS --max-time 3 "http://localhost:$API/api/v1/health" >/dev/null 2>&1; then
      ok "API process is up"
      break
    fi
    [ "$i" = "90" ] && {
      err "the API did not come up within 90s"
      inf "Last 40 lines of its log:"
      dc logs --tail=40 api
      exit 1
    }
    sleep 1
  done

  # /system/status reports database_connected, which is what actually
  # decides whether the dashboard will work. Migrations also run on api
  # start, so this covers "Postgres is up but the schema is not yet".
  for i in $(seq 1 60); do
    if curl -fsS --max-time 3 "http://localhost:$API/api/v1/system/status" 2>/dev/null \
         | grep -q '"database_connected":true'; then
      ok "database is connected"
      break
    fi
    [ "$i" = "60" ] && {
      err "the API is running but cannot reach the database"
      inf "Usually the migrations failed. Last 40 lines:"
      dc logs --tail=40 api
      inf "If the schema is from an incompatible older version:  bash scripts/local.sh reset"
      exit 1
    }
    sleep 1
  done

  # Seed only an empty database, so restarting never overwrites the
  # trading history you have accumulated.
  accounts="$(curl -fsS --max-time 5 "http://localhost:$API/api/v1/accounts" 2>/dev/null)"
  case "$accounts" in
    "[]")
      hdr "Seeding demo data"
      if dc exec -T api python -m app.cli seed-demo >/dev/null 2>&1; then
        ok "demo account and markets created"
      else
        inf "could not seed automatically — run it yourself:"
        inf "bash scripts/local.sh logs api   # to see why"
      fi
      ;;
    "")
      # Neither a list nor empty: the request itself failed. Saying
      # nothing here is how "Ready" ends up printed over a broken stack.
      inf "could not read the account list — the dashboard may look empty"
      ;;
    *) ok "existing data kept" ;;
  esac

  hdr "Ready"
  printf '  Open:  %shttp://localhost:%s%s\n\n' "$B" "$WEB" "$N"
  printf '  Stop it:      bash scripts/local.sh stop\n'
  printf '  See logs:     bash scripts/local.sh logs api\n'
  printf '  Start fresh:  bash scripts/local.sh reset\n\n'
  printf '  Note: most ticks return HOLD. That is the strategy declining to\n'
  printf '  trade, not a failure — see docs/TROUBLESHOOTING.md.\n\n'
}

cmd_stop() {
  require_docker
  dc down && ok "stopped (your data is kept — 'start' brings it back)"
}

cmd_reset() {
  require_docker
  printf '%sThis deletes the database: all paper-trading history goes.%s\n' "$Y" "$N"
  printf 'Type "reset" to confirm: '
  read -r reply </dev/tty 2>/dev/null || reply=""
  [ "$reply" = "reset" ] || { inf "cancelled — nothing changed"; exit 0; }
  dc down -v && ok "database removed"
  cmd_start
}

cmd_status() { bash scripts/doctor.sh; }

cmd_logs() {
  require_docker
  shift 2>/dev/null
  if [ "$#" -eq 0 ]; then dc logs --tail=100 -f
  else dc logs --tail=100 -f "$@"; fi
}

case "${1:-start}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  reset)  cmd_reset ;;
  status) cmd_status ;;
  logs)   cmd_logs "$@" ;;
  *)
    printf 'Usage: bash scripts/local.sh [start|stop|status|logs [service]|reset]\n'
    exit 1 ;;
esac
