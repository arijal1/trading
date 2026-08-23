from __future__ import annotations

import httpx
import pytest

from app.services.exchanges.base import ExchangeAdapterError
from app.services.exchanges.credentials import ExchangeCredentials
from app.services.exchanges.live_base import LiveExchangeAdapter
from app.services.exchanges.resilience import Idempotency, RateLimitedError

CREDS = ExchangeCredentials(api_key="test-key", api_secret="test-secret")


class _StubAdapter(LiveExchangeAdapter):
    """Minimal concrete subclass, for exercising the shared machinery only.

    Not a venue integration — the signing scheme here is invented for the
    test and matches no real exchange.
    """

    name = "stub"
    base_url = "https://api.stub.test"
    requests_per_second = 1000.0

    def sign(self, *, method: str, path: str, body: str, timestamp: str) -> str:
        return self.hmac_sha256(f"{timestamp}{method}{path}{body}")

    def auth_headers(self, *, signature: str, timestamp: str) -> dict[str, str]:
        return {
            "X-API-KEY": self._credentials.api_key,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": timestamp,
        }

    # The abstract ExchangeAdapter surface isn't under test here.
    async def get_balance(self, asset=None): ...
    async def get_positions(self): ...
    async def get_market_price(self, symbol): ...
    async def get_order_book(self, symbol, depth=20): ...
    async def get_ohlcv(self, symbol, timeframe, since, until): ...
    async def place_market_buy(self, request): ...
    async def place_market_sell(self, request): ...
    async def place_limit_buy(self, request): ...
    async def place_limit_sell(self, request): ...
    async def cancel_order(self, symbol, exchange_order_id): ...
    async def get_order_status(self, symbol, exchange_order_id): ...
    async def get_fees(self, symbol): ...
    async def get_trading_rules(self, symbol): ...
    async def get_account_status(self): ...
    async def get_open_orders(self, symbol=None): ...
    async def get_symbols(self): ...


def _adapter(handler) -> _StubAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return _StubAdapter(CREDS, client=client)


def test_base_url_must_be_set():
    class _NoUrl(_StubAdapter):
        base_url = ""

    with pytest.raises(NotImplementedError, match="base_url"):
        _NoUrl(CREDS)


@pytest.mark.asyncio
async def test_request_is_signed_and_carries_credentials():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"ok": True})

    adapter = _adapter(handler)
    assert await adapter.request("GET", "/v1/balance", idempotency=Idempotency.SAFE) == {
        "ok": True
    }
    assert seen["headers"]["x-api-key"] == "test-key"
    assert len(seen["headers"]["x-signature"]) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_signature_changes_with_the_request():
    a = _StubAdapter(CREDS).sign(method="GET", path="/a", body="", timestamp="1")
    b = _StubAdapter(CREDS).sign(method="GET", path="/b", body="", timestamp="1")
    c = _StubAdapter(CREDS).sign(method="GET", path="/a", body="", timestamp="2")
    assert len({a, b, c}) == 3


@pytest.mark.asyncio
async def test_the_api_secret_never_appears_in_a_signature():
    signature = _StubAdapter(CREDS).sign(method="GET", path="/a", body="", timestamp="1")
    assert "test-secret" not in signature


@pytest.mark.asyncio
async def test_http_429_becomes_rate_limited_error(monkeypatch):
    monkeypatch.setattr("app.services.exchanges.resilience.backoff_delay", lambda *_a, **_k: 0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"msg": "slow down"})

    adapter = _adapter(handler)
    with pytest.raises(RateLimitedError):
        await adapter.request("GET", "/v1/balance", idempotency=Idempotency.SAFE)


@pytest.mark.asyncio
async def test_http_error_becomes_adapter_error(monkeypatch):
    monkeypatch.setattr("app.services.exchanges.resilience.backoff_delay", lambda *_a, **_k: 0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    adapter = _adapter(handler)
    with pytest.raises(ExchangeAdapterError, match="500"):
        await adapter.request("GET", "/v1/balance", idempotency=Idempotency.SAFE)


@pytest.mark.asyncio
async def test_unsafe_request_is_attempted_exactly_once():
    """An order placement that fails must not be silently repeated."""
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500, text="boom")

    adapter = _adapter(handler)
    with pytest.raises(ExchangeAdapterError):
        await adapter.request("POST", "/v1/order", idempotency=Idempotency.UNSAFE, body="{}")
    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_safe_request_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.services.exchanges.resilience.backoff_delay", lambda *_a, **_k: 0)
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"ok": True})

    adapter = _adapter(handler)
    assert await adapter.request("GET", "/v1/balance", idempotency=Idempotency.SAFE) == {
        "ok": True
    }
    assert attempts["n"] == 3


def test_module_ships_no_concrete_venue():
    """Guards the documented scope boundary: if someone adds a real venue
    subclass here without the accompanying sandbox validation and docs
    update, this fails and forces that conversation."""
    import app.services.exchanges.live_base as module

    concrete = [
        obj
        for name, obj in vars(module).items()
        if isinstance(obj, type)
        and issubclass(obj, LiveExchangeAdapter)
        and obj is not LiveExchangeAdapter
    ]
    assert concrete == [], f"unexpected concrete venue adapter(s): {concrete}"
