"""Profit Manager: capital recovery + profit-runner management (brief
Sections 2, 19, 42).

The core rule, stated precisely because it's easy to get backwards: once
a position is profitable enough, propose selling *just enough* of it to
recover the original capital invested (net of estimated fees/slippage —
exact recovery is never guaranteed), then let the remainder run as a
"house money" position. The remainder is never treated as risk-free —
`app/services/execution/exit_engine.py`'s trailing stop keeps managing it
exactly like any other open position.

`evaluate_capital_recovery` is a pure function: given a position snapshot
and current price, it proposes a sell size or explains why it's not
proposing one. It deliberately refuses to propose a sell that would
liquidate the whole position (that's what capital recovery is explicitly
*not* supposed to do — see brief Section 2: "Never blindly sell the
entire position simply because the initial capital has been recovered")
or leave a dust-sized remainder.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trading import Fill, Position, PositionEvent
from app.schemas.profit import CapitalRecoveryProposal, ProfitManagerConfig


def evaluate_capital_recovery(
    position: Position,
    *,
    current_price: Decimal,
    fee_pct: Decimal,
    config: ProfitManagerConfig,
) -> CapitalRecoveryProposal:
    if not config.capital_recovery_enabled:
        return CapitalRecoveryProposal(reason="capital recovery disabled")
    if position.status != "OPEN":
        return CapitalRecoveryProposal(reason=f"position status is {position.status}, not OPEN")
    if position.initial_capital <= 0 or position.quantity <= 0:
        return CapitalRecoveryProposal(reason="position has no capital or quantity at risk")

    market_value = position.quantity * current_price
    unrealized_profit = market_value - position.initial_capital
    unrealized_profit_pct = unrealized_profit / position.initial_capital

    if unrealized_profit_pct < config.min_profit_before_recovery:
        return CapitalRecoveryProposal(
            reason=(
                f"unrealized profit {unrealized_profit_pct:.2%} below "
                f"threshold {config.min_profit_before_recovery:.2%}"
            )
        )

    target_recovery = position.initial_capital * config.capital_recovery_target
    remaining_to_recover = target_recovery - position.capital_recovered
    if remaining_to_recover <= 0:
        return CapitalRecoveryProposal(reason="initial capital already fully recovered")

    effective_price = current_price * (1 - config.max_slippage_percent)
    net_price_per_unit = effective_price * (1 - fee_pct / Decimal(100))
    if net_price_per_unit <= 0:
        return CapitalRecoveryProposal(reason="degenerate price after fees/slippage")

    sell_quantity = remaining_to_recover / net_price_per_unit

    if sell_quantity >= position.quantity:
        # Recovering the target would require selling the whole position —
        # exactly what capital recovery must never do. Wait for more
        # profit margin instead of forcing a full exit under this banner.
        return CapitalRecoveryProposal(
            reason=(
                "recovering target capital would require liquidating the entire "
                "position; deferring until there is enough margin to leave a "
                "profit-runner remainder"
            )
        )

    remainder_quantity = position.quantity - sell_quantity
    remainder_value = remainder_quantity * current_price
    if remainder_value < config.min_position_value:
        return CapitalRecoveryProposal(
            reason=(
                f"remaining position value {remainder_value:.2f} would be below "
                f"MIN_POSITION_VALUE {config.min_position_value}; deferring"
            )
        )

    estimated_proceeds = sell_quantity * net_price_per_unit
    return CapitalRecoveryProposal(
        should_recover=True,
        sell_quantity=sell_quantity,
        estimated_proceeds=estimated_proceeds,
        reason=(
            f"unrealized profit {unrealized_profit_pct:.2%} clears threshold; "
            f"selling {sell_quantity} to recover ~{estimated_proceeds:.2f} of "
            f"{position.initial_capital} initial capital"
        ),
    )


async def apply_capital_recovery_fill(
    db: AsyncSession, *, position: Position, fill: Fill, config: ProfitManagerConfig
) -> Position:
    """Applies a capital-recovery sell fill: updates capital_recovered/
    profit_locked/quantity and transitions the position to PROFIT_RUNNER.
    The remainder keeps trading under the exit engine's trailing stop —
    it is never marked as risk-free, and it never gets a resurrected fixed
    take-profit target (Section 2/19's "house money" framing: the runner
    is managed by structure/trailing stop, not a static price target).
    """
    proceeds = fill.price * fill.quantity - fill.fee
    realized_pnl = proceeds - (position.avg_entry_price * fill.quantity)

    position.capital_recovered += proceeds
    position.profit_locked += realized_pnl
    position.quantity -= fill.quantity

    if position.quantity <= 0:
        position.status = "CLOSED"
    else:
        position.status = "PROFIT_RUNNER"
        position.take_profit_price = None
        if position.trailing_stop_pct is None and config.profit_position_enabled:
            position.trailing_stop_pct = config.trailing_stop_percent

    db.add(
        PositionEvent(
            position_id=position.id,
            event_type="CAPITAL_RECOVERED",
            payload={
                "sold_quantity": str(fill.quantity),
                "fill_price": str(fill.price),
                "proceeds": str(proceeds),
                "realized_pnl": str(realized_pnl),
                "capital_recovered_total": str(position.capital_recovered),
                "remaining_quantity": str(position.quantity),
            },
        )
    )
    await db.commit()
    await db.refresh(position)
    return position
