"""Auth dependencies (brief Section 46: JWT + RBAC).

`AUTH_REQUIRED` gates whether these actually enforce. It defaults to
`False` so that the Phase 1-5 endpoints, the dashboard, and every
existing test keep working unchanged — turning auth on is a deliberate
deployment decision, documented in `docs/AUTH.md`.

That default is a real trade-off, stated plainly rather than hidden: with
`AUTH_REQUIRED=false` the API is unauthenticated, exactly as it was
through Phase 5. It must not be exposed beyond a trusted network in that
state. What Phase 6 adds is the *ability* to require auth, and the
guarantee that when it is required it is enforced on every state-changing
route — not a change to the default posture, which would have silently
broken the running dashboard.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_access_token
from app.db.models.core import User
from app.db.session import get_db


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# Sentinel identity used only when AUTH_REQUIRED is false, so downstream
# code can always rely on having a CurrentUser rather than branching on
# None and accidentally treating "no auth" as "admin".
ANONYMOUS = CurrentUser(
    id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
    email="anonymous@localhost",
    role="user",
)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> CurrentUser:
    settings = get_settings()
    token = _bearer_token(request)

    if not settings.AUTH_REQUIRED:
        # Still honour a valid token when one is supplied, so a caller can
        # act as a real (possibly admin) user even with auth off.
        if token:
            try:
                return await _user_from_token(db, token)
            except HTTPException:
                return ANONYMOUS
        return ANONYMOUS

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _user_from_token(db, token)


async def _user_from_token(db: AsyncSession, token: str) -> CurrentUser:
    try:
        payload = decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = uuid.UUID(payload.get("sub", ""))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token subject is not a user id"
        ) from exc

    # The DB is the authority on whether the user still exists and is
    # active — a token issued before an account was disabled must stop
    # working immediately, not at its natural expiry.
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user is inactive or unknown"
        )
    return CurrentUser(id=user.id, email=user.email, role=user.role)


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Gate the genuinely dangerous operations (kill switch, credentials)."""
    if not get_settings().AUTH_REQUIRED:
        return user
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin role required"
        )
    return user
