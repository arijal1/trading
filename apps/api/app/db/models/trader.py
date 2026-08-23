from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin


class Trader(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "traders"

    wallet_address: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str | None] = mapped_column(String(64))
    strategy_classification: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    consistency_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    is_followed: Mapped[bool] = mapped_column(default=False)


class TraderMetrics(Base, UUIDPKMixin):
    __tablename__ = "trader_metrics"

    trader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traders.id"), nullable=False)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    avg_return: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    avg_hold_time_seconds: Mapped[int | None] = mapped_column()
    num_trades: Mapped[int] = mapped_column(default=0)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )


class TraderTrade(Base, UUIDPKMixin):
    __tablename__ = "trader_trades"

    trader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traders.id"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))


class CopyTradeSignal(Base, UUIDPKMixin):
    __tablename__ = "copy_trade_signals"

    trader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traders.id"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    source_trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trader_trades.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column()
    price_deviation_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
