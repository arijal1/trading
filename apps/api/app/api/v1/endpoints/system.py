from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.system import (
    EmergencyActionRequest,
    SystemStateResponse,
    SystemStatusResponse,
)
from app.services import system_state as system_state_service

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(db: AsyncSession = Depends(get_db)) -> SystemStatusResponse:
    settings = get_settings()
    db_connected = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_connected = False

    state = await system_state_service.get_or_create_state(db)
    await db.commit()

    return SystemStatusResponse(
        status="ok" if db_connected else "degraded",
        trading_mode=settings.TRADING_MODE.value,
        database_connected=db_connected,
        is_emergency_stopped=state.is_emergency_stopped,
        is_trading_halted=state.is_trading_halted,
        reason=state.reason,
    )


@router.post("/trading/emergency-stop", response_model=SystemStateResponse)
async def emergency_stop(
    payload: EmergencyActionRequest, db: AsyncSession = Depends(get_db)
) -> SystemStateResponse:
    state = await system_state_service.emergency_stop(
        db, reason=payload.reason, actor=payload.actor
    )
    return SystemStateResponse(
        is_emergency_stopped=state.is_emergency_stopped,
        is_trading_halted=state.is_trading_halted,
        reason=state.reason,
        set_by=state.set_by,
        set_at=state.set_at,
    )


@router.post("/trading/resume", response_model=SystemStateResponse)
async def resume_trading(
    payload: EmergencyActionRequest, db: AsyncSession = Depends(get_db)
) -> SystemStateResponse:
    state = await system_state_service.resume_trading(
        db, reason=payload.reason, actor=payload.actor
    )
    return SystemStateResponse(
        is_emergency_stopped=state.is_emergency_stopped,
        is_trading_halted=state.is_trading_halted,
        reason=state.reason,
        set_by=state.set_by,
        set_at=state.set_at,
    )


@router.post("/trading/pause", response_model=SystemStateResponse)
async def pause_trading(
    payload: EmergencyActionRequest, db: AsyncSession = Depends(get_db)
) -> SystemStateResponse:
    state = await system_state_service.pause_trading(
        db, reason=payload.reason, actor=payload.actor
    )
    return SystemStateResponse(
        is_emergency_stopped=state.is_emergency_stopped,
        is_trading_halted=state.is_trading_halted,
        reason=state.reason,
        set_by=state.set_by,
        set_at=state.set_at,
    )
