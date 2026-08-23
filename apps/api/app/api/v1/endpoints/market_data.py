from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.core import Asset, Candle, Exchange, Market
from app.db.session import get_db
from app.schemas.exchange import TIMEFRAME_SECONDS, Timeframe
from app.schemas.market_data import (
    AssetResponse,
    CandleResponse,
    MarketResponse,
    SyncCandlesResponse,
)
from app.schemas.technical_analysis import TechnicalAnalysisResult
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.market_data.engine import align_to_interval, sync_candles
from app.services.technical_analysis.engine import (
    MIN_BARS_REQUIRED,
    InsufficientDataError,
    TechnicalAnalysisEngine,
    candles_to_dataframe,
)

router = APIRouter(tags=["market-data"])

# Phase 2 ships only the mock adapter (brief Section 4: no exchange has
# been selected, and reverse-engineering one to fake support is
# explicitly disallowed). Real adapters register here once added.
_adapter = MockExchangeAdapter()


@router.get("/assets", response_model=list[AssetResponse])
async def list_assets(db: AsyncSession = Depends(get_db)) -> list[AssetResponse]:
    result = await db.execute(select(Asset).order_by(Asset.symbol))
    return [
        AssetResponse(
            id=a.id,
            symbol=a.symbol,
            chain=a.chain,
            contract_address=a.contract_address,
            risk_score=a.risk_score,
        )
        for a in result.scalars()
    ]


@router.get("/markets", response_model=list[MarketResponse])
async def list_markets(db: AsyncSession = Depends(get_db)) -> list[MarketResponse]:
    base_asset = aliased(Asset)
    quote_asset = aliased(Asset)
    stmt = (
        select(Market, Exchange.name, base_asset.symbol, quote_asset.symbol)
        .join(Exchange, Market.exchange_id == Exchange.id)
        .join(base_asset, Market.base_asset_id == base_asset.id)
        .join(quote_asset, Market.quote_asset_id == quote_asset.id)
        .order_by(Market.symbol)
    )
    rows = await db.execute(stmt)
    return [
        MarketResponse(
            id=market.id,
            exchange_id=market.exchange_id,
            exchange_name=exchange_name,
            symbol=market.symbol,
            base_asset_symbol=base_symbol,
            quote_asset_symbol=quote_symbol,
        )
        for market, exchange_name, base_symbol, quote_symbol in rows
    ]


async def _get_market_or_404(db: AsyncSession, market_id: uuid.UUID) -> Market:
    market = await db.get(Market, market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="market not found")
    return market


@router.get("/markets/{market_id}/candles", response_model=list[CandleResponse])
async def get_candles(
    market_id: uuid.UUID,
    timeframe: Timeframe = Timeframe.H1,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[CandleResponse]:
    await _get_market_or_404(db, market_id)
    limit = max(1, min(limit, 1000))
    result = await db.execute(
        select(Candle)
        .where(Candle.market_id == market_id, Candle.timeframe == timeframe.value)
        .order_by(Candle.ts.desc())
        .limit(limit)
    )
    candles = list(result.scalars())
    candles.reverse()
    return [
        CandleResponse(
            ts=c.ts, open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume
        )
        for c in candles
    ]


@router.post("/markets/{market_id}/sync", response_model=SyncCandlesResponse)
async def sync_market_candles(
    market_id: uuid.UUID,
    timeframe: Timeframe = Timeframe.H1,
    hours: int = 24,
    db: AsyncSession = Depends(get_db),
) -> SyncCandlesResponse:
    market = await _get_market_or_404(db, market_id)
    hours = max(1, min(hours, 24 * 30))
    # Align to the last fully-closed interval boundary: never sync a
    # still-forming candle, since it would be written once and never
    # revisited to pick up its final close.
    until = align_to_interval(datetime.now(UTC), TIMEFRAME_SECONDS[timeframe])
    since = until - timedelta(hours=hours)

    result = await sync_candles(
        db,
        market_id=market.id,
        symbol=market.symbol,
        timeframe=timeframe,
        adapter=_adapter,
        since=since,
        until=until,
    )
    return SyncCandlesResponse(
        requested_count=result.requested_count,
        already_stored_count=result.already_stored_count,
        fetched_count=result.fetched_count,
        inserted_count=result.inserted_count,
        gap_count=len(result.gap_timestamps),
        adapter_called=result.adapter_called,
    )


@router.get("/markets/{market_id}/technical-analysis", response_model=TechnicalAnalysisResult)
async def get_technical_analysis(
    market_id: uuid.UUID,
    timeframe: Timeframe = Timeframe.H1,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
) -> TechnicalAnalysisResult:
    market = await _get_market_or_404(db, market_id)
    limit = max(MIN_BARS_REQUIRED, min(limit, 1000))
    result = await db.execute(
        select(Candle)
        .where(Candle.market_id == market_id, Candle.timeframe == timeframe.value)
        .order_by(Candle.ts.desc())
        .limit(limit)
    )
    candles = list(result.scalars())
    candles.reverse()

    if len(candles) < MIN_BARS_REQUIRED:
        raise HTTPException(
            status_code=422,
            detail=(
                f"insufficient candle history for technical analysis: "
                f"need at least {MIN_BARS_REQUIRED} bars, have {len(candles)}. "
                f"Call POST /markets/{market_id}/sync first."
            ),
        )

    df = candles_to_dataframe(candles)
    engine = TechnicalAnalysisEngine()
    try:
        return engine.analyze(df, symbol=market.symbol, timeframe=timeframe.value)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
