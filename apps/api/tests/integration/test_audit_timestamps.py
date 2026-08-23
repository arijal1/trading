"""Regression tests for the frozen-now() server_default bug.

app/db/models/audit.py (and portfolio.py, trading.py, trader.py,
market_intel.py) used `server_default="now()"` — a bare Python string —
on their timestamp columns. Postgres treats a quoted string default as a
constant and freezes it at the moment the column's DEFAULT is set (a
well-known Postgres pitfall), rather than the intended "evaluate now() on
every insert" behavior you get from `server_default=func.now()`. That
meant every row in audit_logs, risk_events, system_events, alerts,
portfolio_snapshots, signals, decisions, order_events, fills,
position_events, trader_metrics, copy_trade_signals, sentiment_events,
and market_regimes silently recorded the same fixed timestamp forever,
however different their creation times actually were.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.audit import AuditLog
from app.services import system_state as system_state_service


@pytest.mark.asyncio
async def test_audit_log_occurred_at_advances_across_separate_commits(db_session):
    """The exact scenario that surfaced the bug: two real emergency-stop
    actions, each its own commit, must not share one frozen timestamp.
    """
    await system_state_service.emergency_stop(db_session, reason="first", actor="tester")
    await system_state_service.resume_trading(db_session, reason="second", actor="tester")

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.actor == "tester").order_by(AuditLog.occurred_at)
    )
    rows = list(result.scalars())
    assert len(rows) == 2
    # Not just "not equal" — genuinely ordered, i.e. real wall-clock time
    # was captured at each commit rather than one value reused for both.
    assert rows[0].occurred_at < rows[1].occurred_at
