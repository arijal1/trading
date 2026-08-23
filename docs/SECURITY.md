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
- AuthN/AuthZ (Phase 5+): JWT-based sessions, role-based access control on
  every state-changing endpoint.
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
