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
async def test_list_assets(client: AsyncClient, seeded_market):
    response = await client.get("/api/v1/assets")
    assert response.status_code == 200
    symbols = {a["symbol"] for a in response.json()}
    assert {"BTC", "USD"} <= symbols


@pytest.mark.asyncio
async def test_list_markets(client: AsyncClient, seeded_market):
    response = await client.get("/api/v1/markets")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "BTC/USD"
    assert body[0]["base_asset_symbol"] == "BTC"
    assert body[0]["quote_asset_symbol"] == "USD"


@pytest.mark.asyncio
async def test_candles_endpoint_404_for_unknown_market(client: AsyncClient):
    response = await client.get(
        "/api/v1/markets/00000000-0000-0000-0000-000000000000/candles"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_sync_then_fetch_candles_then_technical_analysis(
    client: AsyncClient, seeded_market
):
    sync_response = await client.post(
        f"/api/v1/markets/{seeded_market.id}/sync",
        params={"timeframe": "1h", "hours": 72},
    )
    assert sync_response.status_code == 200
    sync_body = sync_response.json()
    assert sync_body["inserted_count"] == 72
    assert sync_body["adapter_called"] is True

    candles_response = await client.get(
        f"/api/v1/markets/{seeded_market.id}/candles", params={"timeframe": "1h", "limit": 500}
    )
    assert candles_response.status_code == 200
    candles = candles_response.json()
    assert len(candles) == 72
    # ascending order
    assert candles[0]["ts"] < candles[-1]["ts"]

    ta_response = await client.get(
        f"/api/v1/markets/{seeded_market.id}/technical-analysis", params={"timeframe": "1h"}
    )
    assert ta_response.status_code == 200
    ta_body = ta_response.json()
    assert ta_body["symbol"] == "BTC/USD"
    assert ta_body["bar_count"] == 72
    assert 0 <= ta_body["trend_score"] <= 100


@pytest.mark.asyncio
async def test_technical_analysis_422_when_insufficient_history(
    client: AsyncClient, seeded_market
):
    await client.post(
        f"/api/v1/markets/{seeded_market.id}/sync",
        params={"timeframe": "1h", "hours": 5},
    )
    response = await client.get(
        f"/api/v1/markets/{seeded_market.id}/technical-analysis", params={"timeframe": "1h"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_second_sync_call_is_a_no_op_cache_hit(client: AsyncClient, seeded_market):
    first = await client.post(
        f"/api/v1/markets/{seeded_market.id}/sync", params={"timeframe": "1h", "hours": 24}
    )
    assert first.json()["inserted_count"] == 24

    second = await client.post(
        f"/api/v1/markets/{seeded_market.id}/sync", params={"timeframe": "1h", "hours": 24}
    )
    assert second.json()["inserted_count"] == 0
    assert second.json()["adapter_called"] is False
