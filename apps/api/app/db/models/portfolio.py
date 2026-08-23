from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPKMixin


class PortfolioSnapshot(Base, UUIDPKMixin):
    __tablename__ = "portfolio_snapshots"

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    exposure: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=0)
    drawdown: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
