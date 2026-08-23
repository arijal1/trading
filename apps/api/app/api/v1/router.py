from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
