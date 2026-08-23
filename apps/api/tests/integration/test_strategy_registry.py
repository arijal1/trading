from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.trading import Strategy
from app.services.strategy.registry import (
    COMPOSITE_STRATEGY_NAME,
    COMPOSITE_STRATEGY_VERSION,
    get_or_create_composite_strategy,
)


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent_within_one_session(db_session):
    first = await get_or_create_composite_strategy(db_session)
    await db_session.commit()
    second = await get_or_create_composite_strategy(db_session)
    await db_session.commit()
    assert first.id == second.id

    rows = await db_session.execute(
        select(Strategy).where(
            Strategy.name == COMPOSITE_STRATEGY_NAME,
            Strategy.version == COMPOSITE_STRATEGY_VERSION,
        )
    )
    assert len(list(rows.scalars())) == 1


@pytest.mark.asyncio
async def test_concurrent_first_callers_never_create_duplicate_rows(db_session):
    """Regression test: two concurrent first-ever callers (separate DB
    sessions, as separate HTTP requests would be) used to be able to both
    see no existing row and both insert, producing two distinct strategy
    rows with the same name. The (name, version) unique constraint plus
    upsert-on-conflict must prevent that.
    """
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def call_once() -> Strategy:
        async with session_factory() as session:
            strategy = await get_or_create_composite_strategy(session)
            await session.commit()
            return strategy

    try:
        results = await asyncio.gather(*(call_once() for _ in range(10)))
    finally:
        await engine.dispose()

    ids = {r.id for r in results}
    assert len(ids) == 1

    rows = await db_session.execute(
        select(Strategy).where(
            Strategy.name == COMPOSITE_STRATEGY_NAME,
            Strategy.version == COMPOSITE_STRATEGY_VERSION,
        )
    )
    assert len(list(rows.scalars())) == 1
