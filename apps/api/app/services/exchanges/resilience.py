"""Rate limiting, retry, and circuit breaking for exchange calls (Section 53).

The single most important rule here, and the reason this module is small
and explicit rather than a generic `@retry` decorator:

    **Never blindly retry an order submission.**

A timed-out order placement is genuinely ambiguous — the venue may have
accepted it. Retrying turns one intended order into two real ones. The
existing `OrderManager` already solves this correctly via
`client_order_id` + `get_order_status` reconciliation, so retries here are
restricted to operations the caller has explicitly declared idempotent
(`Idempotency.SAFE`), and `OrderManager` never declares order placement
safe. A generic decorator that retried everything by default would
silently undo that guarantee, which is why one isn't used.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

from app.core.logging import get_logger
from app.services.exchanges.base import ExchangeAdapterError

logger = get_logger(__name__)

T = TypeVar("T")


class Idempotency(StrEnum):
    #: Safe to retry: reads, and writes keyed so a repeat is a no-op.
    SAFE = "SAFE"
    #: Never retried automatically — a repeat could place a second order.
    UNSAFE = "UNSAFE"


class RateLimitedError(ExchangeAdapterError):
    """The venue signalled a rate limit (HTTP 429 or equivalent)."""


class CircuitOpenError(ExchangeAdapterError):
    """The circuit breaker is open; the call was not attempted."""


class TokenBucketRateLimiter:
    """Classic token bucket, shared across concurrent callers.

    Rate limiting is client-side and cooperative: it protects the venue's
    limits and our own IP reputation, but it is not a guarantee — the
    venue's own accounting is authoritative, so `RateLimitedError` still
    has to be handled when it happens anyway.
    """

    def __init__(self, rate_per_second: float, burst: int | None = None) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self.rate = rate_per_second
        self.capacity = float(burst if burst is not None else max(1, int(rate_per_second)))
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._updated) * self.rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                # Sleep only as long as it takes to earn one token.
                await asyncio.sleep((1 - self._tokens) / self.rate)


@dataclass
class CircuitBreaker:
    """Fails closed after repeated failures, then probes for recovery.

    Deliberately trips on consecutive failures rather than a failure
    *rate*: for an order path, five failures in a row is already a strong
    signal something is wrong, and waiting for a rate to converge means
    more real attempts against a venue that is misbehaving.
    """

    failure_threshold: int = 5
    reset_after_seconds: float = 30.0
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.reset_after_seconds:
            # Half-open: allow one probe through. If it fails, `record_failure`
            # re-opens immediately.
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
            logger.error(
                "circuit_breaker_opened",
                consecutive_failures=self._consecutive_failures,
                reset_after_seconds=self.reset_after_seconds,
            )


def backoff_delay(attempt: int, *, base: float = 0.5, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter (AWS's 'Exponential Backoff and
    Jitter'). Full jitter rather than fixed backoff because synchronised
    retries from many callers re-create the very spike that caused the
    failure."""
    ceiling = min(cap, base * (2**attempt))
    return random.uniform(0, ceiling)


class ResilientCaller:
    """Wraps exchange calls with rate limiting, retries, and a breaker."""

    def __init__(
        self,
        *,
        rate_limiter: TokenBucketRateLimiter | None = None,
        breaker: CircuitBreaker | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.breaker = breaker or CircuitBreaker()
        self.max_attempts = max_attempts

    async def call(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        idempotency: Idempotency,
        name: str = "exchange_call",
    ) -> T:
        if self.breaker.is_open:
            raise CircuitOpenError(
                f"circuit breaker is open; refusing to attempt {name}. "
                "Repeated failures suggest the venue or credentials are unhealthy."
            )

        # An UNSAFE operation gets exactly one attempt, always. Retrying it
        # is the duplicate-order bug this whole module exists to prevent.
        attempts = self.max_attempts if idempotency is Idempotency.SAFE else 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            if self.rate_limiter is not None:
                await self.rate_limiter.acquire()
            try:
                result = await operation()
            except ExchangeAdapterError as exc:
                last_error = exc
                self.breaker.record_failure()
                if attempt + 1 >= attempts:
                    break
                delay = backoff_delay(attempt)
                logger.warning(
                    "exchange_call_retrying",
                    operation=name,
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 3),
                    error=str(exc),
                )
                await asyncio.sleep(delay)
            else:
                self.breaker.record_success()
                return result

        assert last_error is not None
        logger.error("exchange_call_failed", operation=name, attempts=attempts)
        raise last_error
