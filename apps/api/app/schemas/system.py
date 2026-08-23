from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class SystemStatusResponse(BaseModel):
    status: str
    trading_mode: str
    database_connected: bool
    is_emergency_stopped: bool
    is_trading_halted: bool
    reason: str | None = None


class EmergencyActionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)
    actor: str = Field(min_length=1, max_length=128)


class SystemStateResponse(BaseModel):
    is_emergency_stopped: bool
    is_trading_halted: bool
    reason: str | None
    set_by: str | None
    set_at: datetime | None
