"""Password hashing and JWT issuance/verification (brief Section 46).

Argon2id for passwords (the current password-hashing competition winner,
and what OWASP recommends first) rather than bcrypt: it is memory-hard,
so GPU/ASIC cracking is far more expensive per guess.

`JWT_SECRET_KEY` has no default, for the same reason
`MASTER_ENCRYPTION_KEY` has none: a shipped default signing key is a
publicly-known signing key, and anyone could mint themselves an admin
token with it. An unset secret raises at the point of use.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()


class AuthNotConfiguredError(RuntimeError):
    """JWT_SECRET_KEY is unset."""


class InvalidTokenError(ValueError):
    """Token is expired, malformed, or not signed by us."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time-ish verification that never raises on a bad password.

    Returns False for a mismatch *and* for a malformed stored hash — a
    corrupt hash must not authenticate anyone, and must not 500 either.
    """
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


# RFC 7518 §3.2: an HMAC-SHA256 key should be at least as long as the
# hash output. A short secret is brute-forceable offline from a single
# captured token, which would let an attacker mint admin tokens.
MIN_SECRET_BYTES = 32


def _secret() -> str:
    secret = get_settings().JWT_SECRET_KEY
    if not secret:
        raise AuthNotConfiguredError(
            "JWT_SECRET_KEY is not set — refusing to sign or verify tokens with a "
            "default key. Generate one with: python -c "
            "'import secrets; print(secrets.token_urlsafe(48))'"
        )
    if len(secret.encode()) < MIN_SECRET_BYTES:
        raise AuthNotConfiguredError(
            f"JWT_SECRET_KEY is shorter than {MIN_SECRET_BYTES} bytes. A short HMAC "
            "secret can be brute-forced offline from one captured token, which would "
            "let an attacker mint admin tokens. Generate one with: python -c "
            "'import secrets; print(secrets.token_urlsafe(48))'"
        )
    return secret


def create_access_token(*, user_id: uuid.UUID, email: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _secret(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        # `algorithms` is pinned to the configured algorithm rather than
        # accepting whatever the token's own header claims — otherwise a
        # forged `alg: none` (or an HMAC/RSA confusion) token would verify.
        return jwt.decode(token, _secret(), algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("token is invalid") from exc
