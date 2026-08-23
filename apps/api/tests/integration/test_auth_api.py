from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api import deps
from app.api.v1.endpoints import auth as auth_endpoint
from app.core import security
from app.core.config import Settings
from app.core.security import hash_password
from app.db.models.core import User

SECRET = "integration-test-signing-secret-at-least-32-bytes-long"
PASSWORD = "a-sufficiently-long-password"


def _settings(auth_required: bool) -> Settings:
    return Settings(JWT_SECRET_KEY=SECRET, AUTH_REQUIRED=auth_required, JWT_EXPIRE_MINUTES=60)


@pytest.fixture
def auth_on(monkeypatch):
    s = _settings(True)
    monkeypatch.setattr(deps, "get_settings", lambda: s)
    monkeypatch.setattr(security, "get_settings", lambda: s)
    monkeypatch.setattr(auth_endpoint, "get_settings", lambda: s)
    return s


@pytest.fixture
def auth_off(monkeypatch):
    s = _settings(False)
    monkeypatch.setattr(deps, "get_settings", lambda: s)
    monkeypatch.setattr(security, "get_settings", lambda: s)
    monkeypatch.setattr(auth_endpoint, "get_settings", lambda: s)
    return s


@pytest_asyncio.fixture
async def users(db_session):
    admin = User(
        email="admin@example.com", hashed_password=hash_password(PASSWORD), role="admin"
    )
    plain = User(
        email="user@example.com", hashed_password=hash_password(PASSWORD), role="user"
    )
    disabled = User(
        email="disabled@example.com",
        hashed_password=hash_password(PASSWORD),
        role="admin",
        is_active=False,
    )
    db_session.add_all([admin, plain, disabled])
    await db_session.commit()
    for u in (admin, plain, disabled):
        await db_session.refresh(u)
    return {"admin": admin, "user": plain, "disabled": disabled}


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_login_succeeds_and_returns_a_token(client, users, auth_on):
    token = await _login(client, "admin@example.com")
    assert token


@pytest.mark.asyncio
async def test_login_with_wrong_password_is_rejected(client, users, auth_on):
    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unknown_and_wrong_password_are_indistinguishable(client, users, auth_on):
    """User enumeration defence: both must give the identical response."""
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-password"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


@pytest.mark.asyncio
async def test_inactive_user_cannot_log_in(client, users, auth_on):
    response = await client.post(
        "/api/v1/auth/login", json={"email": "disabled@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_emergency_stop_requires_a_token_when_auth_is_on(client, users, auth_on):
    response = await client.post(
        "/api/v1/trading/emergency-stop", json={"reason": "test", "actor": "tester"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_emergency_stop_requires_admin_role(client, users, auth_on):
    token = await _login(client, "user@example.com")
    response = await client.post(
        "/api/v1/trading/emergency-stop",
        json={"reason": "test", "actor": "tester"},
        headers=_bearer(token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_trip_the_kill_switch(client, users, auth_on):
    token = await _login(client, "admin@example.com")
    response = await client.post(
        "/api/v1/trading/emergency-stop",
        json={"reason": "test", "actor": "admin"},
        headers=_bearer(token),
    )
    assert response.status_code == 200
    assert response.json()["is_emergency_stopped"] is True


@pytest.mark.asyncio
async def test_garbage_token_is_rejected(client, users, auth_on):
    response = await client.post(
        "/api/v1/trading/emergency-stop",
        json={"reason": "test", "actor": "tester"},
        headers=_bearer("not-a-real-token"),
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_for_a_deactivated_user_stops_working_immediately(
    client, users, auth_on, db_session
):
    """A token issued before deactivation must not survive until expiry."""
    token = await _login(client, "admin@example.com")
    users["admin"].is_active = False
    db_session.add(users["admin"])
    await db_session.commit()

    response = await client.post(
        "/api/v1/trading/emergency-stop",
        json={"reason": "test", "actor": "admin"},
        headers=_bearer(token),
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_stays_open_when_auth_is_on(client, auth_on):
    """Liveness must never require a credential — an auth outage would
    otherwise look like a dead process to an orchestrator."""
    assert (await client.get("/api/v1/health")).status_code == 200


@pytest.mark.asyncio
async def test_metrics_stays_open_when_auth_is_on(client, auth_on):
    assert (await client.get("/metrics")).status_code == 200


@pytest.mark.asyncio
async def test_kill_switch_is_open_when_auth_is_disabled(client, auth_off):
    """The documented Phase 1-5 posture must be preserved exactly."""
    response = await client.post(
        "/api/v1/trading/emergency-stop", json={"reason": "test", "actor": "tester"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_register_requires_admin(client, users, auth_on):
    user_token = await _login(client, "user@example.com")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "another-long-password"},
        headers=_bearer(user_token),
    )
    assert response.status_code == 403

    admin_token = await _login(client, "admin@example.com")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "another-long-password"},
        headers=_bearer(admin_token),
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"


@pytest.mark.asyncio
async def test_register_rejects_short_passwords(client, users, auth_on):
    admin_token = await _login(client, "admin@example.com")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "password": "short"},
        headers=_bearer(admin_token),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(client, users, auth_on):
    admin_token = await _login(client, "admin@example.com")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "another-long-password"},
        headers=_bearer(admin_token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_response_never_contains_the_password_hash(client, users, auth_on):
    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
    )
    body = response.text
    assert "argon2" not in body
    assert users["admin"].hashed_password not in body
