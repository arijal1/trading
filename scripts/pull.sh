#!/usr/bin/env bash
# Pull images one at a time, retrying on network failure.
#
#   bash scripts/pull.sh
#
# `docker compose up` pulls everything in parallel, which on a slow or
# flaky link (a Pi on wifi is the usual case) opens several TLS sessions
# at once and reliably produces:
#
#     net/http: TLS handshake timeout
#
# That is a transport failure, not a missing image — the pull simply ran
# out of patience. Serialising the pulls and retrying fixes it in most
# cases, and Docker keeps completed layers, so each attempt resumes rather
# than starting over.
#
# Run this before `scripts/up.sh` if the pull keeps failing.

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [ -f .compose-args ]; then
  read -r COMPOSE_ARGS < .compose-args
else
  COMPOSE_ARGS="-f infrastructure/docker-compose.yml"
fi

ATTEMPTS="${ATTEMPTS:-5}"

for attempt in $(seq 1 "$ATTEMPTS"); do
  echo "--- pull attempt $attempt of $ATTEMPTS ---"
  # --parallel 1 is the point: one connection at a time.
  # shellcheck disable=SC2086
  if docker compose $COMPOSE_ARGS --parallel 1 pull --ignore-buildable; then
    echo
    echo "All images pulled. Now run:  bash scripts/up.sh"
    exit 0
  fi
  if [ "$attempt" -lt "$ATTEMPTS" ]; then
    wait_s=$((attempt * 10))
    echo "Pull failed. Waiting ${wait_s}s before retrying (layers already"
    echo "downloaded are kept, so this resumes rather than restarting)..."
    sleep "$wait_s"
  fi
done

cat <<'EOF'

Still failing after several attempts. This is a network problem between
your machine and Docker Hub, not a problem with this project. Things that
actually help, in order:

  1. If you are on wifi, try ethernet. This is the most common fix on a Pi.

  2. Force IPv4 DNS. Docker on a Pi often hangs trying Docker Hub over
     IPv6 when the network does not really route it.

     /etc/docker/daemon.json is strict JSON: no comments, no trailing
     commas. A malformed file stops the docker daemon from starting at
     all, taking every container with it. So do NOT hand-edit it.

     If the file does NOT already exist, create it in one command:

        test -f /etc/docker/daemon.json && echo "EXISTS - merge by hand instead" || \
          echo '{"dns":["1.1.1.1","8.8.8.8"]}' | sudo tee /etc/docker/daemon.json

     Validate BEFORE restarting - this is what saves you:

        sudo python3 -m json.tool /etc/docker/daemon.json && sudo systemctl restart docker

     If docker will not start after any edit, just delete the file; it is
     entirely optional:

        sudo rm -f /etc/docker/daemon.json
        sudo systemctl reset-failed docker.service
        sudo systemctl start docker

     The reset-failed is required: after a few rapid failures systemd
     reports "Start request repeated too quickly" and refuses to start
     the service at all, so fixing the file alone appears to do nothing.

  3. Check you are not rate-limited. Anonymous Docker Hub pulls are
     capped; `docker login` raises the limit.

  4. Pull the one image by hand to see the real error:

        docker pull postgres:16-alpine
EOF
exit 1
