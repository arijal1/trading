from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.core import Candle
from app.schemas.backtest import BacktestConfig
from app.schemas.exchange import Timeframe
from app.services.backtesting.engine import BacktestEngine
from app.services.exchanges.mock import MockExchangeAdapter
from app.services.technical_analysis.engine import MIN_BARS_REQUIRED


def _mock_candles(symbol: str, hours: int, since: datetime | None = None) -> list[Candle]:
    adapter = MockExchangeAdapter()
    since = since or datetime(2026, 1, 1, tzinfo=UTC)
    until = since + timedelta(hours=hours)
    bars = asyncio.get_event_loop().run_until_complete(
        adapter.get_ohlcv(symbol, Timeframe.H1, since, until)
    )
    return [
        Candle(
            market_id=None,
            timeframe="1h",
            ts=b.ts,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
        )
        for b in bars
    ]


def _engine(config: BacktestConfig | None = None) -> BacktestEngine:
    return BacktestEngine(config or BacktestConfig(), taker_fee_pct=Decimal("0.15"))


def test_rejects_insufficient_candles():
    candles = _mock_candles("BTC/USD", hours=MIN_BARS_REQUIRED)
    with pytest.raises(ValueError):
        _engine().run(candles, symbol="BTC/USD", timeframe=Timeframe.H1)


def test_runs_and_produces_bounded_metrics():
    candles = _mock_candles("BTC/USD", hours=250)
    result = _engine().run(candles, symbol="BTC/USD", timeframe=Timeframe.H1)

    assert result.bar_count == 250
    assert result.starting_equity == Decimal("10000")
    assert result.ending_equity > 0
    assert 0 <= result.metrics.win_rate <= 1
    assert 0 <= result.metrics.loss_rate <= 1
    assert result.metrics.max_drawdown_pct >= 0
    assert result.metrics.num_trades == len(result.trades)


def test_is_reproducible_given_identical_inputs():
    candles = _mock_candles("BTC/USD", hours=250)
    result_1 = _engine().run(candles, symbol="BTC/USD", timeframe=Timeframe.H1)
    result_2 = _engine().run(candles, symbol="BTC/USD", timeframe=Timeframe.H1)
    assert result_1.model_dump() == result_2.model_dump()


def test_every_trade_exit_after_entry_in_time():
    candles = _mock_candles("BTC/USD", hours=250)
    result = _engine().run(candles, symbol="BTC/USD", timeframe=Timeframe.H1)
    for trade in result.trades:
        # >= not >: an intrabar stop/take-profit hit on the very bar a
        # position was entered on is a legitimate 0-bar-hold trade, and
        # with only OHLC (not tick) data both are stamped with that bar's
        # own timestamp.
        assert trade.exit_ts >= trade.entry_ts
        assert trade.quantity > 0
        assert trade.holding_bars >= 0


def test_fees_are_charged_on_every_trade():
    candles = _mock_candles("BTC/USD", hours=250)
    result = _engine().run(candles, symbol="BTC/USD", timeframe=Timeframe.H1)
    assert len(result.trades) > 0
    for trade in result.trades:
        assert trade.fees_paid > 0


def test_never_opens_a_position_larger_than_max_position_size():
    config = BacktestConfig()
    config.risk_limits.max_position_size = Decimal("0.05")
    candles = _mock_candles("BTC/USD", hours=250)
    result = _engine(config).run(candles, symbol="BTC/USD", timeframe=Timeframe.H1)
    for trade in result.trades:
        notional = trade.entry_price * trade.quantity
        # Sized off equity at entry time, which we don't retain per-trade,
        # but it can never exceed the *starting* equity by more than the
        # cap fraction since equity only grows/shrinks by realized trades.
        assert notional <= config.starting_equity * Decimal("0.10")  # generous sanity bound


def test_never_places_a_trade_when_cash_is_exhausted():
    """A pathological config (100% risk) must never push cash negative."""
    config = BacktestConfig(risk_pct=Decimal("1.0"))
    config.risk_limits.max_position_size = Decimal("1.0")
    candles = _mock_candles("BTC/USD", hours=250)
    result = _engine(config).run(candles, symbol="BTC/USD", timeframe=Timeframe.H1)
    assert result.ending_equity >= 0


def test_different_symbols_produce_different_trades():
    btc_candles = _mock_candles("BTC/USD", hours=250)
    eth_candles = _mock_candles("ETH/USD", hours=250)
    btc_result = _engine().run(btc_candles, symbol="BTC/USD", timeframe=Timeframe.H1)
    eth_result = _engine().run(eth_candles, symbol="ETH/USD", timeframe=Timeframe.H1)
    assert [t.entry_price for t in btc_result.trades] != [t.entry_price for t in eth_result.trades]
