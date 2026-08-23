from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Asset, Candle, Exchange, Market
from app.schemas.exchange import OHLCVBar, Timeframe
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.market_data.engine import sync_candles
from app.services.technical_analysis.engine import TechnicalAnalysisEngine, candles_to_dataframe


@pytest_asyncio.fixture
async def seeded_market(db_session: AsyncSession) -> Market:
    exchange = Exchange(name="Mock Exchange", adapter_type="mock")
    base = Asset(symbol="BTC")
    quote = Asset(symbol="USD")
    db_session.add_all([exchange, base, quote])
    await db_session.flush()

    market = Market(
        exchange_id=exchange.id,
        base_asset_id=base.id,
        quote_asset_id=quote.id,
        symbol="BTC/USD",
    )
    db_session.add(market)
    await db_session.commit()
    await db_session.refresh(market)
    return market


class _CountingAdapter(MockExchangeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.ohlcv_call_count = 0

    async def get_ohlcv(self, symbol, timeframe, since, until) -> list[OHLCVBar]:
        self.ohlcv_call_count += 1
        return await super().get_ohlcv(symbol, timeframe, since, until)


@pytest.mark.asyncio
async def test_sync_candles_inserts_expected_bar_count(db_session, seeded_market):
    adapter = MockExchangeAdapter()
    until = datetime(2026, 1, 2, tzinfo=UTC)
    since = until - timedelta(hours=48)

    result = await sync_candles(
        db_session,
        market_id=seeded_market.id,
        symbol=seeded_market.symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=since,
        until=until,
    )

    assert result.adapter_called is True
    assert result.inserted_count == 48
    assert result.gap_timestamps == []

    stored = await db_session.execute(
        select(Candle).where(Candle.market_id == seeded_market.id)
    )
    assert len(list(stored.scalars())) == 48


@pytest.mark.asyncio
async def test_sync_candles_is_idempotent_and_skips_adapter_call(db_session, seeded_market):
    adapter = _CountingAdapter()
    until = datetime(2026, 1, 2, tzinfo=UTC)
    since = until - timedelta(hours=24)

    first = await sync_candles(
        db_session,
        market_id=seeded_market.id,
        symbol=seeded_market.symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=since,
        until=until,
    )
    assert first.inserted_count == 24
    assert adapter.ohlcv_call_count == 1

    second = await sync_candles(
        db_session,
        market_id=seeded_market.id,
        symbol=seeded_market.symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=since,
        until=until,
    )
    assert second.inserted_count == 0
    assert second.adapter_called is False
    assert adapter.ohlcv_call_count == 1  # no second network/adapter call

    stored = await db_session.execute(
        select(Candle).where(Candle.market_id == seeded_market.id)
    )
    assert len(list(stored.scalars())) == 24


@pytest.mark.asyncio
async def test_sync_candles_partial_overlap_only_fetches_and_inserts_missing(
    db_session, seeded_market
):
    adapter = _CountingAdapter()
    until = datetime(2026, 1, 2, tzinfo=UTC)
    first_since = until - timedelta(hours=10)

    await sync_candles(
        db_session,
        market_id=seeded_market.id,
        symbol=seeded_market.symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=first_since,
        until=until,
    )
    assert adapter.ohlcv_call_count == 1

    wider_since = until - timedelta(hours=20)
    result = await sync_candles(
        db_session,
        market_id=seeded_market.id,
        symbol=seeded_market.symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=wider_since,
        until=until,
    )
    assert adapter.ohlcv_call_count == 2
    assert result.inserted_count == 10  # only the newly-missing 10 hours

    stored = await db_session.execute(
        select(Candle).where(Candle.market_id == seeded_market.id)
    )
    assert len(list(stored.scalars())) == 20


@pytest.mark.asyncio
async def test_technical_analysis_over_synced_candles(db_session, seeded_market):
    adapter = MockExchangeAdapter()
    until = datetime(2026, 1, 3, tzinfo=UTC)
    since = until - timedelta(hours=80)

    await sync_candles(
        db_session,
        market_id=seeded_market.id,
        symbol=seeded_market.symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=since,
        until=until,
    )

    stored = await db_session.execute(
        select(Candle).where(Candle.market_id == seeded_market.id).order_by(Candle.ts)
    )
    candles = list(stored.scalars())
    assert len(candles) == 80

    df = candles_to_dataframe(candles)
    engine = TechnicalAnalysisEngine()
    result = engine.analyze(df, symbol=seeded_market.symbol, timeframe="1h")

    assert result.bar_count == 80
    assert 0 <= result.trend_score <= 100
    assert result.indicators.close == float(candles[-1].close)


@pytest.mark.asyncio
async def test_candle_upsert_does_not_duplicate_on_conflict(db_session, seeded_market):
    """Sanity check on the (market_id, timeframe, ts) unique constraint itself."""
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add(
        Candle(
            market_id=seeded_market.id,
            timeframe="1h",
            ts=ts,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("10"),
        )
    )
    await db_session.commit()

    adapter = MockExchangeAdapter()
    result = await sync_candles(
        db_session,
        market_id=seeded_market.id,
        symbol=seeded_market.symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=ts,
        until=ts + timedelta(hours=1),
    )
    # The manually-inserted bar already covers the only expected timestamp.
    assert result.inserted_count == 0
    assert result.adapter_called is False
