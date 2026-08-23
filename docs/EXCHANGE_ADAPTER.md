# Exchange Adapter (Phase 2)

`app/services/exchanges/base.py` defines `ExchangeAdapter`, the single
interface every exchange/broker integration implements (brief Section 4):
balances, positions, price, order book, OHLCV, all four order-placement
variants, cancel, order status, open orders, trading rules, symbols, fees,
account status. Every method returns a typed schema from
`app/schemas/exchange.py` — never a raw exchange response — so nothing
downstream depends on any one exchange's shape.

## Why only a mock adapter exists so far

No specific exchange has been named for this project, and the brief
(Section 4) explicitly forbids reverse-engineering private endpoints or
scraping an authenticated interface to fake support for one. So Phase 2
ships exactly one implementation: `MockExchangeAdapter`
(`app/services/exchanges/mock.py`). A real adapter is added once a named
exchange with an official, authenticated trading API is chosen — at that
point it drops in behind the same interface with no changes needed to the
market data engine, technical analysis engine, or (in later phases) the
order manager.

## MockExchangeAdapter properties

- **Deterministic**: every value (price, OHLCV bar, order book level) is a
  pure function of `(symbol, timeframe, timestamp)` via a seeded hash, not
  of call order or wall-clock time. The same request always returns the
  same data, which is what makes `MarketDataEngine.sync_candles` testable
  as idempotent and what makes indicator/engine tests reproducible.
- **No network calls.** Nothing about it resembles scraping or hitting a
  real venue.
- **`can_withdraw` is always `False`** on `get_account_status()` — Section
  33/39 requires trading credentials to never carry withdrawal permission,
  and the mock adapter models that constraint even though it isn't a real
  credential.
- Market orders fill immediately at the synthetic current price; limit
  orders fill immediately only if already marketable, otherwise they sit
  `SUBMITTED` until cancelled (no partial-fill simulation yet — that's a
  Phase 4 paper-trading engine concern, not an adapter concern).

## What's not implemented yet

Order placement here is in-memory only (no DB persistence, no
idempotency-key handling at the adapter level — that belongs to the Order
Manager in Phase 4). Rate limiting, reconnect/backoff, and WebSocket
streaming (Section 53) are not needed by a mock adapter and will be added
alongside the first real one.
