"""Authentication endpoints (brief Section 46).

`POST /auth/register` is admin-gated once `AUTH_REQUIRED` is on, which
creates a bootstrap problem: the first admin cannot be created through
the API of a system that requires an admin to create users. That is
deliberate — the first admin is provisioned out-of-band via the
`create-admin` CLI (`app/cli.py`), so an internet-reachable deployment
never has a window where anyone can self-register as admin. Documented in
`docs/AUTH.md`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, require_admin
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.audit import AuditLog
from app.db.models.core import User
from app.db.session import get_db
from app.schemas.auth import (
    AuthConfigResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(tags=["auth"])
logger = get_logger(__name__)


@router.get("/auth/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    """Public: tells a client whether it needs to log in before anything else.

    Unauthenticated on purpose. The alternative — having the dashboard
    probe a protected endpoint and infer the posture from a 401 — works
    but conflates "auth is on" with "your token expired" and with "the
    API is down", which produces a login screen at exactly the moments it
    is least helpful.
    """
    return AuthConfigResponse(auth_required=get_settings().AUTH_REQUIRED)


@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # One indistinguishable failure for "no such user", "wrong password",
    # and "inactive user": telling them apart lets an attacker enumerate
    # which email addresses have accounts.
    if user is None or not verify_password(payload.password, user.hashed_password):
        logger.warning("login_failed", email=payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )
    if not user.is_active:
        logger.warning("login_failed_inactive", email=payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )

    settings = get_settings()
    token = create_access_token(user_id=user.id, email=user.email, role=user.role)
    logger.info("login_succeeded", user_id=str(user.id), role=user.role)
    return TokenResponse(
        access_token=token, expires_in_minutes=settings.JWT_EXPIRE_MINUTES
    )


@router.post("/auth/register", response_model=UserResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    actor: CurrentUser = Depends(require_admin),
) -> UserResponse:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    if payload.role not in ("user", "admin"):
        raise HTTPException(status_code=422, detail="role must be 'user' or 'admin'")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.flush()
    db.add(
        AuditLog(
            actor=actor.email,
            action="register_user",
            entity_type="user",
            entity_id=str(user.id),
            after={"email": user.email, "role": user.role},
        )
    )
    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=user.id, email=user.email, role=user.role, is_active=user.is_active
    )


@router.get("/auth/me", response_model=UserResponse)
async def me(user: CurrentUser = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, role=user.role, is_active=True)
