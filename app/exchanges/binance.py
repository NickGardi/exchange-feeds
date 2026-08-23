from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from decimal import Decimal

from app.exchanges.base import BaseFeed, load_json, parse_decimal
from app.exchanges.symbols import binance_to_normalized
from app.models.quote import Quote


class BinanceFeed(BaseFeed):
    name = "binance"

    def ws_url(self) -> str:
        streams = "/".join(f"{s.lower()}@bookTicker" for s in self.native_symbols)
        return f"wss://stream.binance.com:9443/stream?streams={streams}"

    async def subscribe(self, ws: object) -> None:
        # Combined stream URL already subscribes; nothing to send.
        return None

    def parse(self, raw: str) -> Iterable[Quote]:
        payload = load_json(raw)
        if not isinstance(payload, dict):
            return []
        data = payload.get("data", payload)
        if not isinstance(data, dict) or "b" not in data or "a" not in data:
            return []
        bid = parse_decimal(data.get("b"))
        ask = parse_decimal(data.get("a"))
        bid_size = parse_decimal(data.get("B"), allow_zero=True) or Decimal("0")
        ask_size = parse_decimal(data.get("A"), allow_zero=True) or Decimal("0")
        native = str(data.get("s") or "")
        if bid is None or ask is None or not native:
            return []
        return [
            Quote(
                exchange=self.name,
                symbol=binance_to_normalized(native),
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
                received_at=datetime.now(timezone.utc),
            )
        ]
