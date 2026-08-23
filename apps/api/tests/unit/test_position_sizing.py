from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.portfolio import PositionSizeRequest
from app.services.portfolio.position_sizing import (
    InvalidStopDistanceError,
    calculate_position_size,
    fixed_fractional_size,
    volatility_adjusted_size,
)


def test_fixed_fractional_size_hand_computed():
    # $10,000 equity, risk 1% = $100. Entry 100, stop 95 -> distance 5.
    # quantity = 100 / 5 = 20.
    quantity = fixed_fractional_size(
        equity=Decimal("10000"),
        risk_pct=Decimal("0.01"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
    )
    assert quantity == Decimal("20")


def test_fixed_fractional_size_rejects_zero_distance():
    with pytest.raises(InvalidStopDistanceError):
        fixed_fractional_size(
            equity=Decimal("10000"),
            risk_pct=Decimal("0.01"),
            entry_price=Decimal("100"),
            stop_price=Decimal("100"),
        )


def test_volatility_adjusted_size_hand_computed():
    # $10,000 equity, risk 1% = $100. ATR=2, multiplier=2.5 -> stop distance=5.
    # quantity = 100/5 = 20.
    quantity = volatility_adjusted_size(
        equity=Decimal("10000"),
        risk_pct=Decimal("0.01"),
        atr=Decimal("2"),
        atr_multiplier=Decimal("2.5"),
        entry_price=Decimal("100"),
    )
    assert quantity == Decimal("20")


def test_calculate_position_size_uncapped():
    request = PositionSizeRequest(
        equity=Decimal("10000"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        risk_pct=Decimal("0.01"),
        max_position_value_pct=Decimal("0.50"),  # generous cap, shouldn't bind
        min_position_value=Decimal("10"),
    )
    result = calculate_position_size(request)
    assert result.quantity == Decimal("20")
    assert result.notional_value == Decimal("2000")
    assert result.risk_amount == Decimal("100")
    assert result.capped_by is None


def test_calculate_position_size_capped_by_max_position_size():
    # Uncapped notional would be 20 * 100 = 2000, i.e. 20% of equity.
    # Cap it to 5% of equity ($500) instead.
    request = PositionSizeRequest(
        equity=Decimal("10000"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        risk_pct=Decimal("0.01"),
        max_position_value_pct=Decimal("0.05"),
        min_position_value=Decimal("10"),
    )
    result = calculate_position_size(request)
    assert result.capped_by == "max_position_size"
    assert result.notional_value == Decimal("500")
    assert result.quantity == Decimal("5")


def test_calculate_position_size_skips_dust_position():
    request = PositionSizeRequest(
        equity=Decimal("100"),
        entry_price=Decimal("100"),
        stop_price=Decimal("99"),
        risk_pct=Decimal("0.001"),  # tiny risk budget -> tiny position
        max_position_value_pct=Decimal("0.10"),
        min_position_value=Decimal("50"),
    )
    result = calculate_position_size(request)
    assert result.quantity == Decimal("0")
    assert result.capped_by == "min_position_value"
