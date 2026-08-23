"""Emergency kill-switch primitive (Section 40).

The system_state table holds a single row. Every mutation goes through this
module so it always writes a matching audit_logs row (Section 33/57) — there
is no path that flips is_emergency_stopped without an audit trail.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditLog
from app.db.models.core import SystemState


async def get_or_create_state(db: AsyncSession) -> SystemState:
    result = await db.execute(select(SystemState).limit(1))
    state = result.scalar_one_or_none()
    if state is None:
        state = SystemState(is_emergency_stopped=False, is_trading_halted=False)
        db.add(state)
        await db.flush()
    return state


async def emergency_stop(db: AsyncSession, *, reason: str, actor: str) -> SystemState:
    state = await get_or_create_state(db)
    before = {"is_emergency_stopped": state.is_emergency_stopped}
    state.is_emergency_stopped = True
    state.is_trading_halted = True
    state.reason = reason
    state.set_by = actor
    state.set_at = datetime.now(UTC)
    db.add(
        AuditLog(
            actor=actor,
            action="emergency_stop",
            entity_type="system_state",
            entity_id=str(state.id),
            before=before,
            after={"is_emergency_stopped": True, "reason": reason},
        )
    )
    await db.commit()
    await db.refresh(state)
    return state


async def resume_trading(db: AsyncSession, *, reason: str, actor: str) -> SystemState:
    state = await get_or_create_state(db)
    before = {
        "is_emergency_stopped": state.is_emergency_stopped,
        "is_trading_halted": state.is_trading_halted,
    }
    state.is_emergency_stopped = False
    state.is_trading_halted = False
    state.reason = reason
    state.set_by = actor
    state.set_at = datetime.now(UTC)
    db.add(
        AuditLog(
            actor=actor,
            action="resume_trading",
            entity_type="system_state",
            entity_id=str(state.id),
            before=before,
            after={"is_emergency_stopped": False, "is_trading_halted": False, "reason": reason},
        )
    )
    await db.commit()
    await db.refresh(state)
    return state


async def pause_trading(db: AsyncSession, *, reason: str, actor: str) -> SystemState:
    state = await get_or_create_state(db)
    before = {"is_trading_halted": state.is_trading_halted}
    state.is_trading_halted = True
    state.reason = reason
    state.set_by = actor
    state.set_at = datetime.now(UTC)
    db.add(
        AuditLog(
            actor=actor,
            action="pause_trading",
            entity_type="system_state",
            entity_id=str(state.id),
            before=before,
            after={"is_trading_halted": True, "reason": reason},
        )
    )
    await db.commit()
    await db.refresh(state)
    return state
