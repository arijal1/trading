# Live Trading (Phase 6, brief Section 39)

**Nothing in this repository can currently place a real order.** No
exchange venue is integrated (see "Why no venue is wired up" below), and
even if one were, the default configuration refuses live trading at five
independent gates. This document describes the machinery that would gate
live trading, and what turning it on would require.

## The guard

`app/services/execution/live_guard.py`. Every live order must pass
`LiveTradingGuard`, which checks:

| Check | Source | Meaning |
|---|---|---|
| `TRADING_MODE_IS_LIVE` | `TRADING_MODE` | Global mode is `live`, not `paper`/`shadow` |
| `LIVE_TRADING_ENABLED` | `LIVE_TRADING` | Live trading explicitly enabled |
| `TRADING_CONFIRMATION` | `TRADING_CONFIRMATION` | Operator has confirmed intent |
| `VALID_EXCHANGE_CREDENTIALS` | setting + vault | Flag set *and* credentials actually stored |
| `RISK_LIMITS_VALID` | `RISK_LIMITS_VALID` | Risk limits reviewed and attested |
| `EMERGENCY_STOP_AVAILABLE` | `EMERGENCY_STOP_AVAILABLE` | Kill switch is functional |
| `NOT_EMERGENCY_STOPPED` | `system_state` | Kill switch not currently tripped |
| `NOT_TRADING_HALTED` | `system_state` | Trading not paused |
| `ACCOUNT_IS_LIVE_MODE` | `accounts.mode` | This account is a live account |
| `WITHDRAWALS_DISABLED` | `exchanges` + `DISABLE_WITHDRAWALS` | Key is withdrawal-restricted |
| `WITHIN_MAX_LIVE_CAPITAL` | `MAX_LIVE_CAPITAL` | Order notional within the per-order cap |

Three design properties matter more than the list itself:

- **It fails closed.** The guard starts from "refused". Any exception
  during evaluation — an unreachable database, a missing row, an
  unreadable setting — returns a refusal, never an approval. An
  unverifiable guardrail is treated as a failed guardrail.
- **It is not bypassable from the order path.** `OrderManager.submit_order`
  calls the guard itself; there is no `skip_guard` parameter and no
  alternate submission method. `tests/unit/test_live_guard.py` asserts
  this *structurally* — it inspects the signature and source of
  `submit_order` and fails if an escape hatch is ever added, or if the
  guard call is removed.
- **Every refusal names its cause.** A refusal returns the specific
  `GuardCheck` values that failed, so an operator never debugs a kill
  switch by guesswork.

Reconciliation is deliberately *not* gated: `OrderManager` still queries
and reconciles an existing order's status while the guard would refuse a
new one. Reconciliation is read-only against the venue and is how a stuck
order gets resolved — blocking it during an emergency stop would be
actively harmful.

### Checking readiness without placing an order

`GET /api/v1/trading/live-readiness?account_id=…&exchange_id=…`
(admin-only) dry-runs every check and returns exactly which ones fail. It
evaluates against a notional of `MAX_LIVE_CAPITAL` — the largest order
that could ever be permitted — so a green result means "the configuration
is ready", not "some small order would squeak through".

Against the shipped defaults it returns:

```json
{
  "allowed": false,
  "failed_checks": ["TRADING_MODE_IS_LIVE", "LIVE_TRADING_ENABLED",
                    "TRADING_CONFIRMATION", "VALID_EXCHANGE_CREDENTIALS",
                    "RISK_LIMITS_VALID"],
  "max_live_capital": "1000.0"
}
```

## Credentials

`app/services/exchanges/credentials.py` + `app/core/crypto.py`. Exchange
API keys are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before
they touch the database, using `MASTER_ENCRYPTION_KEY`.

- **No plaintext fallback.** An unset key raises rather than storing the
  credential unencrypted — a silent fallback is how plaintext secrets end
  up in production databases.
- **No weak-key stretching.** The setting must be a real Fernet key, not
  an arbitrary passphrase, so `MASTER_ENCRYPTION_KEY=changeme` cannot
  happen.
- **Authenticated encryption.** A tampered ciphertext fails to decrypt
  rather than yielding attacker-influenced plaintext.
- **Withdrawal restriction is enforced at registration.**
  `store_credentials` refuses outright unless the caller attests the key
  is withdrawal-restricted. This is an *attestation*, not a verification —
  only the exchange can report a key's real permissions, and no adapter
  exists yet to ask. Stated plainly rather than implying a guarantee the
  code cannot make.
- `ExchangeCredentials.__repr__` is redacted, so a credential reaching a
  log line, traceback, or debugger by accident does not print the secret.

Verified end-to-end: a plaintext canary stored through the real service
appears **zero** times anywhere in the `exchanges` table, while the
round-trip decrypt returns the original value.

## Resilience (Section 53)

`app/services/exchanges/resilience.py` — token-bucket rate limiting,
exponential backoff with full jitter, and a circuit breaker that fails
closed. The rule that shapes the whole module:

> **Never blindly retry an order submission.**

A timed-out order placement is genuinely ambiguous — the venue may have
accepted it. Retrying turns one intended order into two real ones. So
retries are restricted to operations a caller explicitly declares
`Idempotency.SAFE`, and order placement is always `UNSAFE` (exactly one
attempt, always). A generic `@retry` decorator would have silently undone
the `client_order_id` reconciliation guarantee that Phase 4 built, which
is why one isn't used.

## Why no venue is wired up

`app/services/exchanges/live_base.py` provides everything venue-agnostic —
credential injection, HMAC signing scaffolding, the resilience layer,
and the abstract hooks a venue subclass fills in. It ships **no concrete
venue**, deliberately:

1. **No exchange has been chosen.** That depends on the operator's
   jurisdiction, their account, and the terms they've accepted. It is not
   a decision this codebase should make on their behalf.
2. **The brief forbids reverse-engineering.** A real adapter must be
   written against an exchange's official, documented, ToS-permitted API —
   not a scraped or inferred one.
3. **It could not be tested here.** No credentials exist in this
   environment, so a venue integration written now could not be executed
   against the real API even once before shipping. Code whose failure mode
   is "places or loses real orders", shipped untested, is precisely what
   Section 39 exists to prevent.

`tests/unit/test_live_exchange_base.py::test_module_ships_no_concrete_venue`
enforces this boundary: adding a venue subclass to that module fails the
test, forcing the sandbox-validation and documentation conversation
rather than letting a venue slip in unnoticed.

### Adding a venue

1. Name the exchange and confirm its official API is ToS-permitted for
   automated trading in your jurisdiction.
2. Subclass `LiveExchangeAdapter`, implementing `sign()`, `auth_headers()`,
   and the `ExchangeAdapter` methods — mapping venue JSON into
   `app.schemas.exchange` types, never leaking raw venue shapes upward.
3. **Validate against the venue's sandbox/testnet first**, with real
   round-trips for every order type and every failure mode.
4. Only then configure a mainnet key — withdrawal-restricted, minimum
   necessary permissions.
5. Start with `MAX_LIVE_CAPITAL` set very low and raise it deliberately.

## Enabling live trading (checklist)

Not a recommendation to do this — a description of what it would take:

1. Paper trade long enough to have a real performance record
   (`docs/PAPER_TRADING.md`).
2. Integrate and sandbox-validate a venue adapter (above).
3. Generate secrets: `poetry run python -m app.cli generate-keys`.
4. Store withdrawal-restricted credentials through the vault.
5. Set `AUTH_REQUIRED=true` and provision an admin
   (`poetry run python -m app.cli create-admin …`) — see `docs/AUTH.md`.
6. Set `MAX_LIVE_CAPITAL` to an amount you can afford to lose entirely.
7. Flip `TRADING_MODE=live`, `LIVE_TRADING`, `TRADING_CONFIRMATION`,
   `VALID_EXCHANGE_CREDENTIALS`, `RISK_LIMITS_VALID`.
8. Confirm `GET /trading/live-readiness` returns `allowed: true`.
9. Confirm the kill switch works *before* trading, not after.

The brief's framing applies to every step: capital preservation first,
profitability second. No strategy in this repository has been shown to be
profitable, and nothing here should be read as suggesting otherwise.
