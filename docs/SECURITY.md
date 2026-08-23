# Security Model

## Secrets

- No secret (API key, DB password, Telegram token, LLM key, exchange
  credential) is ever committed. `.env.example` at the repo root documents
  every variable name with a safe placeholder/default only.
- `.gitignore` excludes `.env`, `*.env`, and common credential file
  patterns.
- Exchange API keys are stored encrypted at rest (`accounts`/`exchanges`
  table columns are named `*_encrypted`; the encryption implementation
  lands with the first real exchange adapter in Phase 6, using a
  server-side key from the secret manager / env, never a hardcoded key).
- Exchange API keys used by this system must have **trading permissions
  only** — withdrawal permission is never required and the `exchanges`
  table has a `withdrawals_disabled` flag the system checks before
  accepting a credential set as valid for live trading (Section 39/33 of
  the brief).

## Application security (rolled out as each phase adds attack surface)

- Input validation: every external input (HTTP body, AI/LLM output,
  exchange webhook payload) is parsed through a strict Pydantic model;
  invalid/unexpected shapes are rejected, never coerced silently.
- SQL injection: SQLAlchemy parameterized queries only; no raw string
  interpolation into SQL.
- AuthN/AuthZ (Phase 6, docs/AUTH.md): JWT bearer tokens with Argon2id
  password hashing, decode-time algorithm pinning (defeats `alg: none`
  forgery), a minimum 32-byte signing key, enumeration-resistant login,
  and immediate revocation via a per-request user lookup. Role-based
  access control gates the kill switch, live-readiness, and user
  registration. Enforced when `AUTH_REQUIRED=true`; the default `false`
  preserves the Phase 1-5 unauthenticated posture, which means the API
  must not be exposed beyond a trusted network in that state.
- Secrets at rest (Phase 6, docs/LIVE_TRADING.md): exchange API
  credentials are Fernet-encrypted (authenticated AES) before reaching the
  database, with no plaintext fallback — an unset `MASTER_ENCRYPTION_KEY`
  raises rather than silently storing plaintext. Verified by a test
  asserting a plaintext canary appears nowhere in the stored row.
- Secret redaction in logs (Phase 6): a structlog processor redacts
  sensitive keys (api_key, secret, token, password, authorization,
  signature, …) anywhere in an event, including nested structures. This is
  defence in depth — the primary control is that no code passes a secret
  to a log call — because "no code ever does X" is a claim that decays as
  a codebase grows, and a leaked key in a log aggregator is not
  recoverable after the fact.
- CORS (Phase 5): `CORSMiddleware` restricted to an explicit allowlist
  (`CORS_ALLOWED_ORIGINS`, defaulting to the local dashboard's origin
  only) — never a wildcard — since the dashboard (`apps/web`) calls this
  API directly from the browser and every write endpoint (including the
  emergency-stop kill switch) is reachable to whatever origin is allowed.
- Rate limiting (Phase 5+) on the public API; exchange-side rate limiting
  (Section 53) with backoff/jitter/queuing in the market-data and
  execution layers from Phase 2 onward.
- Audit logging: every state-changing action (config change, emergency
  stop/resume, order placement, trader follow/unfollow) writes an
  `audit_logs` row with actor, before/after state, and timestamp.
- Dependency/secret scanning: CI runs `pip-audit`/`ruff` and a
  secret-scan step (Phase 1 CI includes lint + basic secret pattern check;
  a dedicated scanner is added once the dependency surface is non-trivial).

## AI safety boundary

The LLM/AI layer never has direct execution authority. Its output is
validated against a strict Pydantic schema (Section 51) and then passed
through the deterministic `PolicyValidator`, which can reject any decision
regardless of AI confidence. No natural-language output is ever parsed
into an order. See `docs/ARCHITECTURE.md` Section 8 and 15/51 of the
original brief.

## Live-trading guardrails

Live order execution is gated on all of: `LIVE_TRADING=true`,
`TRADING_CONFIRMATION=true`, valid (non-withdrawal) exchange credentials,
validated risk limits, and an available, tested emergency-stop path. Any
one missing condition blocks live trading entirely. `MAX_LIVE_CAPITAL`
hard-caps deployed capital independent of account balance. None of this
code exists yet (Phase 6) — `TRADING_MODE` defaults to `PAPER` and there is
currently no code path capable of placing a real order.
