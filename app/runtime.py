from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.services.aggregator import BookAggregator
from app.services.alerts import AlertService
from app.services.cache import PriceCache
from app.services.cassandra_store import CassandraStore
from app.services.feeds import FeedManager
from app.services.hub import PriceHub
from app.services.metrics import LARGE_MOVE, observe_prices
from app.services.store import SnapshotStore

logger = logging.getLogger(__name__)


@dataclass
class AppRuntime:
    settings: Settings
    aggregator: BookAggregator
    alerts: AlertService
    cache: PriceCache
    store: SnapshotStore
    cassandra: CassandraStore
    hub: PriceHub
    feeds: FeedManager
    tasks: list[asyncio.Task[None]]

    def snapshot_payload(self) -> dict[str, object]:
        prices = {symbol: price.to_dict() for symbol, price in self.aggregator.all_best().items()}
        return {
            "type": "prices",
            "prices": prices,
            "feeds": [state.to_dict() for state in self.feeds.statuses()],
        }

    async def pipeline_snapshot(self) -> dict[str, object]:
        prices = await self.cache.get_all()
        if not prices:
            prices = await asyncio.to_thread(self.cassandra.get_all_best)
        feeds = await self.cache.get_feeds()
        return {"type": "prices", "prices": prices, "feeds": feeds}

    async def get_price_dict(self, symbol: str) -> dict[str, Any] | None:
        if not self.settings.pipeline_mode:
            best = self.aggregator.best(symbol)
            return best.to_dict() if best else None
        cached = await self.cache.get(symbol)
        if cached:
            return cached
        return await asyncio.to_thread(self.cassandra.get_best, symbol)

    async def get_all_price_dicts(self) -> dict[str, Any]:
        if not self.settings.pipeline_mode:
            return {s: p.to_dict() for s, p in self.aggregator.all_best().items()}
        cached = await self.cache.get_all()
        if cached:
            return cached
        return await asyncio.to_thread(self.cassandra.get_all_best)


def build_runtime(settings: Settings) -> AppRuntime:
    aggregator = BookAggregator(stale_after=settings.stale_quote_seconds)
    alerts = AlertService(settings.alert_move_pct, settings.alert_cooldown_seconds)
    cache = PriceCache(settings.redis_url)
    store = SnapshotStore(settings.database_url)
    cassandra = CassandraStore(settings.cassandra_host, settings.cassandra_keyspace)
    hub = PriceHub()
    feeds = FeedManager(settings, aggregator, alerts)
    return AppRuntime(
        settings=settings,
        aggregator=aggregator,
        alerts=alerts,
        cache=cache,
        store=store,
        cassandra=cassandra,
        hub=hub,
        feeds=feeds,
        tasks=[],
    )


async def start_runtime(runtime: AppRuntime) -> None:
    await runtime.cache.connect()
    if runtime.settings.require_redis and not runtime.cache.available:
        raise RuntimeError("REDIS_URL is required but Redis is unavailable")
    await runtime.store.connect()
    if runtime.settings.require_database and not runtime.store.available:
        raise RuntimeError("DATABASE_URL is required but PostgreSQL is unavailable")
    await asyncio.to_thread(runtime.cassandra.connect)

    if runtime.settings.testing:
        return

    if not runtime.settings.pipeline_mode:
        await runtime.feeds.start()
        runtime.tasks = [
            asyncio.create_task(_broadcast_loop(runtime), name="broadcast"),
            asyncio.create_task(_snapshot_loop(runtime), name="snapshots"),
        ]
        return

    runtime.tasks = [asyncio.create_task(_pipeline_broadcast(runtime), name="pipeline-broadcast")]


async def stop_runtime(runtime: AppRuntime) -> None:
    for task in runtime.tasks:
        task.cancel()
    if runtime.tasks:
        await asyncio.gather(*runtime.tasks, return_exceptions=True)
    await runtime.feeds.stop()
    await runtime.cache.close()
    await runtime.store.close()
    runtime.cassandra.close()


async def _broadcast_loop(runtime: AppRuntime) -> None:
    try:
        while True:
            runtime.aggregator.prune()
            payload = runtime.snapshot_payload()
            prices = runtime.aggregator.all_best()
            observe_prices({symbol: price.to_dict() for symbol, price in prices.items()})
            await runtime.hub.broadcast(payload)
            await runtime.cache.set_many(prices)
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        return


async def _pipeline_broadcast(runtime: AppRuntime) -> None:
    last_mid: dict[str, float] = {}
    try:
        while True:
            payload = await runtime.pipeline_snapshot()
            prices = payload.get("prices") or {}
            if isinstance(prices, dict):
                observe_prices(prices)
                _count_large_moves(runtime, prices, last_mid)
            await runtime.hub.broadcast(payload)
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        return


def _count_large_moves(runtime: AppRuntime, prices: dict[str, Any], last_mid: dict[str, float]) -> None:
    threshold = runtime.settings.alert_move_pct
    for symbol, price in prices.items():
        try:
            mid = float(price["mid"])
        except (KeyError, TypeError, ValueError):
            continue
        prev = last_mid.get(symbol)
        last_mid[symbol] = mid
        if prev and prev > 0 and abs(mid - prev) / prev * 100 >= threshold:
            LARGE_MOVE.inc()


async def _snapshot_loop(runtime: AppRuntime) -> None:
    interval = max(runtime.settings.snapshot_interval_seconds, 5.0)
    try:
        while True:
            await asyncio.sleep(interval)
            prices = list(runtime.aggregator.all_best().values())
            if prices:
                await runtime.store.save_prices(prices)
    except asyncio.CancelledError:
        return
