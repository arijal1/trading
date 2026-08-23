"""Backtesting engine (brief Section 36).

Walks forward bar by bar over historical candles. At bar `i`, only
`candles[:i+1]` is ever visible to the technical analysis / strategy
layer — a decision made from bar `i`'s close always fills at bar `i+1`'s
open, so the engine can never act on information from the future. Fees
come from the exchange adapter's fee schedule; slippage is modeled
explicitly as a configurable adverse price move on every fill.

What this does NOT do (documented scope, not an oversight):
- **Partial fills**: every fill is assumed complete. Modeling partial
  fills needs a liquidity/order-book model this phase doesn't have.
- **Latency simulation**: fills are instant at the next bar's open.
- **True walk-forward *optimization***: strategies here are fixed
  rule-based heuristics, not fitted parameters, so there is nothing to
  re-fit per rolling window. The "no look-ahead" walk-forward *execution*
  style is what's implemented.
- **Capital recovery / staged profit-locking** (Section 2/19/42) and
  **copy-trading delay** (Section 12): both depend on machinery that is
  explicitly Phase 4 (ProfitManager, trader tracking).
- **Multi-asset portfolio effects** (correlation, survivorship bias
  across a universe): this engine backtests one symbol at a time.

Because none of the above involves randomness, this engine has no RNG
and needs no seed to be reproducible — the same candles and config always
produce the same trades.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.db.models.core import Candle
from app.schemas.backtest import BacktestConfig, BacktestResult, TradeRecord
from app.schemas.exchange import TIMEFRAME_SECONDS, Timeframe
from app.schemas.exit import PositionExitState
from app.schemas.portfolio import PortfolioState, PositionSizeRequest
from app.schemas.strategy import SignalDirection
from app.services.backtesting.metrics import compute_performance_metrics
from app.services.execution.exit_engine import (
    ExitEngine,
    advance_position_state,
    compute_dynamic_stop_loss,
)
from app.services.portfolio.position_sizing import calculate_position_size
from app.services.portfolio.risk_engine import PortfolioRiskEngine
from app.services.strategy.aggregator import StrategyAggregator
from app.services.strategy.signals import generate_all_signals
from app.services.technical_analysis.engine import (
    MIN_BARS_REQUIRED,
    TechnicalAnalysisEngine,
    candles_to_dataframe,
)


@dataclass
class _Bar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class _OpenPosition:
    exit_state: PositionExitState
    quantity: Decimal
    entry_fee: Decimal
    entry_bar_index: int


class BacktestEngine:
    def __init__(self, config: BacktestConfig, *, taker_fee_pct: Decimal) -> None:
        self.config = config
        self.taker_fee_pct = taker_fee_pct
        self.ta_engine = TechnicalAnalysisEngine()
        self.exit_engine = ExitEngine()
        self.aggregator = StrategyAggregator(
            weights=config.strategy_weights,
            buy_threshold=config.buy_threshold,
            sell_threshold=config.sell_threshold,
        )
        self.risk_engine = PortfolioRiskEngine(config.risk_limits)

    def run(self, candles: list[Candle], *, symbol: str, timeframe: Timeframe) -> BacktestResult:
        sorted_candles = sorted(candles, key=lambda c: c.ts)
        if len(sorted_candles) < MIN_BARS_REQUIRED + 1:
            raise ValueError(
                f"need at least {MIN_BARS_REQUIRED + 1} candles to backtest "
                f"(one extra bar to execute the final decision), got {len(sorted_candles)}"
            )

        bars = [
            _Bar(ts=c.ts, open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume)
            for c in sorted_candles
        ]
        ta_df = candles_to_dataframe(sorted_candles)
        max_hold_seconds = (
            self.config.max_hold_bars * TIMEFRAME_SECONDS[timeframe]
            if self.config.max_hold_bars
            else None
        )

        cash = self.config.starting_equity
        position: _OpenPosition | None = None
        trades: list[TradeRecord] = []
        equity_curve: list[float] = []

        peak_equity = cash
        day_start_equity = cash
        week_start_equity = cash
        current_day = bars[MIN_BARS_REQUIRED - 1].ts.date()
        current_week = bars[MIN_BARS_REQUIRED - 1].ts.isocalendar()[:2]

        for i in range(MIN_BARS_REQUIRED - 1, len(bars) - 1):
            bar = bars[i]
            next_bar = bars[i + 1]

            position_value = position.quantity * bar.close if position else Decimal(0)
            mark_to_market_equity = cash + position_value

            if bar.ts.date() != current_day:
                current_day = bar.ts.date()
                day_start_equity = mark_to_market_equity
            bar_week = bar.ts.isocalendar()[:2]
            if bar_week != current_week:
                current_week = bar_week
                week_start_equity = mark_to_market_equity
            peak_equity = max(peak_equity, mark_to_market_equity)

            window_start = max(0, i - self.config.ta_window_bars + 1)
            ta = self.ta_engine.analyze(
                ta_df.iloc[window_start : i + 1], symbol=symbol, timeframe=timeframe.value
            )

            portfolio_state = PortfolioState(
                equity=mark_to_market_equity,
                cash=cash,
                open_position_count=1 if position else 0,
                exposure_by_asset=(
                    {symbol: position.quantity * bar.close} if position else {}
                ),
                total_exposure=(position.quantity * bar.close if position else Decimal(0)),
                peak_equity=peak_equity,
                day_start_equity=day_start_equity,
                week_start_equity=week_start_equity,
                # Backtests don't consult live system_state — there is no
                # "live" trading happening to halt.
                is_emergency_stopped=False,
                is_trading_halted=False,
            )

            if position is not None:
                position.exit_state = advance_position_state(position.exit_state, bar.high)
                exit_decision = self.exit_engine.evaluate(
                    position.exit_state,
                    current_high=bar.high,
                    current_low=bar.low,
                    current_close=bar.close,
                    current_ts=bar.ts,
                    ta=ta,
                )
                if exit_decision.should_exit:
                    if exit_decision.fills_intrabar:
                        # Stop/trailing-stop/take-profit: a resting order
                        # that filled the moment this (already-closed)
                        # bar's low/high crossed it — not deferred to the
                        # next bar.
                        raw_exit_price = exit_decision.exit_price
                        assert raw_exit_price is not None
                        exit_ts, exit_bar_index = bar.ts, i
                    else:
                        raw_exit_price = next_bar.open
                        exit_ts, exit_bar_index = next_bar.ts, i + 1
                    cash, trade = self._close_position(
                        position,
                        raw_exit_price=raw_exit_price,
                        exit_ts=exit_ts,
                        exit_trigger=exit_decision.trigger.value,
                        exit_bar_index=exit_bar_index,
                        cash=cash,
                    )
                    trades.append(trade)
                    position = None
            else:
                atr = ta.indicators.atr_14
                if atr is not None and atr > 0:
                    signals = generate_all_signals(ta)
                    decision = self.aggregator.aggregate(signals)
                    if decision.direction == SignalDirection.BUY:
                        position = self._try_open_position(
                            symbol=symbol,
                            next_bar=next_bar,
                            entry_bar_index=i + 1,
                            atr=Decimal(str(atr)),
                            equity=mark_to_market_equity,
                            cash=cash,
                            portfolio_state=portfolio_state,
                            max_hold_seconds=max_hold_seconds,
                        )
                        if position is not None:
                            cost = (
                                position.exit_state.entry_price * position.quantity
                                + position.entry_fee
                            )
                            cash -= cost

            equity_curve.append(float(mark_to_market_equity))

        if position is not None:
            final_bar = bars[-1]
            cash, trade = self._close_position(
                position,
                raw_exit_price=final_bar.close,
                exit_ts=final_bar.ts,
                exit_trigger="END_OF_DATA",
                exit_bar_index=len(bars) - 1,
                cash=cash,
            )
            trades.append(trade)
            equity_curve.append(float(cash))

        metrics = compute_performance_metrics(equity_curve, trades, timeframe=timeframe.value)

        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe.value,
            bar_count=len(bars),
            starting_equity=self.config.starting_equity,
            ending_equity=cash,
            trades=trades,
            metrics=metrics,
        )

    def _apply_slippage(self, raw_price: Decimal, *, selling: bool) -> Decimal:
        slip = raw_price * self.config.slippage_pct
        return raw_price - slip if selling else raw_price + slip

    def _close_position(
        self,
        position: _OpenPosition,
        *,
        raw_exit_price: Decimal,
        exit_ts: datetime,
        exit_trigger: str,
        exit_bar_index: int,
        cash: Decimal,
    ) -> tuple[Decimal, TradeRecord]:
        """Fill the sell, realize PnL/fees, and return updated cash plus the trade record.

        Shared by both the mid-loop exit-trigger path and the end-of-data
        forced liquidation, which previously duplicated this PnL/fee math.
        """
        fill_price = self._apply_slippage(raw_exit_price, selling=True)
        fee = fill_price * position.quantity * self.taker_fee_pct / Decimal(100)
        proceeds = fill_price * position.quantity - fee
        cost_basis = position.exit_state.entry_price * position.quantity
        pnl = proceeds - cost_basis - position.entry_fee
        trade = TradeRecord(
            entry_ts=position.exit_state.opened_at,
            exit_ts=exit_ts,
            entry_price=position.exit_state.entry_price,
            exit_price=fill_price,
            quantity=position.quantity,
            pnl=pnl,
            pnl_pct=float(pnl / cost_basis) if cost_basis else 0.0,
            exit_trigger=exit_trigger,
            fees_paid=position.entry_fee + fee,
            holding_bars=exit_bar_index - position.entry_bar_index,
        )
        return cash + proceeds, trade

    def _try_open_position(
        self,
        *,
        symbol: str,
        next_bar: _Bar,
        entry_bar_index: int,
        atr: Decimal,
        equity: Decimal,
        cash: Decimal,
        portfolio_state: PortfolioState,
        max_hold_seconds: int | None,
    ) -> _OpenPosition | None:
        entry_price = self._apply_slippage(next_bar.open, selling=False)
        stop_price = compute_dynamic_stop_loss(
            entry_price=entry_price, atr=atr, atr_multiplier=self.config.atr_multiplier
        )
        if stop_price <= 0:
            return None

        size_request = PositionSizeRequest(
            equity=equity,
            entry_price=entry_price,
            stop_price=stop_price,
            risk_pct=self.config.risk_pct,
            max_position_value_pct=self.config.risk_limits.max_position_size,
            min_position_value=self.config.min_position_value,
        )
        size_result = calculate_position_size(size_request)
        if size_result.quantity <= 0:
            return None

        risk_check = self.risk_engine.check_new_position(
            portfolio_state, asset_symbol=symbol, proposed_notional=size_result.notional_value
        )
        if not risk_check.approved:
            return None

        fee = entry_price * size_result.quantity * self.taker_fee_pct / Decimal(100)
        if entry_price * size_result.quantity + fee > cash:
            return None

        take_profit_price = (
            entry_price * (1 + self.config.take_profit_pct)
            if self.config.take_profit_pct
            else None
        )
        exit_state = PositionExitState(
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            trailing_stop_pct=self.config.trailing_stop_pct,
            highest_price_since_entry=entry_price,
            opened_at=next_bar.ts,
            max_hold_seconds=max_hold_seconds,
        )
        return _OpenPosition(
            exit_state=exit_state,
            quantity=size_result.quantity,
            entry_fee=fee,
            entry_bar_index=entry_bar_index,
        )
