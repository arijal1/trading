from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1.endpoints import (
    auth,
    backtests,
    health,
    market_data,
    paper_trading,
    system,
)

api_router = APIRouter()

# Public, deliberately: `/health` is what a load balancer or `docker
# healthcheck` calls before any credential exists, and `/auth/*` is how a
# credential is obtained in the first place. Gating either would be a
# bootstrap deadlock.
api_router.include_router(auth.router)
api_router.include_router(health.router)

# Everything else requires an identity.
#
# Until now only *mutations* were gated (`require_admin` on the kill
# switch, credentials, and so on) while every read — portfolio equity,
# open positions, order history, system state — answered anyone who
# asked, even with AUTH_REQUIRED=true. That is fine on a trusted LAN and
# wrong the moment the API is reachable from the internet: an attacker
# who cannot *touch* anything can still read the entire trading book,
# which is most of what there is to protect here.
#
# `get_current_user` is a no-op when AUTH_REQUIRED is false — it returns
# the ANONYMOUS sentinel — so this changes nothing for existing local
# setups, tests, or the dashboard's default posture. It only closes the
# hole for deployments that have actually turned auth on.
_authenticated = [Depends(get_current_user)]
api_router.include_router(system.router, dependencies=_authenticated)
api_router.include_router(market_data.router, dependencies=_authenticated)
api_router.include_router(backtests.router, dependencies=_authenticated)
api_router.include_router(paper_trading.router, dependencies=_authenticated)
