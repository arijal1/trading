# Paper Trading (Phase 4)

`app/services/execution/paper_trading_session.py`. `PaperTradingSession`
runs one decision cycle for one `(account, market, timeframe)` per call —
there is no scheduler ticking every followed market for every account yet
(same "no worker queue" boundary `docs/BACKTESTING.md` already documents
for backtests). It ties together everything built in Phases 2-4:

```
candles -> TechnicalAnalysisEngine
        -> if a position is open:
             PositionManager.advance_and_evaluate_exit
               (ratchets the trailing stop, then ExitEngine.evaluate)
             if should_exit: OrderManager.submit_order(SELL, full qty)
                              -> PositionManager.apply_sell_fill
             else: ProfitManager.evaluate_capital_recovery
                   if should_recover: OrderManager.submit_order(SELL, partial qty)
                                      -> ProfitManager.apply_capital_recovery_fill
                   else: HOLD
        -> else:
             generate_all_signals -> StrategyAggregator.aggregate
             if not BUY: HOLD
             compute_dynamic_stop_loss (ATR) -> build_portfolio_state
               -> calculate_position_size -> PortfolioRiskEngine.check_new_position
             if approved: OrderManager.submit_order(BUY) -> PositionManager.apply_buy_fill
             else: SKIPPED_RISK / SKIPPED_SIZE
  -> always: build_portfolio_state + record_snapshot, regardless of outcome
```

Every fill goes through `OrderManager` (idempotent on `client_order_id`,
Phase 4), so a tick can safely be retried. `TickResult.action` is one of
`OPENED`, `EXIT`, `CAPITAL_RECOVERED`, `HOLD`, `SKIPPED_RISK`,
`SKIPPED_SIZE`, `NO_SIGNAL`, `INSUFFICIENT_DATA` — every branch, not just
the "something happened" ones, so a caller can distinguish "the market
didn't set up" from "risk/size rejected it" from "not enough history yet".

## Order Manager

`app/services/execution/order_manager.py`. `submit_order` is idempotent on
`client_order_id`: a retried submission with the same ID never places a
second exchange order. The subtle part is the create race — two concurrent
callers can both attempt to insert the same `client_order_id` row, and
whichever loses must not also call the adapter. `_create_order` returns
`(order, created_by_me: bool)` explicitly rather than inferring "did I
create this" from the order's status (a `NEW` status is ambiguous — it
could mean either), and only the winner proceeds to `_place`. If an order
is left `SUBMITTED`/`PARTIALLY_FILLED` with no `exchange_order_id` to
reconcile against, `OrderReconciliationRequiredError` is raised rather
than ever silently resubmitting — verified with real concurrent
`asyncio.gather` regression tests against separate DB sessions
(`tests/integration/test_order_manager.py`), not just sequential retries.

## Position Manager

`app/services/execution/position_manager.py`. Bridges fills to a
persisted `Position` row and re-evaluates exits against it.
`apply_buy_fill` opens a new position or adds to an existing one with a
weighted-average entry price; a fresh add refreshes the stop/target/
trailing config to the new values rather than blending them, since a new
add is a new risk decision. Exit-engine state — `stop_price`,
`take_profit_price`, `trailing_stop_pct`, `highest_price_since_entry`,
`max_hold_seconds` — was added directly to the `positions` table
(migration `060db36f1e44_add_exit_engine_state_columns_to_positions`) so
it survives between ticks instead of living only in memory for the
duration of one process, matching `ExitEngine`'s stateless design
(`docs/STRATEGY_ENGINE.md`).

## Profit Manager (capital recovery)

`app/services/portfolio/profit_manager.py` (brief Sections 2, 19, 42).
Once a position clears `min_profit_before_recovery`, `evaluate_capital_recovery`
proposes selling *just enough* to recover `capital_recovery_target` of the
original capital (net of estimated fees/slippage), never the whole
position — it explicitly refuses to propose a sell that would liquidate
everything or leave a remainder below `min_position_value`, waiting for
more profit margin instead. `apply_capital_recovery_fill` transitions the
remainder to `PROFIT_RUNNER`, clears any fixed take-profit target, and
hands it to the trailing stop — a "house money" position, never treated
as risk-free.

## Portfolio State Builder

`app/services/portfolio/state_builder.py`. `build_portfolio_state`
constructs the same `PortfolioState` snapshot the backtest engine builds
in memory, but from the database:

- **Cash is never a mutable stored balance column.** It's reconstructed
  from `starting_equity` plus every buy/sell fill's signed cost/proceeds
  via a SQL `case()` aggregation over the fill ledger, so it can never
  drift from what orders actually did.
- **Peak / day-start / week-start equity** come from the `portfolio_snapshots`
  history, written by `record_snapshot` after every tick regardless of
  outcome — this can't be stubbed out given the platform's
  capital-preservation-first mandate, since `PortfolioRiskEngine`'s
  drawdown/daily-loss/weekly-loss checks depend on it.
- **Emergency-stop / trading-halt** are read from `system_state` on every
  build, so a kill switch takes effect on the very next tick.

## A real timing coupling, not a bug

`_consider_entry` sizes the stop/position off the *latest synced candle's*
close. `MockExchangeAdapter.place_market_buy` fills at
`get_market_price(now)` — the real wall clock, not the candle's
timestamp. In normal operation (sync candles, then tick) these are
seconds-to-minutes apart and immaterial. But a caller that ticks against
candle history anchored to an old fixed date (as several of this phase's
tests deliberately do, for full reproducibility — see
`tests/integration/test_paper_trading_session.py`) will see the two
diverge sharply, since the mock adapter's synthetic price is a pure
function of `(symbol, timeframe, timestamp)`. This is why those tests
sync a recent, near-`now` candle range rather than trusting a stop/entry
relationship computed against backdated candles.

## Scope (documented, not oversights)

- **One `(account, market, timeframe)` per call.** No scheduler yet
  (Phase 5+ background worker, per `docs/ARCHITECTURE.md`'s tech-stack
  table); a real deployment ticks each followed market on a timer.
- **LONG-only, one open position per `(account, asset)`**, matching
  `PositionExitState`'s scope in `docs/STRATEGY_ENGINE.md`.
- **No live-price feed outside a tick.** `GET /accounts/{id}/portfolio`
  marks open positions at their own average entry price rather than a
  fresh quote, since there's no standalone quote endpoint yet — a real
  mark-to-market read would need one.
- **Accounts are created directly in the DB for now** — no onboarding
  endpoint yet, matching the same gap already documented for markets/
  exchanges in Phase 2 (`docs/API_DESIGN.md`).

## API

See `docs/API_DESIGN.md`'s "Implemented in Phase 4" table:
`GET /accounts/{id}`, `GET /accounts/{id}/portfolio`,
`GET /accounts/{id}/positions`, `GET /accounts/{id}/orders`,
`GET /accounts/{id}/trades`, `POST /accounts/{id}/paper/tick`.
