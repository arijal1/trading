from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    accounts: Mapped[list[Account]] = relationship(back_populates="user")


class Account(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="paper", nullable=False)
    base_currency: Mapped[str] = mapped_column(String(16), default="USD", nullable=False)
    starting_equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=0)

    user: Mapped[User] = relationship(back_populates="accounts")


class Exchange(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "exchanges"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False, default="mock")
    api_key_encrypted: Mapped[str | None] = mapped_column(String(1024))
    api_secret_encrypted: Mapped[str | None] = mapped_column(String(1024))
    withdrawals_disabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Asset(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("symbol", "chain", name="uq_asset_symbol_chain"),)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    chain: Mapped[str | None] = mapped_column(String(32))
    contract_address: Mapped[str | None] = mapped_column(String(128))
    decimals: Mapped[int | None] = mapped_column()
    risk_score: Mapped[int | None] = mapped_column()


class Market(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "markets"
    __table_args__ = (
        UniqueConstraint("exchange_id", "symbol", name="uq_market_exchange_symbol"),
    )

    exchange_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exchanges.id"), nullable=False)
    base_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    quote_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_rules: Mapped[dict | None] = mapped_column(JSONB)


class Candle(Base, UUIDPKMixin):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("market_id", "timeframe", "ts", name="uq_candle_market_tf_ts"),
    )

    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("markets.id"), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)


class Configuration(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "configuration"

    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(128))


class SystemState(Base, UUIDPKMixin, TimestampMixin):
    """Singleton row (Section 40: emergency kill switch)."""

    __tablename__ = "system_state"

    is_emergency_stopped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_trading_halted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512))
    set_by: Mapped[str | None] = mapped_column(String(128))
    set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
