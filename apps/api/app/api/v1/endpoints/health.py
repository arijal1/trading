from __future__ import annotations

from fastapi import APIRouter

from app.schemas.system import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe. No dependency on DB/Redis — must always return fast."""
    return HealthResponse(status="ok")
