"""Import every model module so Alembic autogenerate sees full metadata."""
from app.db.models.audit import Alert, AuditLog, RiskEvent, SystemEvent  # noqa: F401
from app.db.models.backtest import Backtest, ModelVersion  # noqa: F401
from app.db.models.core import (  # noqa: F401
    Account,
    Asset,
    Candle,
    Configuration,
    Exchange,
    Market,
    SystemState,
    User,
)
from app.db.models.market_intel import MarketRegime, SentimentEvent  # noqa: F401
from app.db.models.portfolio import PortfolioSnapshot  # noqa: F401
from app.db.models.trader import CopyTradeSignal, Trader, TraderMetrics, TraderTrade  # noqa: F401
from app.db.models.trading import (  # noqa: F401
    Decision,
    Fill,
    Order,
    OrderEvent,
    Position,
    PositionEvent,
    Signal,
    Strategy,
)
