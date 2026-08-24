#!/usr/bin/env bash
# Point the Docker daemon at public DNS resolvers, safely.
#
#   sudo bash scripts/fix-docker-dns.sh
#
# Fixes image pulls that fail with either of these:
#
#   lookup registry-1.docker.io on 192.168.1.1:53: read udp ...: i/o timeout
#   dial tcp [2600:1f18:...]:443: connect: network is unreachable
#
# The first is the local router's DNS being too slow or flaky for the
# daemon; the second is a AAAA record being returned for a network that
# cannot actually route IPv6. Using public IPv4 resolvers addresses both.
#
# Why a script rather than "edit /etc/docker/daemon.json":
#
#   That file is strict JSON, it is easy to corrupt by hand, and a corrupt
#   file stops dockerd from starting *at all* — taking down every
#   container on the machine, not just this project's. Hand-editing it has
#   already caused exactly that once.
#
# So this script:
#   - refuses to touch a malformed existing file,
#   - merges via a real JSON parser, never string concatenation, so other
#     settings survive,
#   - does NOTHING AT ALL if the setting is already in place (see below),
#   - backs up, validates, and if docker does not come back, RESTORES the
#     previous state automatically and tells you.
#
# The worst case is therefore "no change", never "docker is broken".
#
# On the no-op path: restarting dockerd stops every container on the
# machine. Re-running this script after it has already succeeded must
# therefore cost nothing — an unrelated production container should not
# take an outage because someone ran a fix script twice.

set -uo pipefail

CONF=/etc/docker/daemon.json
BACKUP="${CONF}.bak.$(date +%s)"
DNS_JSON='["1.1.1.1", "8.8.8.8"]'

if [ "$(id -u)" -ne 0 ]; then
  echo "This needs root. Run:  sudo bash scripts/fix-docker-dns.sh" >&2
  exit 1
fi

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required (used to edit the JSON safely)." >&2
  exit 1
}

echo "=== Current state ==="
if [ -f "$CONF" ]; then
  echo "$CONF exists:"
  cat "$CONF"
  HAD_FILE=1
else
  echo "$CONF does not exist (this is normal)."
  HAD_FILE=0
fi

echo
echo "=== Applying DNS setting ==="
mkdir -p /etc/docker

# Exit codes from the helper below:
#   0 = file changed, caller must validate and restart
#   3 = already correct, caller must NOT restart
#   2 = existing file malformed, caller must not touch anything
python3 - "$CONF" "$DNS_JSON" "$BACKUP" <<'PY'
import json, os, shutil, sys

path, dns_json, backup = sys.argv[1], sys.argv[2], sys.argv[3]

config = {}
if os.path.exists(path):
    with open(path) as fh:
        text = fh.read().strip()
    if text:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"ERROR: existing {path} is not valid JSON: {exc}", file=sys.stderr)
            print("Refusing to overwrite it. Fix or delete it first:", file=sys.stderr)
            print(f"  sudo rm {path}", file=sys.stderr)
            sys.exit(2)

wanted = json.loads(dns_json)

# Already correct: change nothing, so the caller can skip the restart.
if config.get("dns") == wanted:
    print("Already set to:")
    print(json.dumps(config, indent=2))
    sys.exit(3)

# Only now is a backup worth making — one per real change, rather than one
# per invocation piling up in /etc/docker.
if os.path.exists(path):
    shutil.copy2(path, backup)
    print(f"Backed up to {backup}")

config["dns"] = wanted
with open(path, "w") as fh:
    json.dump(config, fh, indent=2)
    fh.write("\n")
print("Wrote:")
print(json.dumps(config, indent=2))
PY
rc=$?

if [ "$rc" = "3" ]; then
  echo
  echo "No change needed - NOT restarting docker."
  echo "(A restart stops every container on this machine, so re-running"
  echo " this script costs you nothing.)"
  if docker info >/dev/null 2>&1; then
    echo
    docker ps --format 'table {{.Names}}\t{{.Status}}'
    echo
    echo "Docker is running. Next:  bash scripts/pull.sh"
    exit 0
  fi
  echo
  echo "Docker is not running, though. Starting it..." >&2
  systemctl reset-failed docker.service 2>/dev/null
  systemctl start docker
  sleep 5
  if docker info >/dev/null 2>&1; then
    echo "Docker is running now. Next:  bash scripts/pull.sh"
    exit 0
  fi
  echo "Docker still will not start, and the DNS config is not the cause" >&2
  echo "(it was already correct and was not modified). Real error:" >&2
  echo "  sudo journalctl -u docker --no-pager -n 100 | grep -vE '^░░' | tail -20" >&2
  exit 1
fi

if [ "$rc" -ne 0 ]; then
  echo "Aborted without changing anything." >&2
  exit 1
fi

echo
echo "=== Validating before restarting ==="
if ! python3 -m json.tool "$CONF" >/dev/null 2>&1; then
  echo "Written file is not valid JSON. Reverting." >&2
  if [ "$HAD_FILE" = "1" ]; then mv -f "$BACKUP" "$CONF"; else rm -f "$CONF"; fi
  exit 1
fi
echo "Valid JSON."

echo
echo "=== Restarting docker ==="
# reset-failed clears systemd's "Start request repeated too quickly"
# lockout, which otherwise makes a correct fix look like it did nothing.
systemctl reset-failed docker.service 2>/dev/null
systemctl restart docker

echo "Waiting for the daemon..."
for _ in $(seq 1 15); do
  if docker info >/dev/null 2>&1; then
    echo
    echo "SUCCESS - docker is running with the new DNS settings."
    echo
    docker ps --format 'table {{.Names}}\t{{.Status}}'
    echo
    echo "Now retry the pull:   bash scripts/pull.sh"
    exit 0
  fi
  sleep 2
done

# Did not come back: undo everything rather than leaving it broken.
echo
echo "docker did NOT come back. Reverting to the previous state..." >&2
if [ "$HAD_FILE" = "1" ]; then
  mv -f "$BACKUP" "$CONF"
  echo "Restored your original $CONF" >&2
else
  rm -f "$CONF"
  echo "Removed $CONF (there was none before)" >&2
fi
systemctl reset-failed docker.service 2>/dev/null
systemctl restart docker
sleep 5

if docker info >/dev/null 2>&1; then
  echo "Docker is running again on the previous configuration." >&2
  echo "The DNS change was NOT applied. See the real error with:" >&2
else
  echo "Docker is still down. Investigate with:" >&2
fi
echo "  sudo journalctl -u docker --no-pager -n 100 | grep -vE '^░░' | tail -20" >&2
exit 1
