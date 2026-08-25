#!/usr/bin/env bash
# Run the trading platform on your own machine.
#
#   bash scripts/local.sh start     # start it (first run builds; ~5-10 min)
#   bash scripts/local.sh stop      # stop it, keep the data
#   bash scripts/local.sh status    # is it healthy? what's the URL?
#   bash scripts/local.sh logs api  # follow a service's logs
#   bash scripts/local.sh reset     # wipe the database and start fresh
#   bash scripts/local.sh admin you@example.com   # create a login
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

# On macOS the `docker` CLI can exist with no engine behind it at all —
# Homebrew installs the client on its own, and Docker Desktop, Colima,
# OrbStack and Rancher Desktop are four different things that could be
# providing (or failing to provide) the daemon. "Open Docker Desktop" is
# useless advice to someone who does not have Docker Desktop, so find out
# which one is actually installed before saying anything.
mac_engine() {
  [ -d "/Applications/Docker.app" ]  && { echo "desktop";  return; }
  [ -d "/Applications/OrbStack.app" ] && { echo "orbstack"; return; }
  [ -d "/Applications/Rancher Desktop.app" ] && { echo "rancher"; return; }
  command -v colima >/dev/null 2>&1 && { echo "colima"; return; }
  echo "none"
}

wait_for_daemon() {   # wait_for_daemon <seconds>
  local limit="$1" i
  for i in $(seq 1 "$limit"); do
    docker info >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

# Show WHY the daemon could not be reached.
#
# Every check above runs `docker info >/dev/null 2>&1`, which is right for
# a yes/no test and wrong for a failure report: the one line that explains
# the problem gets discarded, leaving "Docker is not running" for a
# machine where Docker Desktop is visibly running. The usual causes all
# announce themselves clearly in that output — a docker context pointing
# at a VM that no longer exists, a stale DOCKER_HOST exported by an old
# shell profile, or Docker Desktop's "Allow the default Docker socket to
# be used" being off so /var/run/docker.sock never appears.
docker_diagnosis() {
  hdr "What docker actually said"
  docker info 2>&1 | grep -vE '^\s*$' | head -12 | sed 's/^/      /'

  hdr "Where it is looking"
  if [ -n "${DOCKER_HOST:-}" ]; then
    printf '      DOCKER_HOST=%s\n' "$DOCKER_HOST"
    inf "DOCKER_HOST is set. If you did not set it deliberately, it is"
    inf "probably a leftover in ~/.zshrc from an old Docker setup and is"
    inf "pointing the CLI somewhere that no longer exists:"
    inf "    unset DOCKER_HOST && bash scripts/local.sh start"
  else
    printf '      DOCKER_HOST is not set (normal)\n'
  fi

  if docker context ls >/dev/null 2>&1; then
    printf '\n'
    docker context ls 2>/dev/null | sed 's/^/      /'
    inf "The context with a * is the one in use. On macOS with Docker"
    inf "Desktop it should be 'desktop-linux'. To switch back:"
    inf "    docker context use desktop-linux"
  fi

  if [ "$(uname -s)" = "Darwin" ]; then
    # Only meaningful when the active context is 'default', which is the
    # context that actually uses /var/run/docker.sock. Docker Desktop's
    # own context points at ~/.docker/run/docker.sock, so reporting the
    # default socket as "missing" there names a file nothing was looking
    # for and sends people to a setting that is not their problem.
    active="$(docker context ls 2>/dev/null | awk '/\*/ {print $1}' | head -1)"
    if [ "${active%\*}" = "default" ] && [ ! -S /var/run/docker.sock ]; then
      printf '      /var/run/docker.sock is missing, and the active context needs it\n'
      inf "Docker Desktop → Settings → Advanced → tick"
      inf "'Allow the default Docker socket to be used', then Apply & Restart."
    fi
    inf ""
    inf "Most common cause when Docker Desktop looks like it is running:"
    inf "it is sitting on a licence acceptance or sign-in screen and has"
    inf "never finished starting. Bring its window up and answer whatever"
    inf "it is waiting on, then re-run."
  fi
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker is not installed."
    case "$(uname -s)" in
      Darwin) inf "Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/"
              inf "(Apple Silicon and Intel both work.)" ;;
      Linux)  inf "Install Docker: https://docs.docker.com/engine/install/" ;;
      *)      inf "Install Docker: https://docs.docker.com/get-docker/" ;;
    esac
    exit 1
  fi

  # Already running: the overwhelmingly common case, so say so and get on
  # with it rather than probing for engines nobody needs.
  if docker info >/dev/null 2>&1; then
    ok "Docker is running"
    return 0
  fi

  local engine app
  case "$(uname -s)" in
    Darwin)
      engine="$(mac_engine)"
      case "$engine" in
        none)
          err "The docker command exists, but no Docker engine is installed."
          inf "This happens when only the CLI was installed (e.g. 'brew install docker')."
          inf "The CLI is just a client — it needs an engine to talk to."
          inf ""
          inf "Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/"
          inf "Or a lighter alternative:  brew install colima && colima start"
          exit 1
          ;;
        colima)
          inf "Colima is installed but not running. Starting it..."
          colima start || { err "colima failed to start"; exit 1; }
          ;;
        desktop|orbstack|rancher)
          case "$engine" in
            desktop)  app="Docker" ;;
            orbstack) app="OrbStack" ;;
            rancher)  app="Rancher Desktop" ;;
          esac
          inf "$app is installed but not running. Starting it..."
          open -a "$app" 2>/dev/null || {
            err "could not launch $app — open it from Applications, then re-run."
            exit 1
          }
          inf "Waiting for it to finish starting (this takes 30-60s the first time)..."
          ;;
      esac
      if wait_for_daemon 60; then
        ok "Docker is running"
        return 0
      fi
      err "Docker did not come up within 2 minutes."
      docker_diagnosis
      exit 1
      ;;
    Linux)
      err "Docker is installed but the daemon is not running."
      inf "sudo systemctl start docker"
      docker_diagnosis
      exit 1
      ;;
    *)
      err "Docker is installed but the daemon is not running."
      inf "Start Docker Desktop, then re-run."
      docker_diagnosis
      exit 1
      ;;
  esac
}

cmd_start() {
  require_docker

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

cmd_admin() {
  require_docker
  shift 2>/dev/null
  email="${1:-}"
  if [ -z "$email" ]; then
    err "Which email? Usage:"
    inf "bash scripts/local.sh admin you@example.com"
    exit 1
  fi

  hdr "Creating an admin user"
  inf "You will be prompted for a password. It is read invisibly — nothing"
  inf "you type appears on screen, and it never enters your shell history."
  inf "Minimum 12 characters."
  printf '\n'

  # A TTY is required: the CLI reads the password with getpass, which needs
  # a terminal to turn echo off. Without one it either fails or, worse,
  # echoes the password in clear text.
  if [ ! -t 0 ]; then
    err "This needs an interactive terminal — run it directly, not piped."
    exit 1
  fi
  dc exec api python -m app.cli create-admin "$email"
}

cmd_logs() {
  require_docker
  shift 2>/dev/null
  if [ "$#" -eq 0 ]; then dc logs --tail=100 -f
  else dc logs --tail=100 -f "$@"; fi
}

case "${1:-start}" in
  start)  cmd_start ;;
  admin)  cmd_admin "$@" ;;
  stop)   cmd_stop ;;
  reset)  cmd_reset ;;
  status) cmd_status ;;
  logs)   cmd_logs "$@" ;;
  *)
    printf 'Usage: bash scripts/local.sh [start|stop|status|logs [service]|reset]\n'
    printf '       bash scripts/local.sh admin you@example.com   # create a login\n'
    exit 1 ;;
esac
