from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import security
from app.core.config import Settings, get_settings

SECRET = "test-signing-secret-not-a-real-one-padded-to-32-plus-bytes"


@pytest.fixture
def with_secret(monkeypatch):
    settings = Settings(JWT_SECRET_KEY=SECRET, JWT_EXPIRE_MINUTES=60)
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    return settings


def test_password_round_trip():
    hashed = security.hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert security.verify_password("correct horse battery staple", hashed) is True
    assert security.verify_password("wrong password", hashed) is False


def test_same_password_hashes_differently():
    """Argon2 salts per-hash: identical passwords must not produce identical
    hashes, or the hash file leaks which users share a password."""
    a = security.hash_password("same-password")
    b = security.hash_password("same-password")
    assert a != b
    assert security.verify_password("same-password", a)
    assert security.verify_password("same-password", b)


def test_malformed_stored_hash_denies_rather_than_raising():
    assert security.verify_password("anything", "not-a-valid-argon2-hash") is False
    assert security.verify_password("anything", "") is False


def test_token_round_trip(with_secret):
    user_id = uuid.uuid4()
    token = security.create_access_token(user_id=user_id, email="a@b.c", role="admin")
    payload = security.decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["email"] == "a@b.c"
    assert payload["role"] == "admin"


def test_expired_token_is_rejected(with_secret, monkeypatch):
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "admin",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError, match="expired"):
        security.decode_access_token(expired)


def test_token_signed_with_another_key_is_rejected(with_secret):
    other_key = "a-different-signing-secret-also-at-least-32-bytes-long"
    forged = jwt.encode({"sub": str(uuid.uuid4()), "role": "admin"}, other_key, "HS256")
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(forged)


def test_alg_none_token_is_rejected(with_secret):
    """The classic JWT forgery: an unsigned token claiming `alg: none`.
    Pinning `algorithms=` at decode time is what stops it."""
    forged = jwt.encode({"sub": str(uuid.uuid4()), "role": "admin"}, key="", algorithm="none")
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(forged)


def test_missing_secret_refuses_to_sign(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: Settings(JWT_SECRET_KEY=None))
    with pytest.raises(security.AuthNotConfiguredError, match="not set"):
        security.create_access_token(user_id=uuid.uuid4(), email="a@b.c", role="user")


def test_short_secret_is_refused(monkeypatch):
    """A short HMAC secret is brute-forceable offline from one token."""
    monkeypatch.setattr(security, "get_settings", lambda: Settings(JWT_SECRET_KEY="tooshort"))
    with pytest.raises(security.AuthNotConfiguredError, match="shorter than"):
        security.create_access_token(user_id=uuid.uuid4(), email="a@b.c", role="user")


def test_shipped_defaults_have_no_signing_key_and_auth_off():
    """A baked-in signing key would let anyone forge admin tokens."""
    settings = get_settings()
    assert settings.JWT_SECRET_KEY is None
    assert settings.AUTH_REQUIRED is False
