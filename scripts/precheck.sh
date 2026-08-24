#!/usr/bin/env bash
# "What's already on this machine?" — read-only inventory.
#
# Unlike scripts/doctor.sh this needs no repo, no .env, and nothing
# running: it is meant to be pasted into a fresh terminal *before* you
# clone anything, to see what is already installed and what might collide.
#
# Changes nothing. Safe to run anywhere, any number of times.
#
#   bash scripts/precheck.sh
# or, without the repo:
#   curl -fsSL https://raw.githubusercontent.com/arijal1/trading/claude/ai-crypto-trading-platform-yhb4nj/scripts/precheck.sh | bash

# Deliberately no `set -e`: a missing tool is information, not a reason to
# abort the report.

if [ -t 1 ]; then
  G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; N=$'\033[0m'
else
  G=""; Y=""; R=""; B=""; N=""
fi
yes_() { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
no_()  { printf '  %s✗%s %s\n' "$R" "$N" "$1"; }
inf_() { printf '  %s·%s %s\n' "$Y" "$N" "$1"; }
hdr()  { printf '\n%s%s%s\n' "$B" "$1" "$N"; }

printf '%s=== Machine inventory ===%s\n' "$B" "$N"

# ------------------------------------------------------------------ machine
hdr "Machine"
OS="$(uname -s 2>/dev/null)"
ARCH="$(uname -m 2>/dev/null)"
inf_ "OS:           $OS"
inf_ "Architecture: $ARCH"

case "$OS" in
  Darwin) inf_ "macOS:        $(sw_vers -productVersion 2>/dev/null)" ;;
  Linux)
    if [ -r /etc/os-release ]; then
      inf_ "Distro:       $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
    fi
    if [ -r /proc/device-tree/model ]; then
      inf_ "Board:        $(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
    fi
    ;;
esac

# 32-bit ARM is the one hard blocker worth calling out immediately.
case "$ARCH" in
  armv6l|armv7l)
    no_ "32-bit ARM — numpy/pandas have no prebuilt wheels for this."
    inf_ "   Reflash with the 64-bit Raspberry Pi OS (you want 'aarch64')."
    ;;
  aarch64|arm64) yes_ "64-bit ARM — supported" ;;
  x86_64|amd64)  yes_ "64-bit x86 — supported" ;;
esac

# ------------------------------------------------------------------- memory
hdr "Memory & disk"
if [ -r /proc/meminfo ]; then
  mem_mb=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 ))
  swap_mb=$(( $(awk '/SwapTotal/{print $2}' /proc/meminfo) / 1024 ))
  inf_ "RAM:  ${mem_mb}MB   Swap: ${swap_mb}MB"
  if [ $(( mem_mb + swap_mb )) -lt 3000 ]; then
    no_ "Under ~3GB RAM+swap — the dashboard build will likely be OOM-killed."
    inf_ "   Fix: add swap (see docs/RASPBERRY_PI.md), or run the API only."
  else
    yes_ "Enough memory to build"
  fi
elif [ "$OS" = "Darwin" ]; then
  inf_ "RAM:  $(( $(sysctl -n hw.memsize 2>/dev/null) / 1024 / 1024 ))MB"
fi

avail="$(df -h . 2>/dev/null | awk 'NR==2{print $4}')"
[ -n "$avail" ] && inf_ "Free disk here: $avail (needs ~5GB for images)"

# ------------------------------------------------------------------- docker
hdr "Docker"
if command -v docker >/dev/null 2>&1; then
  yes_ "docker installed: $(docker --version 2>/dev/null)"

  if timeout 20 docker info >/dev/null 2>&1; then
    yes_ "docker daemon is RUNNING"
    inf_ "Containers running: $(docker ps -q 2>/dev/null | wc -l | tr -d ' ')"
    inf_ "Images stored:      $(docker images -q 2>/dev/null | wc -l | tr -d ' ')"
  else
    no_ "docker is installed but the daemon is NOT running"
    case "$OS" in
      Darwin) inf_ "   Open Docker Desktop from Applications." ;;
      *)      inf_ "   sudo systemctl start docker" ;;
    esac
    inf_ "   (If you just installed it, you may need to log out and back in.)"
  fi

  if docker compose version >/dev/null 2>&1; then
    yes_ "docker compose plugin: $(docker compose version --short 2>/dev/null)"
  elif command -v docker-compose >/dev/null 2>&1; then
    no_ "only the OLD standalone 'docker-compose' is present"
    inf_ "   This project needs the v2 plugin ('docker compose', no hyphen)."
    inf_ "   Update Docker Desktop, or install the docker-compose-plugin package."
  else
    no_ "docker compose plugin missing"
  fi
else
  no_ "docker is NOT installed"
  case "$OS" in
    Darwin) inf_ "   Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/" ;;
    Linux)  inf_ "   curl -fsSL https://get.docker.com | sh" ;;
    *)      inf_ "   https://docs.docker.com/get-docker/" ;;
  esac
fi

# ------------------------------------------------------------- other tools
hdr "Other tools"
for tool in git curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    yes_ "$tool: $("$tool" --version 2>/dev/null | head -1 | cut -c1-60)"
  else
    no_ "$tool is NOT installed (required)"
  fi
done
for tool in psql node npm python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    inf_ "$tool present: $("$tool" --version 2>&1 | head -1 | cut -c1-40)  (not required)"
  fi
done

# ------------------------------------------------------------------- ports
hdr "Ports this project wants"
port_busy() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -qE "[:.]$1[[:space:]]"
  elif command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | grep -qE "[:.]$1[[:space:]].*LISTEN"
  else
    return 1
  fi
}
owner_of() {
  command -v lsof >/dev/null 2>&1 || { echo "unknown"; return; }
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1}'
}
CONFLICT=0
for entry in "5432:Postgres:POSTGRES_PORT" "6379:Redis:REDIS_PORT" \
             "8000:API:API_PORT" "3000:Dashboard:WEB_PORT" \
             "9090:Prometheus:PROMETHEUS_PORT"; do
  port="${entry%%:*}"; rest="${entry#*:}"; label="${rest%%:*}"; var="${rest##*:}"
  if port_busy "$port"; then
    no_ "$port ($label) is ALREADY IN USE by: $(owner_of "$port")"
    inf_ "   Use another:  ${var}=$((port+1)) docker compose -f infrastructure/docker-compose.yml up -d"
    CONFLICT=1
  else
    yes_ "$port ($label) is free"
  fi
done

# ----------------------------------------------------------------- verdict
hdr "Summary"
if ! command -v docker >/dev/null 2>&1; then
  printf '  %sInstall Docker first%s — nothing else can run without it.\n\n' "$R" "$N"
elif ! timeout 20 docker info >/dev/null 2>&1; then
  printf '  %sDocker is installed but not running%s — start it, then re-run this.\n\n' "$R" "$N"
elif [ "$CONFLICT" = "1" ]; then
  printf '  %sReady, but some ports are taken%s — use the overrides shown above.\n\n' "$Y" "$N"
else
  printf '  %sThis machine looks ready.%s\n\n' "$G" "$N"
fi
