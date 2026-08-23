from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from app.core.config import Settings, TradingMode
from app.schemas.live_trading import GuardCheck
from app.services.execution import order_manager as order_manager_module
from app.services.execution.live_guard import LiveTradingGuard, is_live_order


class _FakeAccount:
    def __init__(self, mode: str = "live") -> None:
        self.id = "acct-1"
        self.mode = mode


class _FakeExchange:
    def __init__(self, withdrawals_disabled: bool = True, has_creds: bool = True) -> None:
        self.name = "Test"
        self.withdrawals_disabled = withdrawals_disabled
        self.api_key_encrypted = "cipher" if has_creds else None
        self.api_secret_encrypted = "cipher" if has_creds else None


class _FakeState:
    def __init__(self, stopped: bool = False, halted: bool = False) -> None:
        self.is_emergency_stopped = stopped
        self.is_trading_halted = halted


@pytest.fixture
def patch_state(monkeypatch):
    """Stub system_state so the guard's DB read is controllable."""

    def _apply(state: _FakeState):
        async def _get(_db):
            return state

        monkeypatch.setattr(
            "app.services.execution.live_guard.system_state_service.get_or_create_state", _get
        )

    return _apply


def _all_green_settings() -> Settings:
    return Settings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING=True,
        TRADING_CONFIRMATION=True,
        VALID_EXCHANGE_CREDENTIALS=True,
        RISK_LIMITS_VALID=True,
        EMERGENCY_STOP_AVAILABLE=True,
        DISABLE_WITHDRAWALS=True,
        MAX_LIVE_CAPITAL=1000.0,
    )


@pytest.mark.asyncio
async def test_default_configuration_cannot_place_a_live_order(patch_state):
    """The single most important test in this file: a deployment that
    changes nothing must be incapable of trading real money."""
    patch_state(_FakeState())
    guard = LiveTradingGuard(Settings())
    decision = await guard.evaluate(
        None, account=_FakeAccount(), exchange=_FakeExchange(), notional_value=Decimal("10")
    )
    assert decision.allowed is False
    assert GuardCheck.TRADING_MODE_IS_LIVE in decision.failed_checks
    assert GuardCheck.LIVE_TRADING_ENABLED in decision.failed_checks
    assert GuardCheck.TRADING_CONFIRMATION in decision.failed_checks
    assert GuardCheck.VALID_EXCHANGE_CREDENTIALS in decision.failed_checks
    assert GuardCheck.RISK_LIMITS_VALID in decision.failed_checks


@pytest.mark.asyncio
async def test_fully_configured_setup_is_permitted(patch_state):
    patch_state(_FakeState())
    guard = LiveTradingGuard(_all_green_settings())
    decision = await guard.evaluate(
        None, account=_FakeAccount(), exchange=_FakeExchange(), notional_value=Decimal("500")
    )
    assert decision.allowed is True, decision.reason
    assert decision.failed_checks == []


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"LIVE_TRADING": False}, GuardCheck.LIVE_TRADING_ENABLED),
        ({"TRADING_CONFIRMATION": False}, GuardCheck.TRADING_CONFIRMATION),
        ({"VALID_EXCHANGE_CREDENTIALS": False}, GuardCheck.VALID_EXCHANGE_CREDENTIALS),
        ({"RISK_LIMITS_VALID": False}, GuardCheck.RISK_LIMITS_VALID),
        ({"EMERGENCY_STOP_AVAILABLE": False}, GuardCheck.EMERGENCY_STOP_AVAILABLE),
        ({"TRADING_MODE": TradingMode.PAPER}, GuardCheck.TRADING_MODE_IS_LIVE),
        ({"DISABLE_WITHDRAWALS": False}, GuardCheck.WITHDRAWALS_DISABLED),
    ],
)
@pytest.mark.asyncio
async def test_each_switch_independently_blocks_live_trading(patch_state, override, expected):
    """Every guardrail must be individually sufficient to refuse — none of
    them can be compensated for by the others being green."""
    patch_state(_FakeState())
    settings = _all_green_settings().model_copy(update=override)
    guard = LiveTradingGuard(settings)
    decision = await guard.evaluate(
        None, account=_FakeAccount(), exchange=_FakeExchange(), notional_value=Decimal("500")
    )
    assert decision.allowed is False
    assert expected in decision.failed_checks


@pytest.mark.asyncio
async def test_emergency_stop_overrides_a_fully_enabled_live_config(patch_state):
    patch_state(_FakeState(stopped=True, halted=True))
    guard = LiveTradingGuard(_all_green_settings())
    decision = await guard.evaluate(
        None, account=_FakeAccount(), exchange=_FakeExchange(), notional_value=Decimal("500")
    )
    assert decision.allowed is False
    assert GuardCheck.NOT_EMERGENCY_STOPPED in decision.failed_checks
    assert GuardCheck.NOT_TRADING_HALTED in decision.failed_checks


@pytest.mark.asyncio
async def test_paper_account_cannot_route_to_a_live_venue(patch_state):
    patch_state(_FakeState())
    guard = LiveTradingGuard(_all_green_settings())
    decision = await guard.evaluate(
        None,
        account=_FakeAccount(mode="paper"),
        exchange=_FakeExchange(),
        notional_value=Decimal("500"),
    )
    assert decision.allowed is False
    assert GuardCheck.ACCOUNT_IS_LIVE_MODE in decision.failed_checks


@pytest.mark.asyncio
async def test_missing_exchange_is_refused(patch_state):
    patch_state(_FakeState())
    guard = LiveTradingGuard(_all_green_settings())
    decision = await guard.evaluate(
        None, account=_FakeAccount(), exchange=None, notional_value=Decimal("500")
    )
    assert decision.allowed is False
    assert GuardCheck.WITHDRAWALS_DISABLED in decision.failed_checks
    assert GuardCheck.VALID_EXCHANGE_CREDENTIALS in decision.failed_checks


@pytest.mark.asyncio
async def test_exchange_without_stored_credentials_is_refused(patch_state):
    patch_state(_FakeState())
    guard = LiveTradingGuard(_all_green_settings())
    decision = await guard.evaluate(
        None,
        account=_FakeAccount(),
        exchange=_FakeExchange(has_creds=False),
        notional_value=Decimal("500"),
    )
    assert decision.allowed is False
    assert GuardCheck.VALID_EXCHANGE_CREDENTIALS in decision.failed_checks


@pytest.mark.asyncio
async def test_withdrawal_capable_key_is_refused(patch_state):
    patch_state(_FakeState())
    guard = LiveTradingGuard(_all_green_settings())
    decision = await guard.evaluate(
        None,
        account=_FakeAccount(),
        exchange=_FakeExchange(withdrawals_disabled=False),
        notional_value=Decimal("500"),
    )
    assert decision.allowed is False
    assert GuardCheck.WITHDRAWALS_DISABLED in decision.failed_checks


@pytest.mark.parametrize("notional", [Decimal("0"), Decimal("-5"), Decimal("1000.01")])
@pytest.mark.asyncio
async def test_notional_outside_the_cap_is_refused(patch_state, notional):
    patch_state(_FakeState())
    guard = LiveTradingGuard(_all_green_settings())
    decision = await guard.evaluate(
        None, account=_FakeAccount(), exchange=_FakeExchange(), notional_value=notional
    )
    assert decision.allowed is False
    assert GuardCheck.WITHIN_MAX_LIVE_CAPITAL in decision.failed_checks


@pytest.mark.asyncio
async def test_guard_fails_closed_when_evaluation_raises(monkeypatch):
    """An unverifiable guardrail must be treated as a failed guardrail —
    an exception must never surface as approval."""

    async def _boom(_db):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "app.services.execution.live_guard.system_state_service.get_or_create_state", _boom
    )
    guard = LiveTradingGuard(_all_green_settings())
    decision = await guard.evaluate(
        None, account=_FakeAccount(), exchange=_FakeExchange(), notional_value=Decimal("500")
    )
    assert decision.allowed is False
    assert "RuntimeError" in decision.reason


def test_is_live_order_requires_both_account_mode_and_global_mode():
    live_settings = _all_green_settings()
    paper_settings = Settings()
    assert is_live_order(_FakeAccount(mode="live"), live_settings) is True
    assert is_live_order(_FakeAccount(mode="paper"), live_settings) is False
    assert is_live_order(_FakeAccount(mode="live"), paper_settings) is False
    assert is_live_order(_FakeAccount(mode="paper"), paper_settings) is False


def test_order_manager_exposes_no_way_to_skip_the_guard():
    """Structural guarantee, not a behavioural one: if someone later adds
    a `skip_guard`-style escape hatch to the order path, this fails."""
    signature = inspect.signature(order_manager_module.OrderManager.submit_order)
    forbidden = {"skip_guard", "force", "bypass", "unsafe", "allow_live"}
    assert forbidden.isdisjoint(signature.parameters)

    source = inspect.getsource(order_manager_module.OrderManager.submit_order)
    assert "_enforce_live_guard" in source, (
        "submit_order must call the live guard; removing that call would let live "
        "orders reach a venue ungated"
    )
