from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin


class Strategy(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "strategies"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_strategy_name_version"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    parameters: Mapped[dict | None] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Signal(Base, UUIDPKMixin):
    __tablename__ = "signals"

    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    data_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_age_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Decision(Base, UUIDPKMixin):
    __tablename__ = "decisions"

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    # BUY/SELL/HOLD/REDUCE/EXIT/SKIP
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSONB, default=list)
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    expected_reward: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    expected_risk: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    position_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    trailing_stop: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    time_horizon: Mapped[str | None] = mapped_column(String(32))
    strategy: Mapped[str | None] = mapped_column(String(64))
    supporting_signals: Mapped[dict | None] = mapped_column(JSONB)
    model_version: Mapped[str | None] = mapped_column(String(64))
    policy_result: Mapped[str | None] = mapped_column(String(32))  # APPROVED/REJECTED
    policy_reject_reason: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Order(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "orders"

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decisions.id"))
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(128))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY/SELL
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # MARKET/LIMIT
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    status: Mapped[str] = mapped_column(String(24), default="NEW", nullable=False)
    error: Mapped[str | None] = mapped_column(String(512))


class OrderEvent(Base, UUIDPKMixin):
    __tablename__ = "order_events"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Fill(Base, UUIDPKMixin):
    __tablename__ = "fills"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=0)
    slippage: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    filled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Position(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "positions"

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="OPENING", nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, default=0)
    avg_entry_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, default=0)
    capital_recovered: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=0)
    profit_locked: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=0)
    # Exit-engine state (brief Sections 17-19), persisted so it survives
    # between paper-trading ticks rather than living only in memory.
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    take_profit_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    trailing_stop_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    highest_price_since_entry: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    max_hold_seconds: Mapped[int | None] = mapped_column()


class PositionEvent(Base, UUIDPKMixin):
    __tablename__ = "position_events"

    position_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("positions.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
