"""Backtest endpoints (brief Section 27, Section 36).

Runs synchronously in the request. There is no background worker queue
yet (Celery is planned per docs/ARCHITECTURE.md's tech-stack table but
not wired up until a later phase), so a large `candle_limit` will hold
the HTTP connection open for the backtest's full duration — acceptable
for now, worth revisiting once a worker exists.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.backtest import Backtest
from app.db.models.core import Candle, Market
from app.db.session import get_db
from app.schemas.backtest import BacktestResult
from app.schemas.backtest_api import BacktestRecordResponse, BacktestRunRequest
from app.services.backtesting.engine import BacktestEngine
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.strategy.registry import get_or_create_composite_strategy
from app.services.technical_analysis.engine import MIN_BARS_REQUIRED

router = APIRouter(tags=["backtests"])

# Same Phase-2 scope note as market_data.py: only a mock adapter exists,
# used here only for its fee schedule (backtests fill against the
# candles' own OHLCV, never the adapter's synthetic price).
_adapter = MockExchangeAdapter()


@router.post("/backtests", response_model=BacktestRecordResponse)
async def run_backtest(
    request: BacktestRunRequest, db: AsyncSession = Depends(get_db)
) -> BacktestRecordResponse:
    market = await db.get(Market, request.market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="market not found")

    result = await db.execute(
        select(Candle)
        .where(Candle.market_id == market.id, Candle.timeframe == request.timeframe.value)
        .order_by(Candle.ts.desc())
        .limit(request.candle_limit)
    )
    candles = list(result.scalars())
    candles.reverse()

    if len(candles) < MIN_BARS_REQUIRED + 1:
        raise HTTPException(
            status_code=422,
            detail=(
                f"insufficient candle history to backtest: need at least "
                f"{MIN_BARS_REQUIRED + 1} bars, have {len(candles)}. "
                f"Call POST /markets/{market.id}/sync first."
            ),
        )

    fees = await _adapter.get_fees(market.symbol)
    engine = BacktestEngine(request.config, taker_fee_pct=fees.taker_fee_pct)
    backtest_result = engine.run(candles, symbol=market.symbol, timeframe=request.timeframe)

    strategy = await get_or_create_composite_strategy(db)
    record = Backtest(
        strategy_id=strategy.id,
        parameters=request.config.model_dump(mode="json"),
        date_range={"start": candles[0].ts.isoformat(), "end": candles[-1].ts.isoformat()},
        metrics=backtest_result.model_dump(mode="json"),
        status="COMPLETED",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return BacktestRecordResponse(
        id=record.id,
        strategy_id=record.strategy_id,
        status=record.status,
        date_range=record.date_range,
        result=backtest_result,
        created_at=record.created_at,
    )


@router.get("/backtests/{backtest_id}", response_model=BacktestRecordResponse)
async def get_backtest(
    backtest_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> BacktestRecordResponse:
    record = await db.get(Backtest, backtest_id)
    if record is None:
        raise HTTPException(status_code=404, detail="backtest not found")

    return BacktestRecordResponse(
        id=record.id,
        strategy_id=record.strategy_id,
        status=record.status,
        date_range=record.date_range,
        result=BacktestResult.model_validate(record.metrics),
        created_at=record.created_at,
    )
