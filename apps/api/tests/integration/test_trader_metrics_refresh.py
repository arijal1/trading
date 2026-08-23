from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.core import Asset
from app.db.models.trader import Trader, TraderMetrics, TraderTrade
from app.services.copy_trading.trader_tracking import refresh_trader_metrics


@pytest_asyncio.fixture
async def seeded(db_session):
    trader = Trader(display_name="Test Trader", source="test", is_followed=True)
    asset = Asset(symbol="BTC")
    db_session.add_all([trader, asset])
    await db_session.commit()
    await db_session.refresh(trader)
    await db_session.refresh(asset)
    return {"trader": trader, "asset": asset}


@pytest.mark.asyncio
async def test_refresh_with_no_trades_persists_zeroed_metrics(db_session, seeded):
    row = await refresh_trader_metrics(db_session, seeded["trader"].id)
    assert row.num_trades == 0
    assert row.win_rate == Decimal("0")


@pytest.mark.asyncio
async def test_refresh_computes_and_persists_metrics_from_closed_trades(db_session, seeded):
    now = datetime.now(UTC)
    trades = [
        TraderTrade(
            trader_id=seeded["trader"].id,
            asset_id=seeded["asset"].id,
            side="BUY",
            entry_price=Decimal("100"),
            exit_price=Decimal("120"),
            size=Decimal("1"),
            opened_at=now - timedelta(days=2),
            closed_at=now - timedelta(days=1),
            realized_pnl=Decimal("20"),
        ),
        TraderTrade(
            trader_id=seeded["trader"].id,
            asset_id=seeded["asset"].id,
            side="BUY",
            entry_price=Decimal("100"),
            exit_price=Decimal("90"),
            size=Decimal("1"),
            opened_at=now - timedelta(days=1),
            closed_at=now,
            realized_pnl=Decimal("-10"),
        ),
        # An open trade (no closed_at) must be excluded from metrics.
        TraderTrade(
            trader_id=seeded["trader"].id,
            asset_id=seeded["asset"].id,
            side="BUY",
            entry_price=Decimal("100"),
            size=Decimal("1"),
            opened_at=now,
        ),
    ]
    db_session.add_all(trades)
    await db_session.commit()

    row = await refresh_trader_metrics(db_session, seeded["trader"].id)
    assert row.num_trades == 2
    assert row.win_rate == Decimal("0.5")
    assert row.last_activity_at is not None

    stored = await db_session.execute(
        select(TraderMetrics).where(TraderMetrics.trader_id == seeded["trader"].id)
    )
    assert len(list(stored.scalars())) == 1


@pytest.mark.asyncio
async def test_refresh_unknown_trader_raises(db_session):
    with pytest.raises(ValueError, match="not found"):
        await refresh_trader_metrics(db_session, uuid.uuid4())
