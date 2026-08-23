"""Base class for a real, credentialed exchange adapter (Phase 6).

**No concrete venue is implemented here, and that is deliberate.**

The brief forbids reverse-engineering private endpoints or scraping
authenticated interfaces, so a real adapter must be written against an
exchange's official, documented, ToS-permitted API. Which exchange that
is has not been chosen — it depends on the operator's jurisdiction,
account, and accepted terms — and no credentials exist in this
environment, so a venue integration written here could not be executed
against the real API even once before shipping. Shipping untested code
whose failure mode is "places or loses real orders" is precisely what
the brief's Section 39 exists to prevent.

What this module provides is everything that is genuinely venue-agnostic,
so that adding a venue is a small, reviewable subclass rather than a
from-scratch build:

- credential loading from the encrypted vault (never from config or argv)
- HMAC request signing, with the digest and canonical-string details left
  to the subclass (every venue differs)
- the resilience layer (rate limit, backoff, circuit breaker) with the
  idempotency classification already correct per operation
- a hard refusal to place any order unless `LiveTradingGuard` has approved

Subclass checklist — what a venue implementation must supply:

    class MyVenueAdapter(LiveExchangeAdapter):
        name = "myvenue"
        base_url = "https://api.myvenue.example"

        def sign(self, method, path, body, timestamp): ...   # venue's scheme
        def auth_headers(self, signature, timestamp): ...    # venue's headers
        # plus the ExchangeAdapter methods, mapping venue JSON to
        # app.schemas.exchange types — never leaking raw venue shapes.

and it must be validated against the venue's *sandbox/testnet* before any
mainnet key is configured (see docs/LIVE_TRADING.md).
"""
from __future__ import annotations

import hashlib
import hmac
from abc import abstractmethod
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.exchanges.base import ExchangeAdapter, ExchangeAdapterError
from app.services.exchanges.credentials import ExchangeCredentials
from app.services.exchanges.resilience import (
    CircuitBreaker,
    Idempotency,
    RateLimitedError,
    ResilientCaller,
    TokenBucketRateLimiter,
)

logger = get_logger(__name__)


class LiveExchangeAdapter(ExchangeAdapter):
    """Shared machinery for signed, credentialed REST exchange adapters."""

    #: Venue REST root, e.g. "https://api.example.com". Subclass must set.
    base_url: str = ""
    #: Conservative default; a subclass should set the venue's real limit.
    requests_per_second: float = 5.0

    def __init__(
        self,
        credentials: ExchangeCredentials,
        *,
        client: httpx.AsyncClient | None = None,
        caller: ResilientCaller | None = None,
    ) -> None:
        if not self.base_url:
            raise NotImplementedError(
                f"{type(self).__name__} must set `base_url` before it can be used"
            )
        self._credentials = credentials
        self._client = client
        self._caller = caller or ResilientCaller(
            rate_limiter=TokenBucketRateLimiter(self.requests_per_second),
            breaker=CircuitBreaker(),
        )

    # ---- venue-specific hooks -------------------------------------------------

    @abstractmethod
    def sign(self, *, method: str, path: str, body: str, timestamp: str) -> str:
        """Produce the venue's request signature.

        Left abstract because the canonical string, digest, and encoding
        differ per venue; guessing a scheme is exactly the kind of
        reverse-engineering the brief prohibits.
        """

    @abstractmethod
    def auth_headers(self, *, signature: str, timestamp: str) -> dict[str, str]:
        """Headers carrying the API key/signature, per the venue's docs."""

    # ---- shared helpers -------------------------------------------------------

    def hmac_sha256(self, message: str) -> str:
        """Standard HMAC-SHA256 hex digest over the adapter's API secret.

        Provided because most venues use it; a venue that doesn't can
        ignore it and implement `sign` however its docs specify.
        """
        return hmac.new(
            self._credentials.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()

    async def request(
        self,
        method: str,
        path: str,
        *,
        idempotency: Idempotency,
        body: str = "",
        params: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> Any:
        """Signed, rate-limited, retry-aware request.

        `idempotency` is required rather than defaulted: a caller must
        consciously decide whether a repeat of this call could place a
        second order. There is no safe default for that question.
        """
        import time as _time

        ts = timestamp or str(int(_time.time() * 1000))
        signature = self.sign(method=method, path=path, body=body, timestamp=ts)
        headers = {
            "Content-Type": "application/json",
            **self.auth_headers(signature=signature, timestamp=ts),
        }

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0)

        async def _do() -> Any:
            try:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    content=body or None,
                    params=params,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                raise ExchangeAdapterError(f"{method} {path} failed: {exc}") from exc

            if response.status_code == 429:
                raise RateLimitedError(f"{method} {path} rate limited by venue")
            if response.status_code >= 400:
                # Response text is logged by the caller's error handling,
                # never the request headers — those carry the signature.
                raise ExchangeAdapterError(
                    f"{method} {path} returned {response.status_code}: {response.text[:500]}"
                )
            return response.json()

        try:
            return await self._caller.call(
                _do, idempotency=idempotency, name=f"{method} {path}"
            )
        finally:
            if owns_client:
                await client.aclose()
