"""Notification channel contract every delivery mechanism implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.notification import ChannelResult, NotificationMessage


class NotificationChannel(ABC):
    name: str

    @abstractmethod
    async def send(self, message: NotificationMessage) -> ChannelResult: ...
