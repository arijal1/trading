from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import backtests, health, market_data, paper_trading, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(market_data.router)
api_router.include_router(backtests.router)
api_router.include_router(paper_trading.router)
