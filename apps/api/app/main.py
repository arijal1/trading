from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.metrics import router as metrics_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "startup",
        trading_mode=settings.TRADING_MODE.value,
        live_trading_allowed=settings.live_trading_allowed(),
    )
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(metrics_router)
    return app


app = create_app()
