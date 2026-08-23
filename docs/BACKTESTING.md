# Backtesting Engine (Phase 3)

`app/services/backtesting/engine.py`. Walks forward bar by bar over
historical candles from the `candles` table (ingested by Phase 2's
`MarketDataEngine`). At bar `i`, only `candles[:i+1]` is ever visible to
the technical analysis / strategy layer, and any decision made from bar
`i`'s close fills at bar `i+1`'s open — the engine cannot act on
information from the future (brief Section 36's "no look-ahead" rule).

## Per-bar flow

```
bar i closes
  -> TechnicalAnalysisEngine.analyze(candles[i-window+1 : i+1])
  -> if a position is open:
       advance_position_state (ratchet trailing stop off bar i's high)
       ExitEngine.evaluate (checks bar i's high/low/close):
         stop-loss / trailing-stop / take-profit -> fills within bar i
           itself, at the stop/target price (these are resting orders;
           the bar is already fully known, so this is not look-ahead)
         max-hold-time / trend-reversal / momentum-failure -> fills at
           bar i+1's open (decisions made from the close, like entries)
     else:
       generate_all_signals -> StrategyAggregator.aggregate
       if BUY: compute_dynamic_stop_loss (ATR) -> calculate_position_size
               -> PortfolioRiskEngine.check_new_position -> open at bar i+1's open
  -> mark-to-market equity recorded for this bar
```

Fees come from the exchange adapter's `get_fees()` (currently the mock
adapter — see `docs/EXCHANGE_ADAPTER.md`). Slippage is modeled explicitly
as `slippage_pct` applied against the trade direction on every fill
(worse price when buying, worse price when selling) — this is independent
of the adapter, since backtests fill against the candles' own OHLCV, not
the adapter's live-price simulation.

**Intrabar stop/target detection matters.** An earlier version of this
engine checked stop-loss/take-profit against only the bar's close, so a
bar that dipped through the stop and recovered by its close silently
skipped the exit — understating realized risk and overstating backtested
performance (a real bug, found and fixed via review; see
`docs/STRATEGY_ENGINE.md`'s exit-engine section for the fix and its
`fills_intrabar` mechanism). If a single bar's range crosses both the
stop and the take-profit, the engine conservatively assumes the stop was
hit first — there's no tick-level data to resolve the actual order.

## Scope (documented, not oversights)

- **No partial fills.** Every fill is assumed complete. Needs a
  liquidity/order-book model this phase doesn't have.
- **No latency simulation.** Fills are instant at the next bar's open.
- **"Walk-forward" here means no-look-ahead execution, not walk-forward
  *optimization*.** The strategies are fixed rule-based heuristics (see
  `docs/STRATEGY_ENGINE.md`), not fitted parameters, so there's nothing
  to re-fit per rolling window.
- **No capital recovery / staged profit-locking** (Section 2/19/42) and
  **no copy-trading delay** (Section 12) — both depend on machinery
  that's explicitly Phase 4 (`ProfitManager`, trader tracking).
- **Single symbol per run.** No cross-asset correlation, no portfolio-of-
  backtests, no survivorship bias to control for yet (nothing is being
  selected from a universe).
- **No RNG, so no seed.** Every input to the simulation (candles, fees,
  strategy rules) is deterministic; the same candles and config always
  produce the same trades. A seed will be reintroduced if/when partial-
  fill or latency randomness is added.

## Known cost characteristic

Recomputing the full technical-analysis indicator suite at every bar
(rather than updating indicators incrementally) is the dominant cost — a
300-bar backtest takes a few seconds. This is correct (it's what "no
look-ahead" requires) but not fast; incremental/vectorized indicator
updates are a legitimate future optimization once backtest volume
justifies it.

## API

`POST /api/v1/backtests` — runs synchronously in the request (no worker
queue exists yet; see `docs/API_DESIGN.md`) against a market's stored
candles, persists to the `backtests` table against a get-or-created
`technical_composite_v1` `strategies` row, and returns the full result.
`GET /api/v1/backtests/{id}` reads it back. See `docs/API_DESIGN.md` for
the request/response shape.

`app/services/strategy/registry.py`'s `get_or_create_composite_strategy`
upserts (`INSERT ... ON CONFLICT DO NOTHING` against a `(name, version)`
unique constraint) rather than check-then-insert, so that two concurrent
first-ever `/backtests` requests can't both observe no existing row and
both insert a `technical_composite_v1` strategy — a real race found via
review and fixed, with a regression test
(`test_concurrent_first_callers_never_create_duplicate_rows`) that runs
10 real concurrent DB sessions against it.
