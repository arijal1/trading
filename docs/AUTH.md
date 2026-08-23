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
| unauthenticated | Only `/api/v1/health` and `/metrics` when auth is on |

`/health` and `/metrics` stay open by design: liveness must never require
a credential, or an auth outage looks like a dead process to an
orchestrator and triggers a pointless restart loop.

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
- **The dashboard does not log in yet.** `apps/web` calls the API without
  a token, so it works only while `AUTH_REQUIRED=false`. Wiring a login
  screen is the natural next increment (`docs/DASHBOARD.md`).
