from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.audit import Alert
from app.db.models.core import Account, Asset, Candle, Exchange, Market, User
from app.db.models.trading import Order, Position
from app.schemas.exchange import Timeframe
from app.schemas.paper_trading import PaperTradingConfig, TickAction
from app.schemas.portfolio import RiskLimits
from app.schemas.profit import ProfitManagerConfig
from app.schemas.strategy import AggregateDecision, SignalDirection
from app.schemas.technical_analysis import IndicatorSnapshot, TechnicalAnalysisResult
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.execution.paper_trading_session import PaperTradingSession
from app.services.market_data.engine import sync_candles
from app.services.technical_analysis.engine import MIN_BARS_REQUIRED

# A fixed reference date rather than "now": MockExchangeAdapter's synthetic
# bars are a pure function of (symbol, timeframe, ts), so anchoring on a
# fixed date makes every scenario below exactly reproducible regardless of
# what day the suite runs on.
_SINCE = datetime(2024, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def seeded(db_session):
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
    await db_session.refresh(base)
    await db_session.refresh(market)
    return {"account": account, "asset": base, "market": market}


@pytest.mark.asyncio
async def test_insufficient_data_before_min_bars(db_session, seeded):
    adapter = MockExchangeAdapter()
    await sync_candles(
        db_session,
        market_id=seeded["market"].id,
        symbol=seeded["market"].symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=_SINCE,
        until=_SINCE + timedelta(hours=MIN_BARS_REQUIRED - 5),
    )
    session = PaperTradingSession(adapter)
    result = await session.run_tick(
        db_session, account=seeded["account"], market=seeded["market"], timeframe=Timeframe.H1
    )
    assert result.action == TickAction.INSUFFICIENT_DATA


@pytest.mark.asyncio
async def test_no_signal_when_atr_is_zero(db_session, seeded):
    # Perfectly flat candles bypass the adapter entirely: zero volatility
    # means ATR is exactly 0, which _consider_entry must refuse to size
    # a stop off rather than dividing by (or multiplying by) zero.
    ts = _SINCE
    for _ in range(MIN_BARS_REQUIRED + 5):
        db_session.add(
            Candle(
                market_id=seeded["market"].id,
                timeframe=Timeframe.H1.value,
                ts=ts,
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                volume=Decimal("1"),
            )
        )
        ts += timedelta(hours=1)
    await db_session.commit()

    session = PaperTradingSession(MockExchangeAdapter())
    result = await session.run_tick(
        db_session, account=seeded["account"], market=seeded["market"], timeframe=Timeframe.H1
    )
    assert result.action == TickAction.NO_SIGNAL


def _force_buy_decision(*_args, **_kwargs) -> AggregateDecision:
    return AggregateDecision(
        direction=SignalDirection.BUY,
        score=100.0,
        confidence=1.0,
        signals=[],
        reason_codes=["forced"],
    )


@pytest_asyncio.fixture
async def priced_market(db_session, seeded):
    # Synced up through real "now" (unlike `_SINCE`-anchored fixtures used
    # elsewhere in this file): MockExchangeAdapter fills market orders at
    # `get_market_price(now)`, so candles anchored to a fixed past date
    # would leave the latest close (what entry sizing reads) far from the
    # actual fill price — a real timing coupling that a live/paper system
    # avoids simply by always syncing recent candles before ticking.
    adapter = MockExchangeAdapter()
    until = datetime.now(UTC)
    await sync_candles(
        db_session,
        market_id=seeded["market"].id,
        symbol=seeded["market"].symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=until - timedelta(hours=MIN_BARS_REQUIRED + 10),
        until=until,
    )
    return seeded


@pytest.mark.asyncio
async def test_skipped_size_when_risk_pct_yields_dust_position(
    db_session, priced_market, monkeypatch
):
    session = PaperTradingSession(
        MockExchangeAdapter(), config=PaperTradingConfig(risk_pct=Decimal("0"))
    )
    monkeypatch.setattr(session.aggregator, "aggregate", _force_buy_decision)

    result = await session.run_tick(
        db_session,
        account=priced_market["account"],
        market=priced_market["market"],
        timeframe=Timeframe.H1,
    )
    assert result.action == TickAction.SKIPPED_SIZE

    open_positions = await db_session.execute(select(Position))
    assert open_positions.scalars().first() is None


@pytest.mark.asyncio
async def test_skipped_risk_when_max_open_positions_is_zero(db_session, priced_market, monkeypatch):
    config = PaperTradingConfig(risk_limits=RiskLimits(max_open_positions=0))
    session = PaperTradingSession(MockExchangeAdapter(), config=config)
    monkeypatch.setattr(session.aggregator, "aggregate", _force_buy_decision)

    result = await session.run_tick(
        db_session,
        account=priced_market["account"],
        market=priced_market["market"],
        timeframe=Timeframe.H1,
    )
    assert result.action == TickAction.SKIPPED_RISK
    assert "max_open_positions" in (result.detail or "")


@pytest.mark.asyncio
async def test_opens_a_position_on_forced_buy_signal(db_session, priced_market, monkeypatch):
    session = PaperTradingSession(MockExchangeAdapter())
    monkeypatch.setattr(session.aggregator, "aggregate", _force_buy_decision)

    result = await session.run_tick(
        db_session,
        account=priced_market["account"],
        market=priced_market["market"],
        timeframe=Timeframe.H1,
    )
    assert result.action == TickAction.OPENED
    assert result.position_id is not None

    position = await db_session.get(Position, result.position_id)
    assert position.status == "OPEN"
    assert position.quantity > 0
    assert position.stop_price is not None
    assert position.stop_price < position.avg_entry_price

    order = await db_session.get(Order, result.order_id)
    assert order.side == "BUY"
    assert order.status == "FILLED"

    # A second tick with a position already open must not open another one
    # for the same (account, asset) — it should go through the "manage the
    # open position" branch instead.
    second = await session.run_tick(
        db_session,
        account=priced_market["account"],
        market=priced_market["market"],
        timeframe=Timeframe.H1,
    )
    assert second.action in (
        TickAction.HOLD,
        TickAction.EXIT,
        TickAction.CAPITAL_RECOVERED,
    )


@pytest.mark.asyncio
async def test_opening_a_position_dispatches_a_notification(db_session, priced_market, monkeypatch):
    session = PaperTradingSession(MockExchangeAdapter())
    monkeypatch.setattr(session.aggregator, "aggregate", _force_buy_decision)

    result = await session.run_tick(
        db_session,
        account=priced_market["account"],
        market=priced_market["market"],
        timeframe=Timeframe.H1,
    )
    assert result.action == TickAction.OPENED

    alerts = (
        (
            await db_session.execute(
                select(Alert).where(Alert.account_id == priced_market["account"].id)
            )
        )
        .scalars()
        .all()
    )
    assert len(alerts) == 1
    assert alerts[0].type == "POSITION_OPENED"
    assert alerts[0].channel == "log"
    assert alerts[0].payload["delivered"] is True


@pytest.mark.asyncio
async def test_full_lifecycle_opens_and_exits_deterministically(db_session, seeded):
    """No forced signals here: a fixed price path (see `_SINCE`) drives the
    real strategy aggregator through an entire OPENED -> EXIT -> OPENED
    cycle, exactly reproducing the manual verification performed while
    building this orchestrator. Pinned to specific tick offsets so a
    regression in the strategy/exit wiring fails this test immediately
    rather than only showing up as "the numbers look different".
    """
    adapter = MockExchangeAdapter()
    market, account = seeded["market"], seeded["account"]
    seed_until = _SINCE + timedelta(hours=200)
    await sync_candles(
        db_session,
        market_id=market.id,
        symbol=market.symbol,
        timeframe=Timeframe.H1,
        adapter=adapter,
        since=_SINCE,
        until=seed_until,
    )

    session = PaperTradingSession(adapter)
    cursor = seed_until
    actions: list[str] = []
    for _ in range(150):
        next_cursor = cursor + timedelta(hours=1)
        await sync_candles(
            db_session,
            market_id=market.id,
            symbol=market.symbol,
            timeframe=Timeframe.H1,
            adapter=adapter,
            since=cursor,
            until=next_cursor,
        )
        cursor = next_cursor
        result = await session.run_tick(
            db_session, account=account, market=market, timeframe=Timeframe.H1
        )
        actions.append(result.action.value)

    assert actions[76] == "OPENED"
    assert actions[124] == "EXIT"
    assert actions[125] == "OPENED"
    assert actions.count("OPENED") == 2
    assert actions.count("EXIT") == 1

    positions = list((await db_session.execute(select(Position))).scalars())
    assert len(positions) == 2
    assert positions[0].status == "CLOSED"
    assert positions[1].status == "OPEN"


@pytest.mark.asyncio
async def test_capital_recovery_through_manage_open_position(db_session, seeded):
    """Exercises the CAPITAL_RECOVERED branch of `_manage_open_position`
    directly against a hand-built, deeply profitable position and a fake
    TA snapshot that won't itself trigger a signal-based exit — isolating
    the capital-recovery dispatch (order -> fill -> ProfitManager ->
    PROFIT_RUNNER) from whatever the strategy/exit engine happen to decide
    for any particular synthetic price path.
    """
    account, asset, market = seeded["account"], seeded["asset"], seeded["market"]
    entry_price = Decimal("100")
    position = Position(
        account_id=account.id,
        asset_id=asset.id,
        status="OPEN",
        initial_capital=entry_price * Decimal("10"),
        quantity=Decimal("10"),
        avg_entry_price=entry_price,
        stop_price=entry_price * Decimal("0.5"),  # far below current price; won't trigger
        take_profit_price=None,
        trailing_stop_pct=None,
        highest_price_since_entry=entry_price,
        max_hold_seconds=None,
    )
    db_session.add(position)
    await db_session.commit()
    await db_session.refresh(position)

    config = PaperTradingConfig(
        profit_manager=ProfitManagerConfig(
            min_profit_before_recovery=Decimal("0.10"),
            max_slippage_percent=Decimal("0"),
            min_position_value=Decimal("1"),
        )
    )
    session = PaperTradingSession(MockExchangeAdapter(), config=config)

    current_price = entry_price * Decimal("1.5")  # +50%, well past the 10% threshold
    fake_bar = Candle(
        market_id=market.id,
        timeframe=Timeframe.H1.value,
        ts=datetime.now(UTC),
        open=current_price,
        high=current_price,
        low=current_price,
        close=current_price,
        volume=Decimal("1"),
    )
    fake_ta = TechnicalAnalysisResult(
        symbol=market.symbol,
        timeframe=Timeframe.H1.value,
        bar_count=MIN_BARS_REQUIRED,
        trend_direction="UPTREND",
        trend_score=80.0,
        momentum_score=80.0,
        volume_score=50.0,
        volatility_score=50.0,
        breakout_score=50.0,
        reversal_probability=0.1,
        support_levels=[],
        resistance_levels=[],
        indicators=IndicatorSnapshot(close=float(current_price), volume=1.0),
    )

    result = await session._manage_open_position(
        db_session, account=account, market=market, position=position, ta=fake_ta, bar=fake_bar
    )

    assert result.action == TickAction.CAPITAL_RECOVERED
    assert result.position_id == position.id

    await db_session.refresh(position)
    assert position.status == "PROFIT_RUNNER"
    assert position.capital_recovered > 0
    assert 0 < position.quantity < Decimal("10")
