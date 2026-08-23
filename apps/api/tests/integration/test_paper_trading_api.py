from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Account, Asset, Exchange, Market, User


@pytest_asyncio.fixture
async def seeded_account(db_session: AsyncSession):
    user = User(email="trader@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    account = Account(
        user_id=user.id, name="Paper", mode="paper", starting_equity=Decimal("10000")
    )
    exchange = Exchange(name="Mock Exchange", adapter_type="mock")
    base = Asset(symbol="BTC")
    quote = Asset(symbol="USD")
    db_session.add_all([account, exchange, base, quote])
    await db_session.flush()

    market = Market(
        exchange_id=exchange.id, base_asset_id=base.id, quote_asset_id=quote.id, symbol="BTC/USD"
    )
    db_session.add(market)
    await db_session.commit()
    await db_session.refresh(account)
    await db_session.refresh(market)
    return {"account": account, "market": market}


@pytest.mark.asyncio
async def test_list_accounts_includes_seeded_account(client: AsyncClient, seeded_account):
    account = seeded_account["account"]
    response = await client.get("/api/v1/accounts")
    assert response.status_code == 200
    body = response.json()
    assert any(a["id"] == str(account.id) for a in body)


@pytest.mark.asyncio
async def test_get_account_404_for_unknown_id(client: AsyncClient):
    response = await client.get("/api/v1/accounts/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_account_returns_expected_fields(client: AsyncClient, seeded_account):
    account = seeded_account["account"]
    response = await client.get(f"/api/v1/accounts/{account.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(account.id)
    assert body["mode"] == "paper"
    assert Decimal(body["starting_equity"]) == Decimal("10000")


@pytest.mark.asyncio
async def test_portfolio_matches_starting_equity_with_no_activity(
    client: AsyncClient, seeded_account
):
    account = seeded_account["account"]
    response = await client.get(f"/api/v1/accounts/{account.id}/portfolio")
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["equity"]) == Decimal("10000")
    assert Decimal(body["cash"]) == Decimal("10000")
    assert body["open_position_count"] == 0


@pytest.mark.asyncio
async def test_positions_orders_trades_empty_before_any_activity(
    client: AsyncClient, seeded_account
):
    account = seeded_account["account"]
    for path in ("positions", "orders", "trades"):
        response = await client.get(f"/api/v1/accounts/{account.id}/{path}")
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.asyncio
async def test_paper_tick_404_for_unknown_market(client: AsyncClient, seeded_account):
    account = seeded_account["account"]
    response = await client.post(
        f"/api/v1/accounts/{account.id}/paper/tick",
        json={"market_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_paper_tick_422_for_non_paper_account(
    client: AsyncClient, seeded_account, db_session
):
    account, market = seeded_account["account"], seeded_account["market"]
    account.mode = "live"
    db_session.add(account)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/accounts/{account.id}/paper/tick", json={"market_id": str(market.id)}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_paper_tick_insufficient_data_before_sync(client: AsyncClient, seeded_account):
    account, market = seeded_account["account"], seeded_account["market"]
    response = await client.post(
        f"/api/v1/accounts/{account.id}/paper/tick", json={"market_id": str(market.id)}
    )
    assert response.status_code == 200
    assert response.json()["result"]["action"] == "INSUFFICIENT_DATA"


@pytest.mark.asyncio
async def test_paper_tick_after_sync_runs_a_decision_cycle(client: AsyncClient, seeded_account):
    account, market = seeded_account["account"], seeded_account["market"]
    sync_response = await client.post(
        f"/api/v1/markets/{market.id}/sync", params={"timeframe": "1h", "hours": 60}
    )
    assert sync_response.status_code == 200

    response = await client.post(
        f"/api/v1/accounts/{account.id}/paper/tick", json={"market_id": str(market.id)}
    )
    assert response.status_code == 200
    action = response.json()["result"]["action"]
    assert action in (
        "OPENED",
        "HOLD",
        "NO_SIGNAL",
        "SKIPPED_RISK",
        "SKIPPED_SIZE",
    )

    # Whatever happened, a portfolio snapshot must have been recorded.
    portfolio_response = await client.get(f"/api/v1/accounts/{account.id}/portfolio")
    assert portfolio_response.status_code == 200

    if action == "OPENED":
        positions_response = await client.get(f"/api/v1/accounts/{account.id}/positions")
        assert len(positions_response.json()) == 1
        orders_response = await client.get(f"/api/v1/accounts/{account.id}/orders")
        assert len(orders_response.json()) == 1
        trades_response = await client.get(f"/api/v1/accounts/{account.id}/trades")
        assert len(trades_response.json()) == 1
