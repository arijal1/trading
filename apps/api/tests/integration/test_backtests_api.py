from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Asset, Exchange, Market


@pytest_asyncio.fixture
async def seeded_market(db_session: AsyncSession) -> Market:
    exchange = Exchange(name="Mock Exchange", adapter_type="mock")
    base = Asset(symbol="BTC")
    quote = Asset(symbol="USD")
    db_session.add_all([exchange, base, quote])
    await db_session.flush()

    market = Market(
        exchange_id=exchange.id,
        base_asset_id=base.id,
        quote_asset_id=quote.id,
        symbol="BTC/USD",
    )
    db_session.add(market)
    await db_session.commit()
    await db_session.refresh(market)
    return market


@pytest.mark.asyncio
async def test_backtest_404_for_unknown_market(client: AsyncClient):
    response = await client.post(
        "/api/v1/backtests",
        json={"market_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_backtest_422_when_insufficient_candle_history(
    client: AsyncClient, seeded_market
):
    await client.post(
        f"/api/v1/markets/{seeded_market.id}/sync", params={"timeframe": "1h", "hours": 10}
    )
    response = await client.post(
        "/api/v1/backtests", json={"market_id": str(seeded_market.id), "candle_limit": 50}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_run_and_fetch_backtest(client: AsyncClient, seeded_market):
    sync_response = await client.post(
        f"/api/v1/markets/{seeded_market.id}/sync", params={"timeframe": "1h", "hours": 250}
    )
    assert sync_response.status_code == 200
    assert sync_response.json()["inserted_count"] == 250

    run_response = await client.post(
        "/api/v1/backtests",
        json={"market_id": str(seeded_market.id), "timeframe": "1h", "candle_limit": 250},
    )
    assert run_response.status_code == 200
    run_body = run_response.json()

    assert run_body["status"] == "COMPLETED"
    assert run_body["result"]["symbol"] == "BTC/USD"
    assert run_body["result"]["bar_count"] == 250
    assert run_body["result"]["starting_equity"] == "10000"
    assert 0 <= run_body["result"]["metrics"]["win_rate"] <= 1

    backtest_id = run_body["id"]
    get_response = await client.get(f"/api/v1/backtests/{backtest_id}")
    assert get_response.status_code == 200
    get_body = get_response.json()
    assert get_body["id"] == backtest_id
    assert get_body["result"]["bar_count"] == 250
    assert get_body["result"]["metrics"] == run_body["result"]["metrics"]


@pytest.mark.asyncio
async def test_get_backtest_404_for_unknown_id(client: AsyncClient):
    response = await client.get("/api/v1/backtests/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
