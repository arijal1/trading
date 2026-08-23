"""Paper trading orchestrator: one decision cycle for one (account, market).

Ties together everything built across Phases 2-4:

  candles -> TechnicalAnalysisEngine (Phase 2)
          -> if a position is open: PositionManager.advance_and_evaluate_exit
             (ExitEngine, Phase 3) -> exit fill, or ProfitManager capital
             recovery (Phase 4) -> partial fill, or hold
          -> else: strategy signals + StrategyAggregator (Phase 3)
             -> compute_dynamic_stop_loss + calculate_position_size (Phase 3)
             -> PortfolioRiskEngine.check_new_position against a DB-backed
                PortfolioState (Phase 4) -> entry fill, or skip

Every fill goes through OrderManager (idempotent, Phase 4), so a tick can
be retried safely. Intentionally scoped to one (account, market) pair per
call — a scheduler that ticks every followed market for every account is
a Phase 5 concern (this is the same "no worker queue yet" boundary the
backtest engine's synchronous execution already documents).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Account, Candle, Market
from app.db.models.trading import Fill, Order
from app.schemas.exchange import TIMEFRAME_SECONDS, OrderSide, OrderType, Timeframe
from app.schemas.paper_trading import PaperTradingConfig, TickAction, TickResult
from app.schemas.portfolio import PositionSizeRequest
from app.schemas.strategy import SignalDirection
from app.services.exchanges.base import ExchangeAdapter
from app.services.execution.exit_engine import compute_dynamic_stop_loss
from app.services.execution.order_manager import OrderManager
from app.services.execution.position_manager import PositionManager
from app.services.portfolio.position_sizing import calculate_position_size
from app.services.portfolio.profit_manager import (
    apply_capital_recovery_fill,
    evaluate_capital_recovery,
)
from app.services.portfolio.risk_engine import PortfolioRiskEngine
from app.services.portfolio.state_builder import build_portfolio_state, record_snapshot
from app.services.strategy.aggregator import StrategyAggregator
from app.services.strategy.signals import generate_all_signals
from app.services.technical_analysis.engine import (
    MIN_BARS_REQUIRED,
    TechnicalAnalysisEngine,
    candles_to_dataframe,
)


async def _latest_fill(db: AsyncSession, order: Order) -> Fill:
    result = await db.execute(
        select(Fill).where(Fill.order_id == order.id).order_by(Fill.filled_at.desc()).limit(1)
    )
    fill = result.scalars().first()
    if fill is None:
        raise RuntimeError(f"order {order.id} has status {order.status} but no recorded fill")
    return fill


class PaperTradingSession:
    def __init__(self, adapter: ExchangeAdapter, config: PaperTradingConfig | None = None) -> None:
        self.adapter = adapter
        self.config = config or PaperTradingConfig()
        self.order_manager = OrderManager(adapter)
        self.position_manager = PositionManager()
        self.risk_engine = PortfolioRiskEngine(self.config.risk_limits)
        self.aggregator = StrategyAggregator(
            weights=self.config.strategy_weights,
            buy_threshold=self.config.buy_threshold,
            sell_threshold=self.config.sell_threshold,
        )
        self.ta_engine = TechnicalAnalysisEngine()

    async def run_tick(
        self, db: AsyncSession, *, account: Account, market: Market, timeframe: Timeframe
    ) -> TickResult:
        candles_result = await db.execute(
            select(Candle)
            .where(Candle.market_id == market.id, Candle.timeframe == timeframe.value)
            .order_by(Candle.ts.desc())
            .limit(self.config.ta_window_bars)
        )
        candles = list(candles_result.scalars())
        candles.reverse()
        if len(candles) < MIN_BARS_REQUIRED:
            return TickResult(
                action=TickAction.INSUFFICIENT_DATA,
                detail=f"need at least {MIN_BARS_REQUIRED} candles, have {len(candles)}",
            )

        df = candles_to_dataframe(candles)
        ta = self.ta_engine.analyze(df, symbol=market.symbol, timeframe=timeframe.value)
        latest_bar = candles[-1]
        current_price = latest_bar.close

        position = await self.position_manager.get_open_position(
            db, account_id=account.id, asset_id=market.base_asset_id
        )

        if position is not None:
            result = await self._manage_open_position(
                db, account=account, market=market, position=position, ta=ta, bar=latest_bar
            )
        else:
            result = await self._consider_entry(
                db,
                account=account,
                market=market,
                ta=ta,
                current_price=current_price,
                timeframe=timeframe,
            )

        state = await build_portfolio_state(
            db, account=account, current_prices={market.base_asset_id: current_price}
        )
        await record_snapshot(db, account=account, state=state)
        return result

    async def _manage_open_position(
        self, db: AsyncSession, *, account: Account, market: Market, position, ta, bar
    ) -> TickResult:
        exit_decision = await self.position_manager.advance_and_evaluate_exit(
            db,
            position,
            current_high=bar.high,
            current_low=bar.low,
            current_close=bar.close,
            current_ts=bar.ts,
            ta=ta,
        )
        if exit_decision.should_exit:
            sell_order = await self.order_manager.submit_order(
                db,
                account_id=account.id,
                asset_id=market.base_asset_id,
                symbol=market.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=position.quantity,
            )
            sell_fill = await _latest_fill(db, sell_order)
            closed = await self.position_manager.apply_sell_fill(
                db, position=position, fill=sell_fill, exit_trigger=exit_decision.trigger.value
            )
            return TickResult(
                action=TickAction.EXIT,
                detail=exit_decision.reason,
                order_id=sell_order.id,
                position_id=closed.id,
            )

        fees = await self.adapter.get_fees(market.symbol)
        proposal = evaluate_capital_recovery(
            position,
            current_price=bar.close,
            fee_pct=fees.taker_fee_pct,
            config=self.config.profit_manager,
        )
        if proposal.should_recover:
            recovery_order = await self.order_manager.submit_order(
                db,
                account_id=account.id,
                asset_id=market.base_asset_id,
                symbol=market.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=proposal.sell_quantity,
            )
            recovery_fill = await _latest_fill(db, recovery_order)
            runner = await apply_capital_recovery_fill(
                db, position=position, fill=recovery_fill, config=self.config.profit_manager
            )
            return TickResult(
                action=TickAction.CAPITAL_RECOVERED,
                detail=proposal.reason,
                order_id=recovery_order.id,
                position_id=runner.id,
            )

        return TickResult(
            action=TickAction.HOLD, detail="position open, no exit or recovery triggered"
        )

    async def _consider_entry(
        self,
        db: AsyncSession,
        *,
        account: Account,
        market: Market,
        ta,
        current_price: Decimal,
        timeframe: Timeframe,
    ) -> TickResult:
        atr = ta.indicators.atr_14
        if atr is None or atr <= 0:
            return TickResult(action=TickAction.NO_SIGNAL, detail="no ATR available yet")

        signals = generate_all_signals(ta)
        decision = self.aggregator.aggregate(signals)
        if decision.direction != SignalDirection.BUY:
            detail = (
                f"aggregate direction is {decision.direction.value} "
                f"(score={decision.score:.1f})"
            )
            return TickResult(action=TickAction.HOLD, detail=detail)

        stop_price = compute_dynamic_stop_loss(
            entry_price=current_price,
            atr=Decimal(str(atr)),
            atr_multiplier=self.config.atr_multiplier,
        )
        take_profit_price = (
            current_price * (1 + self.config.take_profit_pct)
            if self.config.take_profit_pct
            else None
        )

        portfolio_state = await build_portfolio_state(
            db, account=account, current_prices={market.base_asset_id: current_price}
        )
        size_request = PositionSizeRequest(
            equity=portfolio_state.equity,
            entry_price=current_price,
            stop_price=stop_price,
            risk_pct=self.config.risk_pct,
            max_position_value_pct=self.config.risk_limits.max_position_size,
            min_position_value=self.config.min_position_value,
        )
        size_result = calculate_position_size(size_request)
        if size_result.quantity <= 0:
            return TickResult(action=TickAction.SKIPPED_SIZE, detail=size_result.capped_by or "n/a")

        risk_check = self.risk_engine.check_new_position(
            portfolio_state,
            asset_symbol=str(market.base_asset_id),
            proposed_notional=size_result.notional_value,
        )
        if not risk_check.approved:
            return TickResult(action=TickAction.SKIPPED_RISK, detail=risk_check.reason or "n/a")

        max_hold_seconds = (
            self.config.max_hold_bars * TIMEFRAME_SECONDS[timeframe]
            if self.config.max_hold_bars
            else None
        )
        buy_order = await self.order_manager.submit_order(
            db,
            account_id=account.id,
            asset_id=market.base_asset_id,
            symbol=market.symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=size_result.quantity,
        )
        buy_fill = await _latest_fill(db, buy_order)
        position = await self.position_manager.apply_buy_fill(
            db,
            order=buy_order,
            fill=buy_fill,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            trailing_stop_pct=self.config.trailing_stop_pct,
            max_hold_seconds=max_hold_seconds,
        )
        return TickResult(
            action=TickAction.OPENED,
            detail=decision.reason_codes and ", ".join(decision.reason_codes) or "entry signal",
            order_id=buy_order.id,
            position_id=position.id,
        )
