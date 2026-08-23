"""Prometheus metrics (brief Section 34/56: observability).

Every counter/gauge/histogram here is a plain module-level singleton,
registered once at import time against the default registry — the same
pattern `app/core/logging.py` uses for structlog configuration. Label
sets are deliberately bounded to fixed, small vocabularies (order side,
tick action, risk-check name, exit trigger) rather than anything
free-form (a raw error message, a client_order_id), since an unbounded
label value is a well-known way to quietly blow up a Prometheus
instance's cardinality.
"""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

ORDERS_SUBMITTED = Counter(
    "orders_submitted_total", "Orders created and sent to the adapter", ["side", "type"]
)
ORDERS_FILLED = Counter(
    "orders_filled_total", "Orders that received at least one fill", ["side"]
)
ORDERS_REJECTED = Counter("orders_rejected_total", "Orders rejected by the adapter", ["side"])

POSITIONS_OPENED = Counter("positions_opened_total", "Positions opened")
POSITIONS_EXITED = Counter(
    "positions_exited_total", "Positions closed by the exit engine", ["trigger"]
)
CAPITAL_RECOVERIES = Counter(
    "capital_recoveries_total", "Capital-recovery partial exits applied"
)

RISK_CHECK_REJECTIONS = Counter(
    "risk_check_rejections_total", "New-position risk checks that failed", ["check"]
)

PAPER_TICKS = Counter("paper_ticks_total", "PaperTradingSession.run_tick calls", ["action"])
PAPER_TICK_DURATION = Histogram(
    "paper_tick_duration_seconds", "Wall-clock duration of one run_tick call"
)

EMERGENCY_STOP_ACTIVE = Gauge(
    "emergency_stop_active", "1 if the emergency kill switch is currently engaged, else 0"
)
TRADING_HALTED = Gauge(
    "trading_halted", "1 if trading is currently halted (emergency stop or manual pause), else 0"
)

NOTIFICATIONS_SENT = Counter(
    "notifications_sent_total",
    "Notification delivery attempts by channel and outcome",
    ["channel", "delivered"],
)


def render_latest() -> bytes:
    return generate_latest()


__all__ = [
    "CAPITAL_RECOVERIES",
    "CONTENT_TYPE_LATEST",
    "EMERGENCY_STOP_ACTIVE",
    "NOTIFICATIONS_SENT",
    "ORDERS_FILLED",
    "ORDERS_REJECTED",
    "ORDERS_SUBMITTED",
    "PAPER_TICKS",
    "PAPER_TICK_DURATION",
    "POSITIONS_EXITED",
    "POSITIONS_OPENED",
    "RISK_CHECK_REJECTIONS",
    "TRADING_HALTED",
    "render_latest",
]
