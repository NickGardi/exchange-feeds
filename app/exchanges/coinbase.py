from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone

from decimal import Decimal

from app.exchanges.base import BaseFeed, load_json, parse_decimal, parse_ts
from app.exchanges.symbols import coinbase_to_normalized
from app.models.quote import Quote


class CoinbaseFeed(BaseFeed):
    name = "coinbase"
    ping_interval = 30.0

    def ws_url(self) -> str:
        return "wss://ws-feed.exchange.coinbase.com"

    async def subscribe(self, ws: object) -> None:
        message = {
            "type": "subscribe",
            "product_ids": self.native_symbols,
            "channels": ["ticker", "heartbeat"],
        }
        await ws.send(json.dumps(message))  # type: ignore[union-attr]

    def ping_message(self) -> str | None:
        return None

    def parse(self, raw: str) -> Iterable[Quote]:
        payload = load_json(raw)
        if not isinstance(payload, dict):
            return []
        msg_type = payload.get("type")
        if msg_type != "ticker":
            return []
        bid = parse_decimal(payload.get("best_bid"))
        ask = parse_decimal(payload.get("best_ask"))
        bid_size = parse_decimal(payload.get("best_bid_size"), allow_zero=True) or Decimal("0")
        ask_size = parse_decimal(payload.get("best_ask_size"), allow_zero=True) or Decimal("0")
        native = str(payload.get("product_id") or "")
        if bid is None or ask is None or not native:
            return []
        return [
            Quote(
                exchange=self.name,
                symbol=coinbase_to_normalized(native),
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
                received_at=datetime.now(timezone.utc),
                exchange_ts=parse_ts(payload.get("time")),
            )
        ]
