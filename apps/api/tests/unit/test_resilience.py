from __future__ import annotations

import asyncio
import time

import pytest

from app.services.exchanges.base import ExchangeAdapterError
from app.services.exchanges.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    Idempotency,
    ResilientCaller,
    TokenBucketRateLimiter,
    backoff_delay,
)


def _counting_operation(fail_times: int):
    """Returns (operation, calls) where operation fails `fail_times` then succeeds."""
    calls = {"n": 0}

    async def operation():
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise ExchangeAdapterError("transient")
        return "ok"

    return operation, calls


@pytest.mark.asyncio
async def test_safe_operation_is_retried_until_success(monkeypatch):
    monkeypatch.setattr("app.services.exchanges.resilience.backoff_delay", lambda *_a, **_k: 0)
    operation, calls = _counting_operation(fail_times=2)
    caller = ResilientCaller(max_attempts=3)
    assert await caller.call(operation, idempotency=Idempotency.SAFE) == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_unsafe_operation_is_never_retried():
    """The rule this module exists for: retrying an order placement can
    turn one intended order into two real ones."""
    operation, calls = _counting_operation(fail_times=1)
    caller = ResilientCaller(max_attempts=5)
    with pytest.raises(ExchangeAdapterError):
        await caller.call(operation, idempotency=Idempotency.UNSAFE)
    assert calls["n"] == 1, "an UNSAFE operation must be attempted exactly once"


@pytest.mark.asyncio
async def test_safe_operation_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("app.services.exchanges.resilience.backoff_delay", lambda *_a, **_k: 0)
    operation, calls = _counting_operation(fail_times=99)
    caller = ResilientCaller(max_attempts=3)
    with pytest.raises(ExchangeAdapterError):
        await caller.call(operation, idempotency=Idempotency.SAFE)
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_successful_call_is_not_retried():
    operation, calls = _counting_operation(fail_times=0)
    caller = ResilientCaller(max_attempts=3)
    assert await caller.call(operation, idempotency=Idempotency.SAFE) == "ok"
    assert calls["n"] == 1


def test_backoff_is_bounded_and_jittered():
    delays = [backoff_delay(attempt, base=0.5, cap=30.0) for attempt in range(6)]
    assert all(0 <= d <= 30.0 for d in delays)
    # Full jitter means repeated calls at the same attempt differ.
    samples = {round(backoff_delay(3), 6) for _ in range(30)}
    assert len(samples) > 1, "backoff must be jittered, not deterministic"


def test_backoff_ceiling_grows_then_caps():
    assert max(backoff_delay(0, base=1.0, cap=100.0) for _ in range(50)) <= 1.0
    assert max(backoff_delay(2, base=1.0, cap=100.0) for _ in range(50)) <= 4.0
    assert max(backoff_delay(20, base=1.0, cap=10.0) for _ in range(50)) <= 10.0


def test_circuit_breaker_opens_after_threshold():
    breaker = CircuitBreaker(failure_threshold=3)
    assert breaker.is_open is False
    for _ in range(2):
        breaker.record_failure()
    assert breaker.is_open is False
    breaker.record_failure()
    assert breaker.is_open is True


def test_circuit_breaker_success_resets_the_count():
    breaker = CircuitBreaker(failure_threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.is_open is False


def test_circuit_breaker_half_opens_after_reset_window():
    breaker = CircuitBreaker(failure_threshold=1, reset_after_seconds=0.05)
    breaker.record_failure()
    assert breaker.is_open is True
    time.sleep(0.06)
    assert breaker.is_open is False, "breaker must allow a probe after the reset window"


@pytest.mark.asyncio
async def test_open_circuit_refuses_without_attempting_the_call():
    operation, calls = _counting_operation(fail_times=0)
    breaker = CircuitBreaker(failure_threshold=1, reset_after_seconds=60)
    breaker.record_failure()
    caller = ResilientCaller(breaker=breaker)
    with pytest.raises(CircuitOpenError):
        await caller.call(operation, idempotency=Idempotency.SAFE)
    assert calls["n"] == 0, "an open circuit must not touch the venue at all"


@pytest.mark.asyncio
async def test_rate_limiter_allows_burst_then_throttles():
    limiter = TokenBucketRateLimiter(rate_per_second=10, burst=3)
    started = time.monotonic()
    for _ in range(3):
        await limiter.acquire()
    assert time.monotonic() - started < 0.05, "burst capacity must not be throttled"

    await limiter.acquire()
    assert time.monotonic() - started >= 0.09, "the 4th call must wait for a token"


@pytest.mark.asyncio
async def test_rate_limiter_is_safe_under_concurrency():
    limiter = TokenBucketRateLimiter(rate_per_second=50, burst=2)
    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(6)))
    elapsed = time.monotonic() - started
    # 2 free (burst) + 4 more at 50/s = at least ~0.08s.
    assert elapsed >= 0.07


def test_rate_limiter_rejects_a_nonsensical_rate():
    with pytest.raises(ValueError, match="positive"):
        TokenBucketRateLimiter(rate_per_second=0)


@pytest.mark.asyncio
async def test_rate_limiter_is_applied_before_each_attempt(monkeypatch):
    monkeypatch.setattr("app.services.exchanges.resilience.backoff_delay", lambda *_a, **_k: 0)
    acquired = {"n": 0}

    class _CountingLimiter(TokenBucketRateLimiter):
        async def acquire(self) -> None:
            acquired["n"] += 1

    operation, _ = _counting_operation(fail_times=2)
    caller = ResilientCaller(
        rate_limiter=_CountingLimiter(rate_per_second=1000), max_attempts=3
    )
    await caller.call(operation, idempotency=Idempotency.SAFE)
    assert acquired["n"] == 3, "every attempt, including retries, must take a token"
