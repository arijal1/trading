import pytest

from app.services import system_state as system_state_service


@pytest.mark.asyncio
async def test_emergency_stop_persists_and_audits(db_session):
    state = await system_state_service.emergency_stop(
        db_session, reason="manual test", actor="tester@example.com"
    )
    assert state.is_emergency_stopped is True
    assert state.is_trading_halted is True
    assert state.reason == "manual test"


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
