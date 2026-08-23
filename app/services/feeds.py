from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.exchanges.base import BaseFeed
from app.exchanges.binance import BinanceFeed
from app.exchanges.coinbase import CoinbaseFeed
from app.exchanges.kraken import KrakenFeed
from app.exchanges.shakepay import ShakepayFeed
from app.exchanges.symbols import resolve_pairs
from app.models.quote import Quote
from app.services.aggregator import BookAggregator
from app.services.alerts import AlertService
from app.services.hub import FeedState, utcnow

logger = logging.getLogger(__name__)


class FeedManager:
    def __init__(
        self,
        settings: Settings,
        aggregator: BookAggregator,
        alerts: AlertService,
    ) -> None:
        self.settings = settings
        self.aggregator = aggregator
        self.alerts = alerts
        pairs = resolve_pairs(settings.symbol_list)
        self.states: dict[str, FeedState] = {
            "binance": FeedState("binance"),
            "coinbase": FeedState("coinbase"),
            "kraken": FeedState("kraken"),
            "shakepay": FeedState("shakepay"),
        }
        self.feeds: list[BaseFeed] = [
            BinanceFeed([p.binance for p in pairs], self._on_quote, self._on_status, self._on_activity),
            CoinbaseFeed([p.coinbase for p in pairs], self._on_quote, self._on_status, self._on_activity),
            KrakenFeed([p.kraken for p in pairs], self._on_quote, self._on_status, self._on_activity),
            ShakepayFeed([p.shakepay for p in pairs], self._on_quote, self._on_status, self._on_activity),
        ]
        self._tasks: list[asyncio.Task[None]] = []
        self._stopped = False

    def _set_connected(self, state: FeedState) -> None:
        now = utcnow()
        if not state.connected:
            if state._seen_connected:
                state.reconnects += 1
                self.alerts.on_reconnect(state.name)
            state.connected_since = now
            state.disconnected_since = None
            state._seen_connected = True
        state.connected = True
        state.last_message_at = now

    def _set_disconnected(self, state: FeedState, error: str | None) -> None:
        now = utcnow()
        if not state.connected:
            if error and (not state.last_error or state.last_error == "socket closed"):
                state.last_error = error
            return
        if state.connected_since is not None:
            state.up_seconds += (now - state.connected_since).total_seconds()
            state.connected_since = None
        state.disconnected_since = now
        state.connected = False
        state.last_message_at = now
        if error:
            state.last_error = error
        self.alerts.on_disconnect(state.name, error)

    def _on_activity(self, name: str) -> None:
        state = self.states.get(name)
        if state is None:
            return
        if state.connected:
            state.last_message_at = utcnow()
        else:
            self._set_connected(state)

    def _on_quote(self, quote: Quote) -> None:
        state = self.states.get(quote.exchange)
        if state is not None:
            self._set_connected(state)
            state.last_quote_at = utcnow()
        best = self.aggregator.update(quote)
        if best is not None:
            self.alerts.on_price(best)

    def _on_status(self, name: str, connected: bool, error: str | None) -> None:
        state = self.states.setdefault(name, FeedState(name))
        if connected:
            self._set_connected(state)
        else:
            self._set_disconnected(state, error)

    async def start(self) -> None:
        logger.info("Starting %d exchange feeds for %s", len(self.feeds), self.settings.symbol_list)
        self._tasks = [asyncio.create_task(feed.run(), name=feed.name) for feed in self.feeds]

    async def stop(self) -> None:
        self._stopped = True
        for feed in self.feeds:
            feed.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def statuses(self) -> list[FeedState]:
        return [self.states[name] for name in ("binance", "coinbase", "kraken", "shakepay")]
