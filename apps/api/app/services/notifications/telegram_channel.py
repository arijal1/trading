"""Telegram Bot API channel (brief Section 45).

Speaks the public Bot API's `sendMessage` method over HTTPS — nothing
scraped, no private/unofficial endpoints (Section 4's constraint applies
here too, not just to exchanges). Requires a bot token and chat id
(`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`); `build_default_notification_service`
only registers this channel when both are configured, so an unconfigured
deployment falls back to `LogNotificationChannel` rather than silently
doing nothing or crashing on a missing credential.
"""
from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.schemas.notification import ChannelResult, NotificationMessage
from app.services.notifications.base import NotificationChannel

logger = get_logger(__name__)

_API_BASE = "https://api.telegram.org"


class TelegramNotificationChannel(NotificationChannel):
    name = "telegram"

    def __init__(
        self, bot_token: str, chat_id: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = client

    def _format(self, message: NotificationMessage) -> str:
        return f"[{message.severity.value}] {message.title}\n{message.body}"

    async def send(self, message: NotificationMessage) -> ChannelResult:
        url = f"{_API_BASE}/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": self._format(message)}

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=10.0)
        try:
            response = await client.post(url, json=payload)
            body = response.json()
            if response.status_code == 200 and body.get("ok") is True:
                return ChannelResult(delivered=True)
            error = body.get("description", f"HTTP {response.status_code}")
            logger.warning("telegram_notification_failed", error=error)
            return ChannelResult(delivered=False, error=error)
        except httpx.HTTPError as exc:
            logger.warning("telegram_notification_error", error=str(exc))
            return ChannelResult(delivered=False, error=str(exc))
        finally:
            if owns_client:
                await client.aclose()
