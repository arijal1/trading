"""Trader performance tracking (brief Section 10).

`compute_trader_metrics` is a pure function over a trader's closed trades
— easy to test with hand-built trade lists. `refresh_trader_metrics` is
the thin DB-facing wrapper: loads a trader's closed `trader_trades`,
computes metrics, and upserts a `trader_metrics` row.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trader import Trader, TraderMetrics, TraderTrade
from app.schemas.copy_trading import TraderMetricsResult

_UNBOUNDED_PROFIT_FACTOR = 999.0


class ClosedTrade:
    """Minimal shape compute_trader_metrics needs — lets tests build
    trade data without touching the database."""

    def __init__(
        self,
        *,
        entry_price: Decimal,
        size: Decimal,
        realized_pnl: Decimal,
        opened_at: datetime,
        closed_at: datetime,
    ) -> None:
        self.entry_price = entry_price
        self.size = size
        self.realized_pnl = realized_pnl
        self.opened_at = opened_at
        self.closed_at = closed_at


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def compute_trader_metrics(trades: list[ClosedTrade]) -> TraderMetricsResult:
    if not trades:
        return TraderMetricsResult(
            num_trades=0,
            win_rate=0.0,
            avg_return_pct=0.0,
            max_drawdown_pct=0.0,
            profit_factor=0.0,
            avg_hold_time_seconds=0.0,
            consistency_score=0.0,
            risk_score=0.0,
        )

    returns_pct: list[float] = []
    pnls: list[float] = []
    hold_seconds: list[float] = []
    for trade in trades:
        notional = trade.entry_price * trade.size
        returns_pct.append(float(trade.realized_pnl / notional) if notional else 0.0)
        pnls.append(float(trade.realized_pnl))
        hold_seconds.append((trade.closed_at - trade.opened_at).total_seconds())

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / len(trades)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = _UNBOUNDED_PROFIT_FACTOR
    else:
        profit_factor = 0.0

    avg_return_pct = sum(returns_pct) / len(returns_pct)

    # Dimensionless equity curve (starts at 1.0, compounds returns_pct in
    # trade-closed order) so drawdown is comparable across traders
    # regardless of how much capital any one of them actually deploys.
    ordered_returns = [
        ret
        for _trade, ret in sorted(
            zip(trades, returns_pct, strict=True), key=lambda pair: pair[0].closed_at
        )
    ]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for ret in ordered_returns:
        equity *= 1 + ret
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    std_return = _stdev(returns_pct)
    # Bounded (0, 1]: low return volatility relative to nothing-in-particular
    # scores higher. A documented heuristic, not a statistically validated
    # consistency measure.
    consistency_score = 1 / (1 + std_return)

    risk_score = max(0.0, min(100.0, max_drawdown * 100 + std_return * 100))

    return TraderMetricsResult(
        num_trades=len(trades),
        win_rate=win_rate,
        avg_return_pct=avg_return_pct,
        max_drawdown_pct=max_drawdown,
        profit_factor=profit_factor,
        avg_hold_time_seconds=sum(hold_seconds) / len(hold_seconds),
        consistency_score=consistency_score,
        risk_score=risk_score,
    )


async def refresh_trader_metrics(db: AsyncSession, trader_id: uuid.UUID) -> TraderMetrics:
    trader = await db.get(Trader, trader_id)
    if trader is None:
        raise ValueError(f"trader {trader_id} not found")

    result = await db.execute(
        select(TraderTrade).where(
            TraderTrade.trader_id == trader_id,
            TraderTrade.closed_at.is_not(None),
            TraderTrade.realized_pnl.is_not(None),
        )
    )
    trades = [
        ClosedTrade(
            entry_price=t.entry_price,
            size=t.size,
            realized_pnl=t.realized_pnl,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
        )
        for t in result.scalars()
    ]
    metrics = compute_trader_metrics(trades)

    last_activity_result = await db.execute(
        select(TraderTrade.opened_at)
        .where(TraderTrade.trader_id == trader_id)
        .order_by(TraderTrade.opened_at.desc())
        .limit(1)
    )
    last_activity_at = last_activity_result.scalar_one_or_none()

    row = TraderMetrics(
        trader_id=trader_id,
        win_rate=Decimal(str(round(metrics.win_rate, 6))),
        avg_return=Decimal(str(round(metrics.avg_return_pct, 6))),
        max_drawdown=Decimal(str(round(metrics.max_drawdown_pct, 6))),
        profit_factor=Decimal(str(round(metrics.profit_factor, 4))),
        avg_hold_time_seconds=int(metrics.avg_hold_time_seconds),
        num_trades=metrics.num_trades,
        last_activity_at=last_activity_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
