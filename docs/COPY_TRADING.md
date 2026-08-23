# Copy-Trading Decision Engines (Phase 4, brief Sections 10-13)

`app/services/copy_trading/`. Scoped deliberately to *decisions*, not
data acquisition — there is no trader-data feed wired up yet (no
on-chain indexer, no exchange leaderboard API), so nothing here executes
a real copy trade. What's built is the pure decision logic a future
data-feed integration will plug into, tested against hand-built trade/
signal fixtures so it doesn't have to wait on that integration to be
correct.

## Trader performance tracking (Section 10)

`trader_tracking.py`. `compute_trader_metrics` is a pure function over a
trader's closed trades (`ClosedTrade`, a minimal shape tests can build
without touching the database):

- **Win rate, profit factor** (gross profit / gross loss, capped at
  `_UNBOUNDED_PROFIT_FACTOR = 999.0` when there are no losing trades at
  all rather than returning `inf`), **average return %**.
- **Max drawdown** off a *dimensionless compounding equity curve*
  (starts at 1.0, compounds each trade's `realized_pnl / notional` in
  `closed_at` order) rather than raw dollar P&L — this is what makes
  drawdown comparable across traders who deploy completely different
  amounts of capital. Trades are explicitly sorted by `closed_at` before
  computing the curve; iterating in whatever order they were queried in
  would silently mis-order the compounding and produce a wrong number
  (`tests/unit/test_trader_tracking.py::test_drawdown_ordering_respects_closed_at_not_list_order`
  exists specifically to catch a regression here).
- **Consistency score** — `1 / (1 + stdev(returns_pct))`, a documented
  heuristic (not a statistically validated measure) that scores lower
  return volatility higher.

`refresh_trader_metrics` is the DB-facing wrapper: loads a trader's
closed `trader_trades` (open trades — no `closed_at` — are excluded),
computes metrics, and inserts a new `trader_metrics` row. This is
append-only by design, not an upsert — the schema models `trader_metrics`
as rolling performance history, so each refresh is a new data point
rather than overwriting the last one.

## Copy-trade decisioning (Sections 11-13)

`copy_trade_decision.py`.

- **`compute_trader_score`** reduces the brief's Section 11 formula
  sketch (`performance * consistency * risk_adjusted_return *
  liquidity * execution_quality - drawdown_penalty - volatility_penalty
  - suspicious_activity_penalty - concentration_penalty`) to the subset
  actually computable from `trader_trades` history: performance
  (win rate × capped profit factor), consistency, and a drawdown
  penalty. Liquidity, execution quality, suspicious-activity detection,
  and wallet-concentration all need external market-depth or on-chain
  data this project doesn't have a source for yet — the same class of
  gap the Token Risk Engine has (`docs/ARCHITECTURE.md`). A trader with
  no closed-trade history scores exactly `0.0` — nothing to score yet,
  not a passing grade by default.
- **`evaluate_copy_candidate`** gates eligibility on `MIN_TRADER_SCORE`,
  then guards against chasing a trade whose price has already moved too
  far past the followed trader's own entry (`MAX_COPY_PRICE_DEVIATION_PERCENT`,
  Section 12) — a trader who bought at $100 and is now at $130 shouldn't
  trigger a copy-buy at $130. Also computes `latency_ms` (signal-to-
  evaluation delay), tracked per Section 12's `COPY_LATENCY_MS` even
  though nothing acts on it yet.
- **`resolve_consensus`** implements Section 13's requirement that
  multiple followed traders disagreeing on the same asset never resolves
  as "first signal wins": each trader's signal is weighted by their score,
  and the result is `NO_TRADE` unless the weighted buy/sell gap clears
  `min_consensus_difference`.

## Scope (documented, not oversights)

- **No trader-data source.** `trader_trades` rows have to come from
  somewhere real (on-chain indexer, exchange leaderboard API) before any
  of this runs against live data; Section 4's "don't reverse-engineer
  private endpoints" constraint applies here too.
- **No copy-execution wiring.** `evaluate_copy_candidate` /
  `resolve_consensus` produce decisions; routing an approved decision
  into `OrderManager` the way `PaperTradingSession` does for the
  strategy engine is unbuilt, since it depends on the data source above.
- **No HTTP surface yet** — `GET /traders`, `GET /traders/{id}`,
  `GET /copy-trading`, `POST /copy-trading/follow` remain in
  `docs/API_DESIGN.md`'s "Planned" table for the same reason.
