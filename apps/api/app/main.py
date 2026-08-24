from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        # No cookies are used: the dashboard holds a bearer token and
        # sends it in the Authorization header, so credentialed CORS is
        # not needed and leaving it off keeps the allowlist strict.
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        # "Authorization" is required, not optional: the browser sends a
        # preflight for any request carrying it, and a preflight that does
        # not list the header is rejected — which would make every
        # authenticated dashboard call fail with an opaque CORS error
        # rather than a 401.
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(metrics_router)
    return app


app = create_app()
