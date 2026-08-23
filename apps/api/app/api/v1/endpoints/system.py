from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_admin
from app.core.config import get_settings
from app.db.models.core import Account, Exchange
from app.db.session import get_db
from app.schemas.live_trading import LiveReadinessResponse
from app.schemas.system import (
    EmergencyActionRequest,
    SystemStateResponse,
    SystemStatusResponse,
)
from app.services import system_state as system_state_service
from app.services.execution.live_guard import LiveTradingGuard
from app.services.notifications.service import build_default_notification_service

router = APIRouter(tags=["system"])
_notification_service = build_default_notification_service(get_settings())


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
    payload: EmergencyActionRequest,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
) -> SystemStateResponse:
    state = await system_state_service.emergency_stop(
        db, reason=payload.reason, actor=payload.actor, notification_service=_notification_service
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
    payload: EmergencyActionRequest,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
) -> SystemStateResponse:
    state = await system_state_service.resume_trading(
        db, reason=payload.reason, actor=payload.actor, notification_service=_notification_service
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
    payload: EmergencyActionRequest,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
) -> SystemStateResponse:
    state = await system_state_service.pause_trading(
        db, reason=payload.reason, actor=payload.actor, notification_service=_notification_service
    )
    return SystemStateResponse(
        is_emergency_stopped=state.is_emergency_stopped,
        is_trading_halted=state.is_trading_halted,
        reason=state.reason,
        set_by=state.set_by,
        set_at=state.set_at,
    )


@router.get("/trading/live-readiness", response_model=LiveReadinessResponse)
async def live_readiness(
    account_id: uuid.UUID,
    exchange_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
) -> LiveReadinessResponse:
    """Dry-run the Section 39 guardrails for an account without placing an order.

    Evaluates against a notional of exactly MAX_LIVE_CAPITAL — the largest
    order that could ever be permitted — so a green result means "the
    configuration is ready", not "this particular small order would pass".
    """
    settings = get_settings()
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")

    exchange = await db.get(Exchange, exchange_id) if exchange_id else None
    max_live = Decimal(str(settings.MAX_LIVE_CAPITAL))

    decision = await LiveTradingGuard(settings).evaluate(
        db, account=account, exchange=exchange, notional_value=max_live
    )
    return LiveReadinessResponse(
        allowed=decision.allowed,
        failed_checks=decision.failed_checks,
        reason=decision.reason,
        max_live_capital=max_live,
    )
