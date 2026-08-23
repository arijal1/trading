# Monitoring (Phase 5, brief Section 34/56)

`GET /metrics` — Prometheus text-format exposition
(`app/core/metrics.py`, `app/api/metrics.py`). Deliberately mounted
outside `/api/v1`: Prometheus scrape configs assume a fixed, unversioned
path, and versioning it would just mean every scrape config has to be
updated in lockstep with the API version for no benefit.

## What's exposed

| Metric | Type | Labels | What it means |
|---|---|---|---|
| `orders_submitted_total` | Counter | `side`, `type` | Orders created and sent to the adapter (`OrderManager.submit_order`) |
| `orders_filled_total` | Counter | `side` | Orders that received at least one fill |
| `orders_rejected_total` | Counter | `side` | Orders rejected by the adapter (`ExchangeAdapterError`) |
| `positions_opened_total` | Counter | — | Positions opened by `PaperTradingSession` |
| `positions_exited_total` | Counter | `trigger` | Positions closed, by exit trigger (stop-loss, trailing-stop, take-profit, max-hold-time, trend-reversal, momentum-failure) |
| `capital_recoveries_total` | Counter | — | Capital-recovery partial exits applied (`docs/PAPER_TRADING.md`) |
| `risk_check_rejections_total` | Counter | `check` | New-position risk checks that failed, by check name (`max_drawdown`, `max_daily_loss`, `max_open_positions`, etc. — the fixed set `PortfolioRiskEngine` checks) |
| `paper_ticks_total` | Counter | `action` | `PaperTradingSession.run_tick` calls, by `TickAction` (`OPENED`/`EXIT`/`CAPITAL_RECOVERED`/`HOLD`/`SKIPPED_RISK`/`SKIPPED_SIZE`/`NO_SIGNAL`/`INSUFFICIENT_DATA`) |
| `paper_tick_duration_seconds` | Histogram | — | Wall-clock duration of one `run_tick` call |
| `emergency_stop_active` | Gauge | — | 1 if the emergency kill switch is currently engaged, else 0 |
| `trading_halted` | Gauge | — | 1 if trading is halted (emergency stop or manual pause), else 0 |
| `notifications_sent_total` | Counter | `channel`, `delivered` | Notification delivery attempts (`docs/NOTIFICATIONS.md`), whether or not they succeeded |

Every label set is a fixed, small, known-in-advance vocabulary (order
side, tick action, risk-check name, exit trigger) — never a raw error
message, a `client_order_id`, or anything else unbounded. Unbounded label
values are a well-known way to quietly blow up a Prometheus instance's
cardinality, so this is a deliberate constraint, not an oversight, on
every metric added here.

The two gauges are kept fresh on every read, not just every mutation:
`system_state.get_or_create_state` — called by `GET /system/status` as
well as by every mutation — sets them, so a plain status check after a
process restart still reports the correct value rather than 0 until the
next state change.

## Suggested Grafana panels

No live Grafana instance exists in this environment to export a verified
dashboard JSON against, so this is a documented starter panel list
instead of a checked-in `.json` — verify panel queries against a real
Prometheus instance before importing:

1. **Trading activity** — rate of `paper_ticks_total` by `action`,
   stacked; makes OPENED/EXIT/HOLD/SKIPPED_* proportions visible at a
   glance.
2. **Order funnel** — `orders_submitted_total` vs `orders_filled_total`
   vs `orders_rejected_total`, by `side`.
3. **Exit triggers** — rate of `positions_exited_total` by `trigger`;
   a spike in `STOP_LOSS` relative to `TAKE_PROFIT` is a strategy-health
   signal worth alerting on.
4. **Risk rejections** — rate of `risk_check_rejections_total` by
   `check`; sustained rejection on one check (e.g. `max_drawdown`) means
   the account is pinned against a limit, not that risk checks are
   working as designed.
5. **Kill switch state** — single-stat panels on `emergency_stop_active`
   / `trading_halted`, ideally wired to an alert rule (Section 40's
   "capital preservation first" mandate makes this the single most
   important panel on the board).
6. **Tick latency** — `histogram_quantile` over
   `paper_tick_duration_seconds_bucket` (p50/p95/p99).
7. **Notification delivery health** — rate of
   `notifications_sent_total{delivered="false"}` by `channel`; a rising
   Telegram failure rate should be visible before anyone notices they
   stopped getting alerts.

## Scope (documented, not oversights)

- **No Alertmanager rules checked in.** The panel list above names what's
  worth alerting on; wiring actual alert rules is Phase 6+ (production
  deployment) territory, per `docs/ARCHITECTURE.md`'s roadmap.
- **No per-account metric breakdown.** Every counter here is process-wide,
  not labeled by `account_id` — a per-account label would be unbounded
  cardinality once there's more than a handful of accounts, and there's
  no dashboard yet that would consume it.
- **Structured logs (`docs/ARCHITECTURE.md`'s Section 12) remain the
  source of truth for anything not captured here** — every notification,
  every order/position event, every audit-log row is still written to
  `system_events`/`order_events`/`position_events`/`audit_logs` regardless
  of what's exported as a metric.
