"""Live-trading guard (brief Section 39) — the last gate before real money.

Every condition below must hold before a live order reaches an exchange.
The design rules, in order of importance:

1. **Fails closed.** The guard starts from "refused" and only returns
   permitted if it positively confirmed every check. An exception, a
   missing row, an unreadable setting, a `None` where a value was
   expected — all of these land on refusal, never on approval. Anything
   this code cannot verify, it treats as failed.
2. **Not bypassable from the order path.** `OrderManager.submit_order`
   calls this itself rather than trusting callers to. There is no
   "skip_guard" parameter and no alternate submission method — adding one
   would defeat the entire control, so the absence is deliberate and
   `tests/unit/test_live_guard.py` asserts it structurally.
3. **Every refusal names its cause.** A silent `False` would make an
   operator debug a kill switch by guesswork.

The default configuration cannot place a live order: `TRADING_MODE`
defaults to `paper`, and `LIVE_TRADING` / `TRADING_CONFIRMATION` /
`VALID_EXCHANGE_CREDENTIALS` / `RISK_LIMITS_VALID` all default to `False`
(`app/core/config.py`). Turning on live trading requires deliberately
flipping several independent switches, which is the point — see
`docs/LIVE_TRADING.md`.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.core.logging import get_logger
from app.db.models.core import Account, Exchange
from app.schemas.live_trading import GuardCheck, LiveTradingDecision
from app.services import system_state as system_state_service
from app.services.exchanges import credentials as credentials_service

logger = get_logger(__name__)


class LiveTradingRefusedError(RuntimeError):
    """A live order was attempted while the guard refused it.

    Carries the structured decision so callers can log/surface exactly
    which gate closed.
    """

    def __init__(self, decision: LiveTradingDecision) -> None:
        super().__init__(decision.summary)
        self.decision = decision


def _describe(failed: list[GuardCheck]) -> str:
    return ", ".join(check.value for check in failed)


class LiveTradingGuard:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def evaluate(
        self,
        db: AsyncSession,
        *,
        account: Account,
        exchange: Exchange | None,
        notional_value: Decimal,
    ) -> LiveTradingDecision:
        """Evaluate every Section 39 guardrail. Never raises: returns a
        refusal instead, so a caller cannot accidentally treat a thrown
        exception's absence as approval."""
        try:
            return await self._evaluate(
                db, account=account, exchange=exchange, notional_value=notional_value
            )
        except Exception as exc:  # noqa: BLE001 - fail closed on ANY error
            logger.error("live_guard_evaluation_failed", error=str(exc))
            return LiveTradingDecision(
                allowed=False,
                failed_checks=[],
                reason=(
                    f"guard evaluation raised {type(exc).__name__}; refusing the order. "
                    "An unverifiable guardrail is treated as a failed guardrail."
                ),
            )

    async def _evaluate(
        self,
        db: AsyncSession,
        *,
        account: Account,
        exchange: Exchange | None,
        notional_value: Decimal,
    ) -> LiveTradingDecision:
        s = self.settings
        failed: list[GuardCheck] = []

        if s.TRADING_MODE != TradingMode.LIVE:
            failed.append(GuardCheck.TRADING_MODE_IS_LIVE)
        if not s.LIVE_TRADING:
            failed.append(GuardCheck.LIVE_TRADING_ENABLED)
        if not s.TRADING_CONFIRMATION:
            failed.append(GuardCheck.TRADING_CONFIRMATION)
        if not s.VALID_EXCHANGE_CREDENTIALS:
            failed.append(GuardCheck.VALID_EXCHANGE_CREDENTIALS)
        if not s.RISK_LIMITS_VALID:
            failed.append(GuardCheck.RISK_LIMITS_VALID)
        if not s.EMERGENCY_STOP_AVAILABLE:
            failed.append(GuardCheck.EMERGENCY_STOP_AVAILABLE)

        # The kill switch outranks configuration: even a fully-enabled
        # live setup must not trade while stopped or halted.
        state = await system_state_service.get_or_create_state(db)
        if state.is_emergency_stopped:
            failed.append(GuardCheck.NOT_EMERGENCY_STOPPED)
        if state.is_trading_halted:
            failed.append(GuardCheck.NOT_TRADING_HALTED)

        # An account in paper mode must never route to a live venue, even
        # if every global switch says live is on.
        if account.mode != "live":
            failed.append(GuardCheck.ACCOUNT_IS_LIVE_MODE)

        # No exchange row, no credentials, or withdrawal-capable keys are
        # each independently disqualifying.
        if exchange is None:
            failed.append(GuardCheck.WITHDRAWALS_DISABLED)
            failed.append(GuardCheck.VALID_EXCHANGE_CREDENTIALS)
        else:
            if not exchange.withdrawals_disabled or not s.DISABLE_WITHDRAWALS:
                failed.append(GuardCheck.WITHDRAWALS_DISABLED)
            if not credentials_service.has_credentials(exchange):
                if GuardCheck.VALID_EXCHANGE_CREDENTIALS not in failed:
                    failed.append(GuardCheck.VALID_EXCHANGE_CREDENTIALS)

        # Per-order capital cap. A non-positive notional is nonsensical
        # for a live order and is refused rather than treated as "small
        # enough to be safe".
        max_live = Decimal(str(s.MAX_LIVE_CAPITAL))
        if notional_value <= 0 or notional_value > max_live:
            failed.append(GuardCheck.WITHIN_MAX_LIVE_CAPITAL)

        if failed:
            decision = LiveTradingDecision(
                allowed=False, failed_checks=failed, reason=_describe(failed)
            )
            logger.warning(
                "live_trading_refused",
                account_id=str(account.id),
                failed_checks=[c.value for c in failed],
            )
            return decision

        logger.info(
            "live_trading_permitted",
            account_id=str(account.id),
            notional_value=str(notional_value),
        )
        return LiveTradingDecision(allowed=True, reason="all Section 39 guardrails satisfied")

    async def require(
        self,
        db: AsyncSession,
        *,
        account: Account,
        exchange: Exchange | None,
        notional_value: Decimal,
    ) -> None:
        """Raise `LiveTradingRefusedError` unless live trading is permitted."""
        decision = await self.evaluate(
            db, account=account, exchange=exchange, notional_value=notional_value
        )
        if not decision.allowed:
            raise LiveTradingRefusedError(decision)


def is_live_order(account: Account, settings: Settings | None = None) -> bool:
    """Whether an order for this account would hit a real venue.

    Both conditions are required, and either one being false makes the
    order a paper order. This is the single definition used by the order
    path, so "is this live?" can never be answered inconsistently in two
    places.
    """
    s = settings or get_settings()
    return account.mode == "live" and s.TRADING_MODE == TradingMode.LIVE
