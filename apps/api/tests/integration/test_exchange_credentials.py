from __future__ import annotations

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core import crypto
from app.core.config import Settings
from app.db.models.core import Exchange
from app.services.exchanges import credentials as creds

API_KEY = "ak-live-1234567890"
API_SECRET = "as-live-abcdefghij"


@pytest.fixture(autouse=True)
def with_key(monkeypatch):
    settings = Settings(MASTER_ENCRYPTION_KEY=Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache()
    yield
    crypto.reset_cache()


@pytest_asyncio.fixture
async def exchange(db_session):
    row = Exchange(name="Test Exchange", adapter_type="mock")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_store_and_load_round_trip(db_session, exchange):
    await creds.store_credentials(
        db_session,
        exchange=exchange,
        api_key=API_KEY,
        api_secret=API_SECRET,
        withdrawals_disabled=True,
    )
    loaded = await creds.load_credentials(db_session, exchange.id)
    assert loaded.api_key == API_KEY
    assert loaded.api_secret == API_SECRET


@pytest.mark.asyncio
async def test_plaintext_never_hits_the_database(db_session, exchange):
    await creds.store_credentials(
        db_session,
        exchange=exchange,
        api_key=API_KEY,
        api_secret=API_SECRET,
        withdrawals_disabled=True,
    )
    row = (
        await db_session.execute(select(Exchange).where(Exchange.id == exchange.id))
    ).scalar_one()
    assert API_KEY not in row.api_key_encrypted
    assert API_SECRET not in row.api_secret_encrypted
    # And nothing anywhere on the row carries the plaintext.
    assert API_KEY not in str(row.__dict__)
    assert API_SECRET not in str(row.__dict__)


@pytest.mark.asyncio
async def test_refuses_credentials_that_are_not_withdrawal_restricted(db_session, exchange):
    with pytest.raises(creds.WithdrawalPermissionError, match="withdrawal-restricted"):
        await creds.store_credentials(
            db_session,
            exchange=exchange,
            api_key=API_KEY,
            api_secret=API_SECRET,
            withdrawals_disabled=False,
        )
    await db_session.refresh(exchange)
    assert exchange.api_key_encrypted is None


@pytest.mark.asyncio
async def test_load_without_stored_credentials_raises(db_session, exchange):
    with pytest.raises(creds.CredentialsNotConfiguredError, match="no stored API credentials"):
        await creds.load_credentials(db_session, exchange.id)


@pytest.mark.asyncio
async def test_has_credentials_reflects_state(db_session, exchange):
    assert creds.has_credentials(exchange) is False
    await creds.store_credentials(
        db_session,
        exchange=exchange,
        api_key=API_KEY,
        api_secret=API_SECRET,
        withdrawals_disabled=True,
    )
    assert creds.has_credentials(exchange) is True


def test_credentials_repr_is_redacted():
    c = creds.ExchangeCredentials(api_key=API_KEY, api_secret=API_SECRET)
    assert API_KEY not in repr(c)
    assert API_SECRET not in repr(c)
    assert API_KEY not in str(c)
    assert API_KEY not in f"{c}"
