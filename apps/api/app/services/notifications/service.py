"""Fans one notification out to every configured channel and persists an
`alerts` row per attempt — whether or not delivery actually succeeded, so a
failed Telegram send is itself visible in the audit trail rather than
silently swallowed.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.metrics import NOTIFICATIONS_SENT
from app.db.models.audit import Alert
from app.schemas.notification import NotificationMessage
from app.services.notifications.base import NotificationChannel
from app.services.notifications.log_channel import LogNotificationChannel
from app.services.notifications.telegram_channel import TelegramNotificationChannel


class NotificationService:
    def __init__(self, channels: list[NotificationChannel]) -> None:
        if not channels:
            raise ValueError("NotificationService requires at least one channel")
        self.channels = channels

    async def notify(self, db: AsyncSession, message: NotificationMessage) -> list[Alert]:
        alerts: list[Alert] = []
        for channel in self.channels:
            result = await channel.send(message)
            NOTIFICATIONS_SENT.labels(
                channel=channel.name, delivered=str(result.delivered).lower()
            ).inc()
            alert = Alert(
                account_id=message.account_id,
                type=message.event_type,
                payload={
                    "severity": message.severity.value,
                    "title": message.title,
                    "body": message.body,
                    "delivered": result.delivered,
                    "error": result.error,
                    **message.payload,
                },
                channel=channel.name,
            )
            db.add(alert)
            alerts.append(alert)
        await db.commit()
        return alerts


def build_default_notification_service(settings: Settings) -> NotificationService:
    """The log channel is always included — it can't fail and never depends
    on external configuration, so notification dispatch never has nowhere
    to go. Telegram is added on top of it only when both credentials are
    present; a partially-configured deployment (token without chat id, or
    vice versa) still falls back to log-only rather than raising.
    """
    channels: list[NotificationChannel] = [LogNotificationChannel()]
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        channels.append(
            TelegramNotificationChannel(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
        )
    return NotificationService(channels)
