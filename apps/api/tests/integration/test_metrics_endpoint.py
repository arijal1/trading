from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.metrics import render_latest
from app.db.models.core import Account, Asset, Exchange, Market, User
from app.schemas.exchange import OrderSide, OrderType
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.execution.order_manager import OrderManager


@pytest.mark.asyncio
async def test_metrics_endpoint_is_prometheus_text_format(client: AsyncClient):
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "# HELP orders_submitted_total" in body
    assert "# TYPE paper_ticks_total counter" in body


@pytest.mark.asyncio
async def test_order_submission_increments_orders_submitted_total(db_session):
    label = 'orders_submitted_total{side="BUY",type="MARKET"}'
    before = _extract_labeled_counter(render_latest().decode(), label)

    user = User(email="metrics@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    account = Account(
        user_id=user.id, name="Metrics", mode="paper", starting_equity=Decimal("1000")
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
    await db_session.refresh(base)

    order_manager = OrderManager(MockExchangeAdapter())
    await order_manager.submit_order(
        db_session,
        account_id=account.id,
        asset_id=base.id,
        symbol=market.symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )

    after = _extract_labeled_counter(render_latest().decode(), label)
    assert after == before + 1


@pytest.mark.asyncio
async def test_emergency_stop_sets_gauge_to_one_and_resume_clears_it(client: AsyncClient):
    response = await client.post(
        "/api/v1/trading/emergency-stop", json={"reason": "metrics test", "actor": "tester"}
    )
    assert response.status_code == 200
    metrics_body = (await client.get("/metrics")).text
    assert _extract_gauge(metrics_body, "emergency_stop_active") == 1.0

    response = await client.post(
        "/api/v1/trading/resume", json={"reason": "metrics test done", "actor": "tester"}
    )
    assert response.status_code == 200
    metrics_body = (await client.get("/metrics")).text
    assert _extract_gauge(metrics_body, "emergency_stop_active") == 0.0


def _extract_gauge(body: str, name: str) -> float:
    for line in body.splitlines():
        if line.startswith(name + " "):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"gauge {name} not found")


def _extract_labeled_counter(body: str, label: str) -> float:
    for line in body.splitlines():
        if line.startswith(label + " "):
            return float(line.rsplit(" ", 1)[1])
    return 0.0
