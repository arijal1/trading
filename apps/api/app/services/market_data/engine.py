"""Market data ingestion (brief Section 5).

Fetches OHLCV from an `ExchangeAdapter` and stores it in the `candles`
table. Two rules drive the design:

- **Never re-request data that's already stored.** If every timestamp in
  the requested range is already in the DB, the adapter is not called at
  all.
- **Every write is idempotent.** Bulk insert uses `ON CONFLICT DO
  NOTHING` against the `(market_id, timeframe, ts)` unique constraint, so
  syncing the same range twice is always safe.

Missing candles within the range (a bar the adapter didn't return) are
logged and recorded as a `system_events` row rather than silently
dropped — Section 35 requires the system to notice missing data, not
just tolerate it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.audit import SystemEvent
from app.db.models.core import Candle
from app.schemas.exchange import TIMEFRAME_SECONDS, Timeframe
from app.services.exchanges.base import ExchangeAdapter

logger = get_logger(__name__)


@dataclass
class SyncResult:
    requested_count: int
    already_stored_count: int
    fetched_count: int
    inserted_count: int
    gap_timestamps: list[datetime] = field(default_factory=list)
    adapter_called: bool = False


def align_to_interval(ts: datetime, interval_seconds: int) -> datetime:
    """Floor a timestamp to the start of its interval bucket."""
    aligned_epoch = (ts.timestamp() // interval_seconds) * interval_seconds
    return datetime.fromtimestamp(aligned_epoch, tz=ts.tzinfo)


def _expected_timestamps(since: datetime, until: datetime, interval_seconds: int) -> list[datetime]:
    ts = align_to_interval(since, interval_seconds)
    out: list[datetime] = []
    while ts < until:
        out.append(ts)
        ts = datetime.fromtimestamp(ts.timestamp() + interval_seconds, tz=ts.tzinfo)
    return out


async def sync_candles(
    db: AsyncSession,
    *,
    market_id: uuid.UUID,
    symbol: str,
    timeframe: Timeframe,
    adapter: ExchangeAdapter,
    since: datetime,
    until: datetime,
) -> SyncResult:
    interval_seconds = TIMEFRAME_SECONDS[timeframe]
    expected = _expected_timestamps(since, until, interval_seconds)
    expected_set = set(expected)
    range_start = expected[0] if expected else since

    existing_rows = await db.execute(
        select(Candle.ts).where(
            Candle.market_id == market_id,
            Candle.timeframe == timeframe.value,
            Candle.ts >= range_start,
            Candle.ts < until,
        )
    )
    existing_set = {row[0] for row in existing_rows}
    missing = expected_set - existing_set

    result = SyncResult(
        requested_count=len(expected),
        already_stored_count=len(existing_set & expected_set),
        fetched_count=0,
        inserted_count=0,
    )

    if not missing:
        logger.debug(
            "market_data.sync.cache_hit",
            symbol=symbol,
            timeframe=timeframe.value,
            count=len(expected),
        )
        return result

    result.adapter_called = True
    bars = await adapter.get_ohlcv(symbol, timeframe, since=range_start, until=until)
    result.fetched_count = len(bars)

    rows_to_insert = [
        {
            "market_id": market_id,
            "timeframe": timeframe.value,
            "ts": bar.ts,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for bar in bars
        if bar.ts in missing
    ]

    if rows_to_insert:
        stmt = pg_insert(Candle).values(rows_to_insert)
        stmt = stmt.on_conflict_do_nothing(index_elements=["market_id", "timeframe", "ts"])
        await db.execute(stmt)
        await db.commit()
        result.inserted_count = len(rows_to_insert)

    received_timestamps = {bar.ts for bar in bars}
    gaps = sorted(missing - received_timestamps)
    result.gap_timestamps = gaps

    if gaps:
        logger.warning(
            "market_data.sync.gap_detected",
            symbol=symbol,
            timeframe=timeframe.value,
            gap_count=len(gaps),
            first_gap=gaps[0].isoformat(),
        )
        db.add(
            SystemEvent(
                component="market_data_engine",
                event_type="missing_candles",
                details={
                    "symbol": symbol,
                    "timeframe": timeframe.value,
                    "gap_count": len(gaps),
                    "gap_timestamps": [ts.isoformat() for ts in gaps[:50]],
                },
            )
        )
        await db.commit()

    return result
