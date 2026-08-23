from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.audit import Alert
from app.db.models.core import Account, User
from app.schemas.notification import NotificationMessage, NotificationSeverity
from app.services.notifications.base import NotificationChannel
from app.services.notifications.log_channel import LogNotificationChannel
from app.services.notifications.service import NotificationService


class _FailingChannel(NotificationChannel):
    name = "failing"

    async def send(self, message):
        from app.schemas.notification import ChannelResult

        return ChannelResult(delivered=False, error="simulated failure")


@pytest_asyncio.fixture
async def seeded_account(db_session):
    user = User(email="trader@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    account = Account(
        user_id=user.id, name="Paper", mode="paper", starting_equity=Decimal("10000")
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest.mark.asyncio
async def test_notify_persists_one_alert_per_channel(db_session, seeded_account):
    account_id = seeded_account.id
    service = NotificationService([LogNotificationChannel(), _FailingChannel()])
    message = NotificationMessage(
        event_type="POSITION_OPENED",
        severity=NotificationSeverity.INFO,
        title="Opened",
        body="Bought 1 BTC",
        account_id=account_id,
        payload={"quantity": "1"},
    )

    alerts = await service.notify(db_session, message)
    assert len(alerts) == 2

    stored = (
        (await db_session.execute(select(Alert).where(Alert.account_id == account_id)))
        .scalars()
        .all()
    )
    assert len(stored) == 2

    by_channel = {a.channel: a for a in stored}
    assert by_channel["log"].payload["delivered"] is True
    assert by_channel["failing"].payload["delivered"] is False
    assert by_channel["failing"].payload["error"] == "simulated failure"
    assert by_channel["log"].payload["quantity"] == "1"
    assert by_channel["log"].type == "POSITION_OPENED"


@pytest.mark.asyncio
async def test_notify_with_no_account_id_persists_account_null(db_session):
    service = NotificationService([LogNotificationChannel()])
    message = NotificationMessage(
        event_type="SYSTEM_EVENT",
        severity=NotificationSeverity.WARNING,
        title="Something",
        body="happened",
    )
    alerts = await service.notify(db_session, message)
    assert alerts[0].account_id is None
