#!/usr/bin/env bash
# Remove everything this project put on the machine — and nothing else.
#
#   bash scripts/uninstall-pi.sh          # show what WOULD be removed
#   bash scripts/uninstall-pi.sh --yes    # actually remove it
#
# Why a script instead of "docker system prune -a":
#
#   prune is machine-wide. On a host that also runs unrelated production
#   containers it deletes their images and any volume that happens not to
#   be attached at that moment. It is the single fastest way to destroy
#   something you did not mean to touch.
#
# This script instead selects by Compose project label
# (com.docker.compose.project=trading-platform), which is stamped on the
# containers, volumes and networks this project created and on nothing
# else. Anything without that label is invisible to it.
#
# Two further safety rules, applied even within this project's own set:
#
#   - Shared base images (postgres, redis, ...) are never removed. They
#     are almost certainly used by something else on this machine, and
#     they cost nothing to keep beyond disk. Only images BUILT for this
#     project are removed.
#   - Dry-run is the default. Nothing is deleted without --yes.

set -uo pipefail

PROJECT="trading-platform"
LABEL="com.docker.compose.project=$PROJECT"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APPLY=0
[ "${1:-}" = "--yes" ] && APPLY=1

if [ -t 1 ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
else
  R=""; G=""; Y=""; B=""; N=""
fi
hdr()  { printf '\n%s%s%s\n' "$B" "$1" "$N"; }
item() { printf '  %s·%s %s\n' "$Y" "$N" "$1"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  warn "docker is not available — will only handle the files on disk."
  DOCKER_OK=0
else
  DOCKER_OK=1
fi

printf '%s=== Removing the trading platform from this machine ===%s\n' "$B" "$N"
[ "$APPLY" = "0" ] && printf '%sDRY RUN — nothing will be deleted. Re-run with --yes to apply.%s\n' "$Y" "$N"

# ------------------------------------------------------------------ survey
CONTAINERS=""; VOLUMES=""; NETWORKS=""; IMAGES=""
if [ "$DOCKER_OK" = "1" ]; then
  CONTAINERS="$(docker ps -aq --filter "label=$LABEL" 2>/dev/null)"
  VOLUMES="$(docker volume ls -q --filter "label=$LABEL" 2>/dev/null)"
  NETWORKS="$(docker network ls -q --filter "label=$LABEL" 2>/dev/null)"
  # Only images built for this project. Base images stay, always.
  IMAGES="$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
            | grep -E "^${PROJECT}[-_]" || true)"
fi

hdr "Will be REMOVED"
if [ -n "$CONTAINERS" ]; then
  while read -r cid; do
    [ -z "$cid" ] && continue
    item "container  $(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's|^/||')"
  done <<< "$CONTAINERS"
else
  item "(no containers from this project)"
fi
if [ -n "$VOLUMES" ]; then
  while read -r v; do [ -n "$v" ] && item "volume     $v  ${R}(destroys all paper-trading history)${N}"; done <<< "$VOLUMES"
fi
if [ -n "$NETWORKS" ]; then
  while read -r n; do [ -n "$n" ] && item "network    $(docker network inspect -f '{{.Name}}' "$n" 2>/dev/null)"; done <<< "$NETWORKS"
fi
if [ -n "$IMAGES" ]; then
  while read -r i; do [ -n "$i" ] && item "image      $i"; done <<< "$IMAGES"
fi
item "directory  $REPO_ROOT"

# ------------------------------------------------- what is explicitly spared
hdr "Will NOT be touched"
if [ "$DOCKER_OK" = "1" ]; then
  others="$(docker ps -a --format '{{.Names}}\t{{.Image}}' 2>/dev/null \
            | grep -vE "^${PROJECT}[-_]" || true)"
  if [ -n "$others" ]; then
    while IFS=$'\t' read -r name image; do
      [ -n "$name" ] && ok "container  $name  ($image)"
    done <<< "$others"
  else
    ok "(no other containers on this machine)"
  fi
  ok "shared base images (postgres, redis, ...) — kept, other things use them"
  ok "every volume and network not belonging to '$PROJECT'"
fi
ok "/etc/docker/daemon.json — the DNS setting is left in place (see note below)"

# ------------------------------------------------------------------- apply
if [ "$APPLY" = "0" ]; then
  hdr "Nothing was changed"
  printf '  Run it for real with:\n\n      bash scripts/uninstall-pi.sh --yes\n\n'
  printf '  Read the two lists above first — the volume line destroys data.\n\n'
  exit 0
fi

hdr "Removing"
if [ "$DOCKER_OK" = "1" ]; then
  if [ -n "$CONTAINERS" ]; then
    # shellcheck disable=SC2086
    docker rm -f $CONTAINERS >/dev/null 2>&1 && ok "containers removed"
  fi
  if [ -n "$VOLUMES" ]; then
    # shellcheck disable=SC2086
    docker volume rm $VOLUMES >/dev/null 2>&1 && ok "volumes removed"
  fi
  if [ -n "$NETWORKS" ]; then
    # shellcheck disable=SC2086
    docker network rm $NETWORKS >/dev/null 2>&1 && ok "networks removed"
  fi
  if [ -n "$IMAGES" ]; then
    while read -r i; do
      [ -z "$i" ] && continue
      docker rmi "$i" >/dev/null 2>&1 && ok "image removed: $i" \
        || warn "could not remove image $i (something may still reference it)"
    done <<< "$IMAGES"
  fi
fi

# The directory goes last: until now every step could be re-run from it.
# Deleted from the parent, because deleting the directory you are standing
# in leaves the shell in a path that no longer exists.
cd / || exit 1
if rm -rf "$REPO_ROOT"; then
  ok "removed $REPO_ROOT"
else
  warn "could not remove $REPO_ROOT — remove it by hand"
fi

hdr "Done"
cat <<EOF
  The trading platform is gone. Your other containers were not touched —
  confirm with:

      docker ps

  One thing deliberately left behind: /etc/docker/daemon.json still
  contains the public DNS resolvers (1.1.1.1, 8.8.8.8) that were added to
  get image pulls working. It is not specific to this project, it very
  likely helps your other containers too, and removing it means another
  docker restart — which stops every container on this machine for a few
  seconds. Leave it unless you have a reason not to.

  To remove it anyway:

      sudo rm -f /etc/docker/daemon.json
      sudo systemctl reset-failed docker.service
      sudo systemctl restart docker
EOF
