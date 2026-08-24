#!/usr/bin/env bash
# Thin wrapper around `docker compose` that supplies the right -f flags.
#
#   bash scripts/up.sh                        # build + start everything
#   bash scripts/up.sh logs -f api            # any compose subcommand
#   bash scripts/up.sh exec api python -m app.cli seed-demo
#   bash scripts/up.sh down
#
# Exists so nobody has to paste multi-line commands with backslash
# continuations, which break silently when a paste mangles them: bash runs
# the first fragment on its own (docker compose with no subcommand) and
# then treats the rest as separate commands.
#
# Run scripts/setup.sh first — it writes .compose-args and
# infrastructure/.env.

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [ -f .compose-args ]; then
  read -r COMPOSE_ARGS < .compose-args
else
  COMPOSE_ARGS="-f infrastructure/docker-compose.yml"
  # Fall back to detecting a Pi, so this still does the right thing if
  # setup.sh was never run.
  if [ -r /proc/device-tree/model ] &&
     tr -d '\0' < /proc/device-tree/model 2>/dev/null | grep -qi raspberry; then
    COMPOSE_ARGS="$COMPOSE_ARGS -f infrastructure/docker-compose.pi.yml"
  fi
fi

# No arguments: the common case, build and start detached.
if [ "$#" -eq 0 ]; then
  set -- up --build -d
fi

# shellcheck disable=SC2086 # COMPOSE_ARGS is intentionally word-split
exec docker compose $COMPOSE_ARGS "$@"
