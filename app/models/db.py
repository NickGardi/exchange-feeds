from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (Index("ix_price_snapshots_symbol_ts", "symbol", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    bid: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    ask: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    bid_size: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    ask_size: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    bid_exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    ask_exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    spread: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    mid: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quotes_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PriceBar(Base):
    """1-minute bars written by Airflow from Cassandra ticks."""

    __tablename__ = "price_bars"

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(32), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)


class FeedEvent(Base):
    """Disconnect / reconnect / large-move events for later inspection."""

    __tablename__ = "feed_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
