from __future__ import annotations

from decimal import Decimal

from app.schemas.profit import ProfitManagerConfig
from app.services.portfolio.profit_manager import evaluate_capital_recovery


class _FakePosition:
    """Minimal stand-in for the ORM Position row — evaluate_capital_recovery
    only reads a handful of attributes, so a plain object keeps these tests
    free of any database dependency."""

    def __init__(
        self,
        *,
        status="OPEN",
        initial_capital=Decimal("1000"),
        quantity=Decimal("10"),
        capital_recovered=Decimal("0"),
    ):
        self.status = status
        self.initial_capital = initial_capital
        self.quantity = quantity
        self.capital_recovered = capital_recovered


def _config(**overrides) -> ProfitManagerConfig:
    return ProfitManagerConfig(**overrides)


def test_no_recovery_when_disabled():
    proposal = evaluate_capital_recovery(
        _FakePosition(),
        current_price=Decimal("200"),
        fee_pct=Decimal("0.1"),
        config=_config(capital_recovery_enabled=False),
    )
    assert proposal.should_recover is False


def test_no_recovery_when_position_not_open():
    proposal = evaluate_capital_recovery(
        _FakePosition(status="PROFIT_RUNNER"),
        current_price=Decimal("200"),
        fee_pct=Decimal("0.1"),
        config=_config(),
    )
    assert proposal.should_recover is False
    assert "not OPEN" in proposal.reason


def test_no_recovery_below_profit_threshold():
    # $1000 initial, 10 units, price 105 -> value 1050 -> 5% profit, below 15% default.
    proposal = evaluate_capital_recovery(
        _FakePosition(initial_capital=Decimal("1000"), quantity=Decimal("10")),
        current_price=Decimal("105"),
        fee_pct=Decimal("0"),
        config=_config(min_profit_before_recovery=Decimal("0.15")),
    )
    assert proposal.should_recover is False
    assert "below" in proposal.reason


def test_recovers_when_profit_threshold_cleared_hand_computed():
    # $1000 initial, 10 units @ entry ~100, now price=140 -> value=1400 -> 40% profit.
    # Target recovery = 1000 * 1.00 = 1000. No fees/slippage for a clean hand check.
    # sell_quantity = 1000 / 140 = 7.142857...
    position = _FakePosition(initial_capital=Decimal("1000"), quantity=Decimal("10"))
    proposal = evaluate_capital_recovery(
        position,
        current_price=Decimal("140"),
        fee_pct=Decimal("0"),
        config=_config(max_slippage_percent=Decimal("0"), min_position_value=Decimal("1")),
    )
    assert proposal.should_recover is True
    assert proposal.sell_quantity == Decimal("1000") / Decimal("140")
    assert proposal.estimated_proceeds == Decimal("1000")
    # Remainder must be strictly less than the full position (never a full exit).
    assert proposal.sell_quantity < position.quantity


def test_fees_and_slippage_increase_required_sell_quantity():
    position = _FakePosition(initial_capital=Decimal("1000"), quantity=Decimal("10"))
    no_cost = evaluate_capital_recovery(
        position,
        current_price=Decimal("140"),
        fee_pct=Decimal("0"),
        config=_config(max_slippage_percent=Decimal("0"), min_position_value=Decimal("1")),
    )
    with_cost = evaluate_capital_recovery(
        position,
        current_price=Decimal("140"),
        fee_pct=Decimal("0.5"),
        config=_config(max_slippage_percent=Decimal("0.01"), min_position_value=Decimal("1")),
    )
    assert with_cost.should_recover is True
    # Recovering the same dollar amount net of fees/slippage costs more units.
    assert with_cost.sell_quantity > no_cost.sell_quantity


def test_defers_rather_than_liquidate_entire_position():
    # Barely profitable enough to trigger, but recovering 100% of capital
    # would require selling essentially the whole position.
    position = _FakePosition(initial_capital=Decimal("1000"), quantity=Decimal("10"))
    proposal = evaluate_capital_recovery(
        position,
        current_price=Decimal("101"),  # tiny profit margin, but consider a huge target instead
        fee_pct=Decimal("0"),
        config=_config(
            min_profit_before_recovery=Decimal("0.0"),
            capital_recovery_target=Decimal("1.05"),
        ),
    )
    assert proposal.should_recover is False
    assert "entire" in proposal.reason


def test_defers_when_remainder_would_be_dust():
    position = _FakePosition(initial_capital=Decimal("1000"), quantity=Decimal("10"))
    proposal = evaluate_capital_recovery(
        position,
        current_price=Decimal("140"),
        fee_pct=Decimal("0"),
        config=_config(max_slippage_percent=Decimal("0"), min_position_value=Decimal("100000")),
    )
    assert proposal.should_recover is False
    assert "MIN_POSITION_VALUE" in proposal.reason


def test_already_fully_recovered_does_nothing_more():
    position = _FakePosition(
        initial_capital=Decimal("1000"),
        quantity=Decimal("10"),
        capital_recovered=Decimal("1000"),
    )
    proposal = evaluate_capital_recovery(
        position,
        current_price=Decimal("140"),
        fee_pct=Decimal("0"),
        config=_config(),
    )
    assert proposal.should_recover is False
    assert "already fully recovered" in proposal.reason


def test_never_proposes_selling_more_than_available_quantity():
    position = _FakePosition(initial_capital=Decimal("1000"), quantity=Decimal("10"))
    proposal = evaluate_capital_recovery(
        position,
        current_price=Decimal("140"),
        fee_pct=Decimal("0.5"),
        config=_config(max_slippage_percent=Decimal("0.01"), min_position_value=Decimal("1")),
    )
    if proposal.should_recover:
        assert proposal.sell_quantity <= position.quantity
