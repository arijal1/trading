"""Position sizing (brief Section 20). Never a fixed arbitrary amount.

`fixed_fractional_size` and `volatility_adjusted_size` are the two raw
sizing formulas the brief names; `calculate_position_size` is the
caller-facing entrypoint that applies both the fixed-fractional formula
and the max-exposure / min-position-value caps together, returning zero
quantity (a skip, not an error) when the resulting position would be
dust.
"""
from __future__ import annotations

from decimal import Decimal

from app.schemas.portfolio import PositionSizeRequest, PositionSizeResult


class InvalidStopDistanceError(ValueError):
    pass


def fixed_fractional_size(
    equity: Decimal, risk_pct: Decimal, entry_price: Decimal, stop_price: Decimal
) -> Decimal:
    """Quantity such that a fill at stop_price loses exactly equity * risk_pct."""
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        raise InvalidStopDistanceError("entry_price and stop_price must differ")
    risk_amount = equity * risk_pct
    return risk_amount / stop_distance


def volatility_adjusted_size(
    equity: Decimal, risk_pct: Decimal, atr: Decimal, atr_multiplier: Decimal, entry_price: Decimal
) -> Decimal:
    """Quantity sized off ATR directly, rather than a pre-computed stop distance."""
    if atr <= 0:
        raise InvalidStopDistanceError("atr must be positive")
    stop_distance = atr * atr_multiplier
    risk_amount = equity * risk_pct
    return risk_amount / stop_distance


def calculate_position_size(request: PositionSizeRequest) -> PositionSizeResult:
    quantity = fixed_fractional_size(
        request.equity, request.risk_pct, request.entry_price, request.stop_price
    )
    notional_value = quantity * request.entry_price
    risk_amount = quantity * abs(request.entry_price - request.stop_price)
    capped_by: str | None = None

    max_notional = request.equity * request.max_position_value_pct
    if notional_value > max_notional:
        quantity = max_notional / request.entry_price
        notional_value = quantity * request.entry_price
        risk_amount = quantity * abs(request.entry_price - request.stop_price)
        capped_by = "max_position_size"

    if notional_value < request.min_position_value:
        return PositionSizeResult(
            quantity=Decimal(0),
            notional_value=Decimal(0),
            risk_amount=Decimal(0),
            capped_by="min_position_value",
        )

    return PositionSizeResult(
        quantity=quantity,
        notional_value=notional_value,
        risk_amount=risk_amount,
        capped_by=capped_by,
    )
