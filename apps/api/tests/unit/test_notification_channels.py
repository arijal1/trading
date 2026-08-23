from __future__ import annotations

import httpx
import pytest

from app.schemas.notification import NotificationMessage, NotificationSeverity
from app.services.notifications.log_channel import LogNotificationChannel
from app.services.notifications.service import (
    NotificationService,
    build_default_notification_service,
)
from app.services.notifications.telegram_channel import TelegramNotificationChannel


def _message() -> NotificationMessage:
    return NotificationMessage(
        event_type="TEST_EVENT",
        severity=NotificationSeverity.INFO,
        title="Test title",
        body="Test body",
    )


@pytest.mark.asyncio
async def test_log_channel_always_delivers():
    channel = LogNotificationChannel()
    result = await channel.send(_message())
    assert result.delivered is True
    assert result.error is None


@pytest.mark.asyncio
async def test_telegram_channel_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bottoken123/sendMessage"
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    channel = TelegramNotificationChannel("token123", "chat456", client=client)
    result = await channel.send(_message())
    assert result.delivered is True
    assert result.error is None
    await client.aclose()


@pytest.mark.asyncio
async def test_telegram_channel_api_error_is_not_delivered():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    channel = TelegramNotificationChannel("token123", "chat456", client=client)
    result = await channel.send(_message())
    assert result.delivered is False
    assert "chat not found" in result.error
    await client.aclose()


@pytest.mark.asyncio
async def test_telegram_channel_network_error_is_not_delivered_and_does_not_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    channel = TelegramNotificationChannel("token123", "chat456", client=client)
    result = await channel.send(_message())
    assert result.delivered is False
    assert result.error is not None
    await client.aclose()


def test_notification_service_requires_at_least_one_channel():
    with pytest.raises(ValueError, match="at least one channel"):
        NotificationService([])


def test_default_service_is_log_only_when_telegram_unconfigured(monkeypatch):
    from app.core.config import Settings

    settings = Settings(TELEGRAM_BOT_TOKEN=None, TELEGRAM_CHAT_ID=None)
    service = build_default_notification_service(settings)
    assert [c.name for c in service.channels] == ["log"]


def test_default_service_adds_telegram_when_fully_configured():
    from app.core.config import Settings

    settings = Settings(TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="c")
    service = build_default_notification_service(settings)
    assert [c.name for c in service.channels] == ["log", "telegram"]


def test_default_service_stays_log_only_when_only_one_credential_set():
    from app.core.config import Settings

    settings = Settings(TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID=None)
    service = build_default_notification_service(settings)
    assert [c.name for c in service.channels] == ["log"]
