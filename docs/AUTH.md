# Authentication & Authorization (Phase 6, brief Section 46)

JWT bearer tokens plus role-based access control, gating the endpoints
that change state or touch money.

## Current posture, stated plainly

`AUTH_REQUIRED` defaults to **`false`**, which preserves the Phase 1-5
behaviour exactly: the API is unauthenticated, and the dashboard and every
existing test keep working unchanged.

That is a real trade-off, not an oversight. With `AUTH_REQUIRED=false`
anyone who can reach the API can trip the kill switch and read every
account. **It must not be exposed beyond a trusted network in that
state.** What Phase 6 adds is the *ability* to require auth and the
guarantee that when required it is enforced on every state-changing
route — flipping the default would have silently broken the running
dashboard, so enabling it is a deliberate deployment decision instead.

Live trading should never be enabled without also setting
`AUTH_REQUIRED=true` (see `docs/LIVE_TRADING.md`).

## Roles

| Role | Can |
|---|---|
| `admin` | Everything, including the kill switch, live-readiness, and user registration |
| `user` | Read account data, run paper ticks |
| unauthenticated | Only `/api/v1/health`, `/api/v1/auth/config`, `/api/v1/auth/login`, and `/metrics` when auth is on |

`/health` and `/metrics` stay open by design: liveness must never require
a credential, or an auth outage looks like a dead process to an
orchestrator and triggers a pointless restart loop. `/auth/login` and
`/auth/config` are open for the same structural reason — a client with no
credential has to be able to ask whether it needs one, and then get one.

**Reads are gated too, not just writes.** Through Phase 6 only
state-changing routes carried `require_admin`; every read — portfolio
equity, open positions, order history, system state — answered anyone who
asked, even with `AUTH_REQUIRED=true`. That is acceptable on a trusted LAN
and wrong for anything internet-reachable, since an attacker who cannot
*touch* anything can still read the entire trading book. Authentication is
now applied at the router (`app/api/v1/router.py`) so that a new endpoint
is protected by default and has to be deliberately added to the public
list to escape it — the safer direction for a mistake to run in.

## Endpoints

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/auth/login` | open (that's the point) |
| POST | `/api/v1/auth/register` | admin |
| GET | `/api/v1/auth/me` | any authenticated user |
| POST | `/api/v1/trading/emergency-stop` | admin |
| POST | `/api/v1/trading/resume` | admin |
| POST | `/api/v1/trading/pause` | admin |
| GET | `/api/v1/trading/live-readiness` | admin |
| POST | `/api/v1/accounts/{id}/paper/tick` | authenticated |

## Bootstrapping the first admin

`POST /auth/register` is admin-gated, which creates a chicken-and-egg
problem: the first admin cannot be created through an API that requires an
admin. Deliberately so — a self-service registration endpoint would give
an internet-reachable deployment a window in which anyone could register
themselves as admin.

The first admin is provisioned out-of-band:

```bash
poetry run python -m app.cli create-admin admin@example.com
```

The password is read from a prompt, never an argv argument (which would
land in shell history and the process table).

## Security properties

- **Argon2id password hashing** — memory-hard, so GPU/ASIC cracking is far
  more expensive per guess than bcrypt. Per-hash salt, so identical
  passwords don't produce identical hashes.
- **No default signing key.** `JWT_SECRET_KEY` has no default; a shipped
  default would be a publicly-known key anyone could mint admin tokens
  with. Unset raises at the point of use.
- **Minimum 32-byte signing key** (RFC 7518 §3.2). A shorter HMAC secret
  is brute-forceable offline from a single captured token.
- **Algorithm pinning at decode.** `algorithms=` is pinned to the
  configured algorithm rather than trusting the token's own header, which
  is what defeats the classic `alg: none` forgery and HMAC/RSA confusion.
- **User-enumeration resistance.** "No such user", "wrong password", and
  "inactive user" all return an identical 401 body, so login cannot be
  used to discover which emails have accounts.
- **Revocation is immediate.** Every request re-reads the user from the
  database, so deactivating an account invalidates its existing tokens at
  once rather than at their natural expiry.
- **Malformed stored hashes deny.** A corrupt hash authenticates nobody
  and doesn't 500 either.
- **Registration is audited** — an `audit_logs` row per created user.

## Scope (documented, not oversights)

- **No refresh tokens.** Tokens expire after `JWT_EXPIRE_MINUTES` (default
  60) and the user logs in again. Refresh-token rotation is meaningful
  work — revocation lists, reuse detection — and is not built.
- **No rate limiting on login.** Argon2 makes each guess expensive, but
  that is not a substitute for lockout/throttling. A real deployment
  should front this with a reverse proxy that rate-limits `/auth/login`.
- **No password reset flow**, no MFA, no session listing. All meaningful
  additions; none are built.
- **No token in the browser is perfectly safe.** The dashboard keeps its
  bearer token in `localStorage` (`apps/web/lib/auth.ts`), which any
  script on that origin can read. The alternative — an httpOnly cookie —
  would need credentialed CORS and CSRF defence for a dashboard served
  from a different origin than the API. The trade-off is stated in that
  file rather than hidden; the mitigations are that the dashboard loads
  no third-party scripts, tokens expire in an hour, and deactivating a
  user revokes them instantly.

## Signing in from the dashboard

The dashboard asks `GET /auth/config` on load and renders accordingly:

| `auth_required` | What you see |
|---|---|
| `false` | The dashboard, plus an amber **Unauthenticated mode** badge in the header — so an unguarded deployment is visible rather than silent |
| `true`, no valid token | A sign-in screen; no account data is fetched or rendered |
| `true`, valid token | The dashboard, with your email, role, and a sign-out button |

Turning it on:

```bash
# 1. Generate secrets (also prints MASTER_ENCRYPTION_KEY)
docker compose exec api python -m app.cli generate-keys   # copy into .env

# 2. Create the first admin — deliberately not possible through the API
docker compose exec api python -m app.cli create-admin you@example.com

# 3. Set AUTH_REQUIRED=true in .env, then restart the api service
```

There is no self-registration: `POST /auth/register` is admin-only, so an
internet-reachable deployment never has a window in which a stranger can
create themselves an admin account. The first admin comes from the CLI,
out-of-band.

Two failure modes worth naming, because they look identical from the
outside and are not:

- **A 401 with a token** means the token is stale or the user was
  deactivated. The dashboard discards it and returns to the sign-in
  screen rather than retrying forever with a dead credential.
- **The API not answering at all** shows a distinct "could not reach the
  trading API" panel with a retry button. Collapsing this into the login
  screen would send you hunting for a password problem when the backend
  is simply down.

**Serve it over TLS if it is reachable from outside your network.** A
bearer token on plain HTTP is readable in transit no matter where the
browser stores it. Terminate TLS at a reverse proxy in front of both
services, and block `/metrics` there — it stays open for Prometheus and
leaks operational detail otherwise.
