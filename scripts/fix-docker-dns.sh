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
#   - backs up any existing file first,
#   - merges via a real JSON parser, never string concatenation, so other
#     settings survive,
#   - validates the result before restarting anything,
#   - and if docker does not come back, RESTORES the previous state
#     automatically and tells you.
#
# The worst case is therefore "no change", never "docker is broken".

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
  cp -a "$CONF" "$BACKUP"
  echo "Backed up to $BACKUP"
  HAD_FILE=1
else
  echo "$CONF does not exist (this is normal)."
  HAD_FILE=0
fi

echo
echo "=== Writing DNS setting ==="
mkdir -p /etc/docker

# Merge with a real parser so any existing keys are preserved. A malformed
# existing file is a hard stop: silently replacing someone's config would
# be worse than refusing.
python3 - "$CONF" "$DNS_JSON" <<'PY'
import json, os, sys

path, dns_json = sys.argv[1], sys.argv[2]
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

config["dns"] = json.loads(dns_json)
with open(path, "w") as fh:
    json.dump(config, fh, indent=2)
    fh.write("\n")
print("Wrote:")
print(json.dumps(config, indent=2))
PY

if [ $? -ne 0 ]; then
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
