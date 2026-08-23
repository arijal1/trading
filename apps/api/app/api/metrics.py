"""Prometheus scrape endpoint, deliberately mounted outside `/api/v1`.

Prometheus scrape configs assume a fixed, unversioned `/metrics` path —
unlike every other route in this app, versioning it would just mean every
future Prometheus config has to be updated in lockstep with the API
version, for no benefit (metrics aren't a client-facing contract the way
the rest of `/api/v1` is).
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.metrics import CONTENT_TYPE_LATEST, render_latest

router = APIRouter(tags=["monitoring"])


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=render_latest(), media_type=CONTENT_TYPE_LATEST)
