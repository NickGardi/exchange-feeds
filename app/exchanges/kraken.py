from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone

from decimal import Decimal

from app.exchanges.base import BaseFeed, load_json, parse_decimal, parse_ts
from app.exchanges.symbols import kraken_to_normalized
from app.models.quote import Quote


class KrakenFeed(BaseFeed):
    name = "kraken"
    ping_interval = 30.0

    def ws_url(self) -> str:
        return "wss://ws.kraken.com/v2"

    async def subscribe(self, ws: object) -> None:
        message = {
            "method": "subscribe",
            "params": {
                "channel": "ticker",
                "symbol": self.native_symbols,
                "event_trigger": "bbo",
                "snapshot": True,
            },
        }
        await ws.send(json.dumps(message))  # type: ignore[union-attr]

    def ping_message(self) -> str | None:
        return json.dumps({"method": "ping"})

    def parse(self, raw: str) -> Iterable[Quote]:
        payload = load_json(raw)
        if not isinstance(payload, dict):
            return []
        if payload.get("channel") != "ticker":
            return []
        rows = payload.get("data")
        if not isinstance(rows, list):
            return []
        quotes: list[Quote] = []
        now = datetime.now(timezone.utc)
        for row in rows:
            if not isinstance(row, dict):
                continue
            bid = parse_decimal(row.get("bid"))
            ask = parse_decimal(row.get("ask"))
            bid_size = parse_decimal(row.get("bid_qty"), allow_zero=True) or Decimal("0")
            ask_size = parse_decimal(row.get("ask_qty"), allow_zero=True) or Decimal("0")
            native = str(row.get("symbol") or "")
            if bid is None or ask is None or not native:
                continue
            quotes.append(
                Quote(
                    exchange=self.name,
                    symbol=kraken_to_normalized(native),
                    bid=bid,
                    ask=ask,
                    bid_size=bid_size,
                    ask_size=ask_size,
                    received_at=now,
                    exchange_ts=parse_ts(row.get("timestamp")),
                )
            )
        return quotes
