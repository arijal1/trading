"""The always-available fallback channel: writes to structured logs rather
than an external service. Used as the sole channel whenever no real channel
(e.g. Telegram) is configured, so notification dispatch always has
somewhere to go and a caller never has to special-case "no channels".
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.schemas.notification import ChannelResult, NotificationMessage
from app.services.notifications.base import NotificationChannel

logger = get_logger(__name__)


class LogNotificationChannel(NotificationChannel):
    name = "log"

    async def send(self, message: NotificationMessage) -> ChannelResult:
        logger.info(
            "notification",
            event_type=message.event_type,
            severity=message.severity.value,
            title=message.title,
            body=message.body,
            account_id=str(message.account_id) if message.account_id else None,
        )
        return ChannelResult(delivered=True)
