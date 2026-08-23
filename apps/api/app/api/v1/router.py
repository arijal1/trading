from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health, market_data, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(market_data.router)
