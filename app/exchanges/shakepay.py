from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.exchanges.base import BaseFeed, load_json, parse_decimal
from app.exchanges.symbols import shakepay_to_normalized
from app.models.quote import Quote

logger = logging.getLogger(__name__)

QUOTE_URL = "https://api.shakepay.com/quote"


class ShakepayFeed(BaseFeed):
    """Shakepay has no public WebSocket; poll the quote API instead.

    Quotes are USD two-way rates (BTC_USD sell / USD_BTC buy), mapped onto
    the matching USDT symbols for aggregation.
    """

    name = "shakepay"
    poll_interval = 5.0

    def ws_url(self) -> str:
        return QUOTE_URL

    async def subscribe(self, ws: object) -> None:
        return None

    async def _session(self) -> None:
        url = self.ws_url()
        logger.info("%s polling %s", self.name, url)
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "exchange-feeds/0.1"},
            follow_redirects=True,
        ) as client:
            self._on_status(self.name, True, None)
            while not self._stopped:
                response = await client.get(url)
                response.raise_for_status()
                if self._on_activity:
                    self._on_activity(self.name)
                for quote in self.parse(response.text):
                    self._on_quote(quote)
                await asyncio.sleep(self.poll_interval)

    def parse(self, raw: str) -> Iterable[Quote]:
        payload = load_json(raw)
        if not isinstance(payload, list):
            return []
        rates: dict[str, Decimal] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            native = str(row.get("symbol") or "")
            rate = parse_decimal(row.get("rate") or row.get("baseRate"))
            if native and rate is not None:
                rates[native] = rate

        now = datetime.now(timezone.utc)
        quotes: list[Quote] = []
        for native in self.native_symbols:
            symbol = shakepay_to_normalized(native)
            if symbol is None or "_" not in native:
                continue
            crypto, fiat = native.split("_", 1)
            bid = rates.get(f"{crypto}_{fiat}")
            buy_rate = rates.get(f"{fiat}_{crypto}")
            if bid is None or buy_rate is None or buy_rate == 0:
                continue
            ask = Decimal("1") / buy_rate
            quotes.append(
                Quote(
                    exchange=self.name,
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    bid_size=Decimal("0"),
                    ask_size=Decimal("0"),
                    received_at=now,
                )
            )
        return quotes
