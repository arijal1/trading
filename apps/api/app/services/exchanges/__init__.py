"""Exchange/broker abstraction layer (brief Section 4).

`base.ExchangeAdapter` is the single interface every exchange integration
implements. `mock.MockExchangeAdapter` is the only implementation shipped
so far: no specific exchange has been chosen, and Section 4 explicitly
forbids reverse-engineering private endpoints or scraping authenticated
interfaces to fake support for one. A real adapter is added once a named
exchange with an official, authenticated trading API is selected.
"""
from app.services.exchanges.base import ExchangeAdapter  # noqa: F401
from app.services.exchanges.mock import MockExchangeAdapter  # noqa: F401
