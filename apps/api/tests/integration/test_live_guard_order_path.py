from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import Settings, TradingMode
from app.db.models.core import Account, Asset, Exchange, User
from app.db.models.trading import Order
from app.schemas.exchange import OrderSide, OrderType
from app.schemas.live_trading import GuardCheck
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.execution.live_guard import LiveTradingGuard, LiveTradingRefusedError
from app.services.execution.order_manager import OrderManager


@pytest_asyncio.fixture
async def seeded(db_session):
    user = User(email="live@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    live_account = Account(
        user_id=user.id, name="Live", mode="live", starting_equity=Decimal("10000")
    )
    paper_account = Account(
        user_id=user.id, name="Paper", mode="paper", starting_equity=Decimal("10000")
    )
    exchange = Exchange(
        name="Mock Exchange",
        adapter_type="mock",
        withdrawals_disabled=True,
        api_key_encrypted="cipher",
        api_secret_encrypted="cipher",
    )
    asset = Asset(symbol="BTC")
    db_session.add_all([live_account, paper_account, exchange, asset])
    await db_session.commit()
    for row in (live_account, paper_account, exchange, asset):
        await db_session.refresh(row)
    return {
        "live": live_account,
        "paper": paper_account,
        "exchange": exchange,
        "asset": asset,
    }


def _live_settings(**overrides) -> Settings:
    base = {
        "TRADING_MODE": TradingMode.LIVE,
        "LIVE_TRADING": True,
        "TRADING_CONFIRMATION": True,
        "VALID_EXCHANGE_CREDENTIALS": True,
        "RISK_LIMITS_VALID": True,
        "EMERGENCY_STOP_AVAILABLE": True,
        "DISABLE_WITHDRAWALS": True,
        "MAX_LIVE_CAPITAL": 1_000_000.0,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_live_order_is_refused_under_default_config(db_session, seeded, monkeypatch):
    """A live-mode account under the shipped default settings must not be
    able to place an order, and must not leave an order row behind."""
    monkeypatch.setattr(
        "app.services.execution.live_guard.get_settings", lambda: Settings()
    )
    monkeypatch.setattr(
        "app.services.execution.order_manager.is_live_order", lambda account: True
    )
    manager = OrderManager(MockExchangeAdapter(), guard=LiveTradingGuard(Settings()))

    with pytest.raises(LiveTradingRefusedError) as excinfo:
        await manager.submit_order(
            db_session,
            account_id=seeded["live"].id,
            asset_id=seeded["asset"].id,
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            exchange=seeded["exchange"],
        )

    assert GuardCheck.TRADING_MODE_IS_LIVE in excinfo.value.decision.failed_checks
    orders = (await db_session.execute(select(Order))).scalars().all()
    assert orders == [], "a refused live order must not create an order row"


@pytest.mark.asyncio
async def test_paper_order_is_unaffected_by_the_guard(db_session, seeded):
    """The guard governs real money only — paper trading must keep working
    exactly as before."""
    manager = OrderManager(MockExchangeAdapter())
    order = await manager.submit_order(
        db_session,
        account_id=seeded["paper"].id,
        asset_id=seeded["asset"].id,
        symbol="BTC/USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    assert order.status == "FILLED"


@pytest.mark.asyncio
async def test_live_order_proceeds_when_every_guardrail_is_satisfied(
    db_session, seeded, monkeypatch
):
    """The guard must not be unconditionally closed — a fully-configured,
    deliberately-enabled live setup has to be able to trade, otherwise the
    control is untestable in the direction that matters."""
    settings = _live_settings()
    monkeypatch.setattr("app.services.execution.live_guard.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.services.execution.order_manager.is_live_order", lambda account: True
    )
    manager = OrderManager(MockExchangeAdapter(), guard=LiveTradingGuard(settings))

    order = await manager.submit_order(
        db_session,
        account_id=seeded["live"].id,
        asset_id=seeded["asset"].id,
        symbol="BTC/USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        exchange=seeded["exchange"],
    )
    assert order.status == "FILLED"


@pytest.mark.asyncio
async def test_emergency_stop_blocks_an_otherwise_valid_live_order(
    db_session, seeded, monkeypatch
):
    from app.services import system_state as system_state_service

    await system_state_service.emergency_stop(db_session, reason="test", actor="tester")

    settings = _live_settings()
    monkeypatch.setattr("app.services.execution.live_guard.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.services.execution.order_manager.is_live_order", lambda account: True
    )
    manager = OrderManager(MockExchangeAdapter(), guard=LiveTradingGuard(settings))

    with pytest.raises(LiveTradingRefusedError) as excinfo:
        await manager.submit_order(
            db_session,
            account_id=seeded["live"].id,
            asset_id=seeded["asset"].id,
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            exchange=seeded["exchange"],
        )
    assert GuardCheck.NOT_EMERGENCY_STOPPED in excinfo.value.decision.failed_checks


@pytest.mark.asyncio
async def test_unknown_account_is_refused_rather_than_assumed_paper(db_session, monkeypatch):
    import uuid as _uuid

    manager = OrderManager(MockExchangeAdapter())
    with pytest.raises(
        LiveTradingRefusedError, match="cannot establish whether this order is live"
    ):
        await manager.submit_order(
            db_session,
            account_id=_uuid.uuid4(),
            asset_id=_uuid.uuid4(),
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
