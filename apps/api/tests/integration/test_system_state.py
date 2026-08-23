import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.audit import Alert
from app.db.models.core import SystemState
from app.services import system_state as system_state_service
from app.services.notifications.log_channel import LogNotificationChannel
from app.services.notifications.service import NotificationService


@pytest.mark.asyncio
async def test_emergency_stop_persists_and_audits(db_session):
    state = await system_state_service.emergency_stop(
        db_session, reason="manual test", actor="tester@example.com"
    )
    assert state.is_emergency_stopped is True
    assert state.is_trading_halted is True
    assert state.reason == "manual test"


@pytest.mark.asyncio
async def test_emergency_stop_without_notification_service_sends_nothing(db_session):
    """The default (no notification_service passed) must stay a pure DB
    mutation — existing callers/tests that don't pass one shouldn't
    suddenly start writing alerts."""
    await system_state_service.emergency_stop(
        db_session, reason="manual test", actor="tester@example.com"
    )
    alerts = (await db_session.execute(select(Alert))).scalars().all()
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_emergency_stop_with_notification_service_sends_critical_alert(db_session):
    service = NotificationService([LogNotificationChannel()])
    await system_state_service.emergency_stop(
        db_session,
        reason="manual test",
        actor="tester@example.com",
        notification_service=service,
    )
    alerts = (await db_session.execute(select(Alert))).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].type == "EMERGENCY_STOP"
    assert alerts[0].payload["severity"] == "CRITICAL"
    assert alerts[0].payload["delivered"] is True


@pytest.mark.asyncio
async def test_resume_clears_emergency_stop(db_session):
    await system_state_service.emergency_stop(
        db_session, reason="halt", actor="tester@example.com"
    )
    state = await system_state_service.resume_trading(
        db_session, reason="all clear", actor="tester@example.com"
    )
    assert state.is_emergency_stopped is False
    assert state.is_trading_halted is False


@pytest.mark.asyncio
async def test_pause_halts_without_emergency_stop(db_session):
    state = await system_state_service.pause_trading(
        db_session, reason="scheduled maintenance", actor="tester@example.com"
    )
    assert state.is_trading_halted is True
    assert state.is_emergency_stopped is False


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_session):
    first = await system_state_service.get_or_create_state(db_session)
    second = await system_state_service.get_or_create_state(db_session)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_concurrent_first_callers_never_create_a_second_row(db_session):
    """Regression test: a kill switch is uniquely dangerous to duplicate.

    Two concurrent first-ever callers (separate DB sessions, as separate
    HTTP requests would be) used to be able to both see no existing
    system_state row and both insert one — and a later `SELECT ... LIMIT
    1` would then return an arbitrary one of the two, meaning an
    emergency stop set on one row could be invisible to code reading the
    other. The fixed-id upsert must make a second row impossible.
    """
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def call_once() -> SystemState:
        async with session_factory() as session:
            state = await system_state_service.get_or_create_state(session)
            await session.commit()
            return state

    try:
        results = await asyncio.gather(*(call_once() for _ in range(10)))
    finally:
        await engine.dispose()

    ids = {r.id for r in results}
    assert len(ids) == 1
    assert ids == {system_state_service.SYSTEM_STATE_ID}

    rows = await db_session.execute(select(SystemState))
    assert len(list(rows.scalars())) == 1
