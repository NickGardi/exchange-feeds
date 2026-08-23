from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.quote import BestPrice, utcnow

logger = logging.getLogger("alerts")


class AlertService:
    def __init__(self, move_pct: float, cooldown_seconds: float) -> None:
        self._move_pct = Decimal(str(move_pct))
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._last_mid: dict[str, Decimal] = {}
        self._last_alert_at: dict[str, datetime] = {}
        self._last_cross_at: dict[str, datetime] = {}

    def on_disconnect(self, exchange: str, error: str | None) -> None:
        logger.warning("FEED DISCONNECT  exchange=%s  error=%s", exchange, error or "socket closed")

    def on_reconnect(self, exchange: str) -> None:
        logger.info("FEED RECONNECT  exchange=%s", exchange)

    def on_price(self, price: BestPrice) -> None:
        now = utcnow()
        if price.bid > price.ask:
            last_cross = self._last_cross_at.get(price.symbol)
            if not last_cross or now - last_cross >= self._cooldown:
                self._last_cross_at[price.symbol] = now
                logger.warning(
                    "CROSSED MARKET  symbol=%s  bid=%s (%s) > ask=%s (%s)",
                    price.symbol,
                    price.bid,
                    price.bid_exchange,
                    price.ask,
                    price.ask_exchange,
                )

        previous = self._last_mid.get(price.symbol)
        self._last_mid[price.symbol] = price.mid
        if previous is None or previous == 0:
            return
        change_pct = (abs(price.mid - previous) / previous) * Decimal("100")
        if change_pct < self._move_pct:
            return
        last = self._last_alert_at.get(price.symbol)
        if last and now - last < self._cooldown:
            return
        self._last_alert_at[price.symbol] = now
        direction = "up" if price.mid > previous else "down"
        logger.warning(
            "LARGE MOVE  symbol=%s  %s  %.4f -> %.4f  (%.3f%%)  bid=%s@%s ask=%s@%s",
            price.symbol,
            direction,
            previous,
            price.mid,
            change_pct,
            price.bid,
            price.bid_exchange,
            price.ask,
            price.ask_exchange,
        )
