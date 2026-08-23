"""Strategy registry lookups (brief Section 26: `strategies` table)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trading import Strategy
from app.services.strategy.aggregator import DEFAULT_STRATEGY_WEIGHTS

COMPOSITE_STRATEGY_NAME = "technical_composite_v1"
COMPOSITE_STRATEGY_VERSION = "0.1.0"


async def get_or_create_composite_strategy(db: AsyncSession) -> Strategy:
    """The single rule-based multi-signal strategy backtests run against
    in Phase 3 — see app/services/strategy/signals.py and aggregator.py.

    Upserts on the (name, version) unique constraint rather than
    check-then-insert: two concurrent first-ever callers racing a plain
    SELECT-then-INSERT could otherwise both see no existing row and both
    insert, producing two distinct "technical_composite_v1" strategies
    with different ids and splitting backtest history between them.
    """
    stmt = (
        pg_insert(Strategy)
        .values(
            name=COMPOSITE_STRATEGY_NAME,
            version=COMPOSITE_STRATEGY_VERSION,
            parameters={"strategies": list(DEFAULT_STRATEGY_WEIGHTS.keys())},
            enabled=False,  # not wired into any live/paper execution path yet
        )
        .on_conflict_do_nothing(index_elements=["name", "version"])
    )
    await db.execute(stmt)

    result = await db.execute(
        select(Strategy).where(
            Strategy.name == COMPOSITE_STRATEGY_NAME,
            Strategy.version == COMPOSITE_STRATEGY_VERSION,
        )
    )
    return result.scalar_one()
