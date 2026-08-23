"""Strategy registry lookups (brief Section 26: `strategies` table)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trading import Strategy
from app.services.strategy.aggregator import DEFAULT_STRATEGY_WEIGHTS

COMPOSITE_STRATEGY_NAME = "technical_composite_v1"


async def get_or_create_composite_strategy(db: AsyncSession) -> Strategy:
    """The single rule-based multi-signal strategy backtests run against
    in Phase 3 — see app/services/strategy/signals.py and aggregator.py.
    """
    result = await db.execute(select(Strategy).where(Strategy.name == COMPOSITE_STRATEGY_NAME))
    strategy = result.scalar_one_or_none()
    if strategy is None:
        strategy = Strategy(
            name=COMPOSITE_STRATEGY_NAME,
            version="0.1.0",
            parameters={"strategies": list(DEFAULT_STRATEGY_WEIGHTS.keys())},
            enabled=False,  # not wired into any live/paper execution path yet
        )
        db.add(strategy)
        await db.flush()
    return strategy
