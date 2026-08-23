from __future__ import annotations

from decimal import Decimal

from app.schemas.portfolio import PortfolioState, RiskLimits
from app.services.portfolio.risk_engine import PortfolioRiskEngine


def _healthy_state(**overrides) -> PortfolioState:
    defaults = dict(
        equity=Decimal("10000"),
        cash=Decimal("10000"),
        open_position_count=0,
        exposure_by_asset={},
        total_exposure=Decimal("0"),
        peak_equity=Decimal("10000"),
        day_start_equity=Decimal("10000"),
        week_start_equity=Decimal("10000"),
    )
    defaults.update(overrides)
    return PortfolioState(**defaults)


def test_trading_allowed_when_healthy():
    engine = PortfolioRiskEngine(RiskLimits())
    result = engine.check_trading_allowed(_healthy_state())
    assert result.approved is True


def test_emergency_stop_blocks_trading():
    engine = PortfolioRiskEngine(RiskLimits())
    state = _healthy_state(is_emergency_stopped=True)
    result = engine.check_trading_allowed(state)
    assert result.approved is False
    assert "emergency stop" in result.reason


def test_trading_halted_blocks_trading():
    engine = PortfolioRiskEngine(RiskLimits())
    state = _healthy_state(is_trading_halted=True)
    result = engine.check_trading_allowed(state)
    assert result.approved is False


def test_drawdown_breach_blocks_trading():
    engine = PortfolioRiskEngine(RiskLimits(max_drawdown=Decimal("0.10")))
    # 15% down from peak -> breaches a 10% limit.
    state = _healthy_state(peak_equity=Decimal("10000"), equity=Decimal("8500"))
    result = engine.check_trading_allowed(state)
    assert result.approved is False
    assert result.checks["max_drawdown"] is False


def test_daily_loss_breach_blocks_trading():
    engine = PortfolioRiskEngine(RiskLimits(max_daily_loss=Decimal("0.05")))
    state = _healthy_state(day_start_equity=Decimal("10000"), equity=Decimal("9000"))
    result = engine.check_trading_allowed(state)
    assert result.approved is False
    assert result.checks["max_daily_loss"] is False


def test_new_position_approved_within_limits():
    engine = PortfolioRiskEngine(RiskLimits(max_position_size=Decimal("0.10")))
    state = _healthy_state()
    result = engine.check_new_position(
        state, asset_symbol="BTC/USD", proposed_notional=Decimal("500")
    )
    assert result.approved is True


def test_new_position_rejected_over_max_position_size():
    engine = PortfolioRiskEngine(RiskLimits(max_position_size=Decimal("0.05")))
    state = _healthy_state()
    result = engine.check_new_position(
        state, asset_symbol="BTC/USD", proposed_notional=Decimal("1000")
    )
    assert result.approved is False
    assert result.checks["max_position_size"] is False


def test_new_position_rejected_over_max_open_positions():
    engine = PortfolioRiskEngine(RiskLimits(max_open_positions=2))
    state = _healthy_state(open_position_count=2)
    result = engine.check_new_position(
        state, asset_symbol="BTC/USD", proposed_notional=Decimal("100")
    )
    assert result.approved is False
    assert result.checks["max_open_positions"] is False


def test_new_position_rejected_over_asset_concentration():
    engine = PortfolioRiskEngine(RiskLimits(max_asset_concentration=Decimal("0.10")))
    state = _healthy_state(
        exposure_by_asset={"BTC/USD": Decimal("900")}, total_exposure=Decimal("900")
    )
    result = engine.check_new_position(
        state, asset_symbol="BTC/USD", proposed_notional=Decimal("200")
    )
    assert result.approved is False
    assert result.checks["max_asset_concentration"] is False


def test_new_position_rejected_over_portfolio_exposure():
    engine = PortfolioRiskEngine(RiskLimits(max_portfolio_exposure=Decimal("0.50")))
    state = _healthy_state(total_exposure=Decimal("4500"))
    result = engine.check_new_position(
        state, asset_symbol="ETH/USD", proposed_notional=Decimal("600")
    )
    assert result.approved is False
    assert result.checks["max_portfolio_exposure"] is False


def test_new_position_blocked_by_account_wide_halt_regardless_of_size():
    engine = PortfolioRiskEngine(RiskLimits())
    state = _healthy_state(is_trading_halted=True)
    result = engine.check_new_position(
        state, asset_symbol="BTC/USD", proposed_notional=Decimal("1")
    )
    assert result.approved is False
    assert result.reason == "trading halted"
