from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class NotificationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class NotificationMessage(BaseModel):
    event_type: str
    severity: NotificationSeverity
    title: str
    body: str
    account_id: uuid.UUID | None = None
    payload: dict = Field(default_factory=dict)


class ChannelResult(BaseModel):
    delivered: bool
    error: str | None = None
