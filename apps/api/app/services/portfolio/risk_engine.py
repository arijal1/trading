"""Portfolio risk engine (brief Section 21).

Pure, DB-agnostic: takes a `PortfolioState` snapshot and `RiskLimits`, and
answers whether trading is currently allowed and whether a specific
proposed position would breach a limit. It has no opinion about where the
snapshot came from — the backtesting engine builds one in memory per bar;
a future live/paper engine (Phase 4) builds one from the database. Every
rejection carries the specific check(s) that failed, never a bare False.
"""
from __future__ import annotations

from decimal import Decimal

from app.schemas.portfolio import PortfolioState, RiskCheckResult, RiskLimits


class PortfolioRiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def check_trading_allowed(self, state: PortfolioState) -> RiskCheckResult:
        """Account-wide checks that gate ANY new entry, regardless of size/asset."""
        if state.is_emergency_stopped:
            return RiskCheckResult(
                approved=False, reason="emergency stop active", checks={"emergency_stop": False}
            )
        if state.is_trading_halted:
            return RiskCheckResult(
                approved=False, reason="trading halted", checks={"trading_halted": False}
            )

        checks: dict[str, bool] = {}

        drawdown = self._fractional_decline(state.peak_equity, state.equity)
        checks["max_drawdown"] = drawdown <= self.limits.max_drawdown

        daily_loss = self._fractional_decline(state.day_start_equity, state.equity)
        checks["max_daily_loss"] = daily_loss <= self.limits.max_daily_loss

        weekly_loss = self._fractional_decline(state.week_start_equity, state.equity)
        checks["max_weekly_loss"] = weekly_loss <= self.limits.max_weekly_loss

        return self._result_from_checks(checks)

    def check_new_position(
        self, state: PortfolioState, *, asset_symbol: str, proposed_notional: Decimal
    ) -> RiskCheckResult:
        """Position-specific checks, layered on top of the account-wide gate."""
        trading_check = self.check_trading_allowed(state)
        if not trading_check.approved:
            return trading_check

        checks = dict(trading_check.checks)
        checks["max_open_positions"] = state.open_position_count < self.limits.max_open_positions

        if state.equity <= 0:
            checks["max_position_size"] = False
            checks["max_portfolio_exposure"] = False
            checks["max_asset_concentration"] = False
            return self._result_from_checks(checks)

        position_pct = proposed_notional / state.equity
        checks["max_position_size"] = position_pct <= self.limits.max_position_size

        exposure_pct = (state.total_exposure + proposed_notional) / state.equity
        checks["max_portfolio_exposure"] = exposure_pct <= self.limits.max_portfolio_exposure

        existing_asset_exposure = state.exposure_by_asset.get(asset_symbol, Decimal(0))
        concentration_pct = (existing_asset_exposure + proposed_notional) / state.equity
        checks["max_asset_concentration"] = concentration_pct <= self.limits.max_asset_concentration

        return self._result_from_checks(checks)

    @staticmethod
    def _fractional_decline(baseline: Decimal, current: Decimal) -> Decimal:
        if baseline <= 0:
            return Decimal(0)
        return max(Decimal(0), (baseline - current) / baseline)

    @staticmethod
    def _result_from_checks(checks: dict[str, bool]) -> RiskCheckResult:
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            return RiskCheckResult(
                approved=False, reason=f"breached: {', '.join(failed)}", checks=checks
            )
        return RiskCheckResult(approved=True, checks=checks)
