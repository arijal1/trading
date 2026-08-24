# Running on a Raspberry Pi

A Pi is a good host for this: the thing that makes paper trading useful is
ticking markets continuously, and a $60 board drawing 5W is a better place
for that than a laptop you close at night.

## Will it work?

Yes, on a **Pi 4 or Pi 5 running the 64-bit Raspberry Pi OS**. Verified by
checking every dependency rather than assuming:

| Component | arm64 available |
|---|---|
| `postgres:16-alpine` | yes |
| `redis:7-alpine`, `prom/prometheus` | yes |
| `python:3.11-slim`, `node:22-slim` | yes |
| numpy, pandas, psycopg2-binary, cryptography, argon2-cffi-bindings | yes (prebuilt aarch64 wheels) |

**32-bit will not work.** On `armv7l` there are no prebuilt numpy/pandas
wheels, so they compile from source and typically fail. Check with
`uname -m` — you want `aarch64`, not `armv7l`. If it's 32-bit, reflash
with the 64-bit image; there's no workaround worth pursuing.

### Recommended

- **Pi 5, or Pi 4 with 4GB+.** 2GB works but needs swap (below).
- **Boot from a USB3 SSD, not the SD card.** Postgres and Prometheus write
  continuously; a cheap SD card will degrade in months. This is the single
  biggest reliability upgrade.
- Active cooling if it will run 24/7.

## Setup

```bash
# 1. Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# log out and back in, then check:
docker run --rm hello-world

# 2. The code
git clone https://github.com/arijal1/trading.git
cd trading
git checkout claude/ai-crypto-trading-platform-yhb4nj
cp .env.example .env

# 3. Check the host before building
bash scripts/doctor.sh

# 4. Start, with the Pi overlay
docker compose -f infrastructure/docker-compose.yml \
               -f infrastructure/docker-compose.pi.yml up --build -d

# 5. Seed demo data
docker compose -f infrastructure/docker-compose.yml \
               -f infrastructure/docker-compose.pi.yml \
               exec api python -m app.cli seed-demo
```

Then browse to `http://<pi-ip>:3000` from any machine on your network.
Find the IP with `hostname -I`.

If image pulls fail with `TLS handshake timeout` — common on a Pi over
wifi — run `bash scripts/pull.sh`. It pulls one image at a time with
retries, resuming rather than restarting, and prints the network fixes
that actually help if it still cannot get through.

**The first build takes 15–40 minutes.** Most of it is `npm ci` and the
Next.js build. Subsequent builds are cached and much faster. It has not
hung — let it run.

## What the Pi overlay changes

`infrastructure/docker-compose.pi.yml` is an overlay, not a replacement —
pass both `-f` flags. It:

- **Cuts SD-card writes.** Prometheus retention drops from 15 days to 3
  (and 256MB); Postgres gets `synchronous_commit=off`, WAL compression,
  and longer checkpoint intervals. That last one trades a few hundred
  milliseconds of crash-durability for a large reduction in writes — fine
  for paper-trading history, and something to reverse if this ever holds
  real money.
- **Caps memory per service**, so Postgres doesn't assume it owns a server
  and Redis can't balloon.

## If the build gets OOM-killed

Symptom: the web build dies with **exit code 137** and no useful message.
That's the kernel's OOM killer, not a code error.

Add swap (the simplest fix):

```bash
sudo dphys-swapfile swapoff
sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
free -h    # confirm swap is present
```

If it still fails, cap Node's heap explicitly so it fails predictably
rather than being killed:

```bash
docker compose -f infrastructure/docker-compose.yml \
               -f infrastructure/docker-compose.pi.yml \
               build --build-arg NODE_OPTIONS=--max-old-space-size=1024 web
```

Or skip the dashboard entirely and run the API only — everything the
dashboard does is available over HTTP:

```bash
docker compose -f infrastructure/docker-compose.yml \
               -f infrastructure/docker-compose.pi.yml \
               up -d postgres redis api
```

## Reaching it from outside your house

This is where the Pi answers the "can I put it on my domain?" question —
and the answer is better than a subdomain.

**Do not port-forward this to the internet.** With `AUTH_REQUIRED=false`
(the current default) and no login screen on the dashboard, anyone who
finds the address can read your accounts and trip the kill switch. Port
forwarding also exposes the Pi's SSH to the world.

**Use a private network overlay instead.** [Tailscale](https://tailscale.com)
is the least-effort option and free for personal use:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Install Tailscale on your phone and laptop too, and the Pi is reachable at
a stable private address from anywhere — `http://<pi-name>:3000` — with
nothing exposed publicly. Encrypted, no firewall changes, no certificates,
and no unauthenticated dashboard on the open internet.

If you specifically want `trading.yourdomain.com` to work, Tailscale can
map a domain to a private machine, or Cloudflare Tunnel can publish it
without opening a port. Either way, **finish the dashboard login first** —
see `docs/AUTH.md`. A public hostname in front of an unauthenticated
control panel is still an unauthenticated control panel.

## Keeping it running

Every service already uses `restart: unless-stopped`, so the stack comes
back after a reboot or power cut once Docker itself starts on boot:

```bash
sudo systemctl enable docker
```

Note that **there is no scheduler yet** — ticks only happen when something
calls the endpoint. Until that's built, a cron entry is a reasonable
stopgap:

```bash
# every hour, tick one market (replace the IDs)
0 * * * * curl -sS -X POST "http://localhost:8000/api/v1/accounts/<ACCOUNT_ID>/paper/tick" \
  -H 'Content-Type: application/json' \
  -d '{"market_id":"<MARKET_ID>","timeframe":"1h"}' >> /var/log/trading-tick.log 2>&1
```

Sync candles on the same schedule, or the tick has nothing new to analyse.

## Performance expectations

A Pi 4 is roughly 5–10× slower than a modern laptop for this workload.
In practice:

- One paper tick: well under a second. Fine.
- A 300-bar backtest: a few seconds rather than sub-second. Fine.
- The image build: slow, once. Fine.

None of this is on a latency-critical path today, because the mock adapter
is synthetic and nothing is trading real money. If a real exchange is
integrated later, revisit — a Pi on home broadband is not where you want
latency-sensitive execution running.
