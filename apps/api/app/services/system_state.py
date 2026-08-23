"""Emergency kill-switch primitive (Section 40).

The system_state table holds a single row. Every mutation goes through this
module so it always writes a matching audit_logs row (Section 33/57) — there
is no path that flips is_emergency_stopped without an audit trail.

`get_or_create_state` always operates on one fixed, well-known primary key
rather than "whichever row happens to exist" — a plain check-then-insert
(SELECT ... LIMIT 1, then INSERT if empty) would let two concurrent
first-ever callers (e.g. two near-simultaneous POST /trading/emergency-stop
requests before any row exists) both see nothing and both insert a row.
For a kill switch that's worse than a mere duplicate: a `SELECT ... LIMIT 1`
with two rows present returns an arbitrary one of them, so an emergency
stop set on one row could be invisible to code that happens to read the
other. Pinning the id and upserting on the primary key makes a second row
structurally impossible.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import EMERGENCY_STOP_ACTIVE, TRADING_HALTED
from app.db.models.audit import AuditLog
from app.db.models.core import SystemState
from app.schemas.notification import NotificationMessage, NotificationSeverity
from app.services.notifications.service import NotificationService

# Fixed sentinel id for the one-and-only system_state row. Not a real
# entity identity, just a constant to upsert against.
SYSTEM_STATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _set_gauges(state: SystemState) -> None:
    EMERGENCY_STOP_ACTIVE.set(1 if state.is_emergency_stopped else 0)
    TRADING_HALTED.set(1 if state.is_trading_halted else 0)


async def get_or_create_state(db: AsyncSession) -> SystemState:
    stmt = (
        pg_insert(SystemState)
        .values(id=SYSTEM_STATE_ID, is_emergency_stopped=False, is_trading_halted=False)
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db.execute(stmt)
    result = await db.execute(select(SystemState).where(SystemState.id == SYSTEM_STATE_ID))
    state = result.scalar_one()
    _set_gauges(state)
    return state


async def emergency_stop(
    db: AsyncSession,
    *,
    reason: str,
    actor: str,
    notification_service: NotificationService | None = None,
) -> SystemState:
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
    _set_gauges(state)

    if notification_service is not None:
        await notification_service.notify(
            db,
            NotificationMessage(
                event_type="EMERGENCY_STOP",
                severity=NotificationSeverity.CRITICAL,
                title="Emergency stop activated",
                body=f"Trading halted by {actor}: {reason}",
            ),
        )
    return state


async def resume_trading(
    db: AsyncSession,
    *,
    reason: str,
    actor: str,
    notification_service: NotificationService | None = None,
) -> SystemState:
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
    _set_gauges(state)

    if notification_service is not None:
        await notification_service.notify(
            db,
            NotificationMessage(
                event_type="RESUME_TRADING",
                severity=NotificationSeverity.INFO,
                title="Trading resumed",
                body=f"Trading resumed by {actor}: {reason}",
            ),
        )
    return state


async def pause_trading(
    db: AsyncSession,
    *,
    reason: str,
    actor: str,
    notification_service: NotificationService | None = None,
) -> SystemState:
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
    _set_gauges(state)

    if notification_service is not None:
        await notification_service.notify(
            db,
            NotificationMessage(
                event_type="PAUSE_TRADING",
                severity=NotificationSeverity.WARNING,
                title="Trading paused",
                body=f"Trading paused by {actor}: {reason}",
            ),
        )
    return state
