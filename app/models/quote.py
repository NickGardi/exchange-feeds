from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True, frozen=True)
class Quote:
    exchange: str
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    received_at: datetime
    exchange_ts: datetime | None = None

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(slots=True)
class BestPrice:
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    bid_exchange: str
    ask_exchange: str
    ts: datetime
    quotes: list[Quote] = field(default_factory=list)

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> Decimal:
        if self.mid == 0:
            return Decimal("0")
        return (self.spread / self.mid) * Decimal("10000")

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "bid": _num(self.bid),
            "ask": _num(self.ask),
            "bid_size": _num(self.bid_size),
            "ask_size": _num(self.ask_size),
            "bid_exchange": self.bid_exchange,
            "ask_exchange": self.ask_exchange,
            "spread": _num(self.spread),
            "spread_bps": _num(self.spread_bps),
            "mid": _num(self.mid),
            "ts": self.ts.isoformat(),
            "quotes": [
                {
                    "exchange": q.exchange,
                    "bid": _num(q.bid),
                    "ask": _num(q.ask),
                    "bid_size": _num(q.bid_size),
                    "ask_size": _num(q.ask_size),
                    "received_at": q.received_at.isoformat(),
                }
                for q in self.quotes
            ],
        }


def _num(value: Decimal) -> float:
    return float(value)
