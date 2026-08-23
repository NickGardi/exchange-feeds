from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer

from app.services.hub import iso_utc


class QuoteView(BaseModel):
    exchange: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    received_at: datetime


class BestPriceResponse(BaseModel):
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    bid_exchange: str
    ask_exchange: str
    spread: float
    spread_bps: float
    mid: float
    ts: datetime
    quotes: list[QuoteView] = Field(default_factory=list)


class FeedStatusResponse(BaseModel):
    name: str
    connected: bool
    last_message_at: datetime | None = None
    last_quote_at: datetime | None = None
    last_error: str | None = None
    reconnects: int = 0
    connected_since: datetime | None = None
    disconnected_since: datetime | None = None
    up_seconds: float = 0

    @field_serializer(
        "last_message_at",
        "last_quote_at",
        "connected_since",
        "disconnected_since",
    )
    def _iso_times(self, value: datetime | None) -> str | None:
        return iso_utc(value)


class HealthResponse(BaseModel):
    status: str
    app: str
    symbols: list[str]
    feeds: list[FeedStatusResponse]
    postgres: bool
    redis: bool
    cassandra: bool = False
    tracked_quotes: int


class HistoryPoint(BaseModel):
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_exchange: str
    ask_exchange: str
    spread: Decimal
    mid: Decimal
    ts: datetime
