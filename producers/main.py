"""WebSocket / REST clients that publish raw quotes to Kafka.

One topic per exchange:

    prices.binance | prices.coinbase | prices.kraken | prices.shakepay

This process does not compute best bid/ask. Spark does that.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

from aiokafka import AIOKafkaProducer
from redis.asyncio import Redis

from app.exchanges.base import BaseFeed
from app.exchanges.binance import BinanceFeed
from app.exchanges.coinbase import CoinbaseFeed
from app.exchanges.kraken import KrakenFeed
from app.exchanges.shakepay import ShakepayFeed
from app.exchanges.symbols import resolve_pairs
from app.logging_config import configure_logging
from app.models.quote import Quote
from app.services.hub import iso_utc, utcnow

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
TOPICS = {
    "binance": "prices.binance",
    "coinbase": "prices.coinbase",
    "kraken": "prices.kraken",
    "shakepay": "prices.shakepay",
}

logger = logging.getLogger("producers")


class KafkaPublisher:
    def __init__(self) -> None:
        self.producer: AIOKafkaProducer | None = None
        self.redis: Redis | None = None
        self._queue: asyncio.Queue[Quote] = asyncio.Queue(maxsize=10_000)
        self._reconnects: dict[str, int] = {name: 0 for name in TOPICS}
        self._seen: dict[str, bool] = {name: False for name in TOPICS}
        self._connected: dict[str, bool] = {name: False for name in TOPICS}
        self._connected_since: dict[str, datetime | None] = {name: None for name in TOPICS}
        self._up_seconds: dict[str, float] = {name: 0.0 for name in TOPICS}

    def enqueue(self, quote: Quote) -> None:
        try:
            self._queue.put_nowait(quote)
        except asyncio.QueueFull:
            logger.warning("dropping quote; kafka queue is full")

    def status(self, name: str, connected: bool, error: str | None) -> None:
        self._schedule(self._write_status(name, connected, error, quote=False))

    def activity(self, name: str) -> None:
        self._schedule(self._write_status(name, True, None, quote=False))

    def _schedule(self, coro: object) -> None:
        try:
            asyncio.get_running_loop().create_task(coro)  # type: ignore[arg-type]
        except RuntimeError:
            logger.debug("dropped feed status write; no running event loop")

    async def _write_status(
        self,
        name: str,
        connected: bool,
        error: str | None,
        *,
        quote: bool,
    ) -> None:
        if self.redis is None:
            return
        now = utcnow()
        was = self._connected[name]
        disconnected_since = None
        if connected:
            if not was:
                if self._seen[name]:
                    self._reconnects[name] += 1
                self._connected_since[name] = now
                self._seen[name] = True
            elif self._connected_since[name] is None:
                self._connected_since[name] = now
        else:
            started = self._connected_since[name]
            if was and started is not None:
                self._up_seconds[name] += (now - started).total_seconds()
            if was or self._connected_since[name] is not None:
                disconnected_since = now
            self._connected_since[name] = None
            if was:
                logger.warning("FEED DISCONNECT  exchange=%s  error=%s", name, error)
        self._connected[name] = connected
        payload = {
            "name": name,
            "connected": connected,
            "last_message_at": iso_utc(now),
            "last_quote_at": iso_utc(now) if quote else None,
            "last_error": error if (error and not connected) else None,
            "reconnects": self._reconnects[name],
            "connected_since": iso_utc(self._connected_since[name]),
            "disconnected_since": iso_utc(disconnected_since),
            "up_seconds": round(self._up_seconds[name], 3),
        }
        existing = await self.redis.get(f"feed:{name}")
        if existing:
            prev = json.loads(existing)
            if not quote:
                payload["last_quote_at"] = prev.get("last_quote_at")
            if connected or not error:
                payload["last_error"] = prev.get("last_error")
            if not connected and disconnected_since is None:
                payload["disconnected_since"] = prev.get("disconnected_since")
        await self.redis.set(f"feed:{name}", json.dumps(payload), ex=120)

    async def run(self) -> None:
        self.producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
        await self.producer.start()
        self.redis = Redis.from_url(REDIS_URL, decode_responses=True)
        logger.info("publishing to kafka %s", KAFKA_BOOTSTRAP)
        try:
            while True:
                quote = await self._queue.get()
                topic = TOPICS[quote.exchange]
                body = json.dumps(
                    {
                        "exchange": quote.exchange,
                        "symbol": quote.symbol,
                        "bid": float(quote.bid),
                        "ask": float(quote.ask),
                        "bid_size": float(quote.bid_size),
                        "ask_size": float(quote.ask_size),
                        "ts": quote.received_at.isoformat(),
                    }
                ).encode()
                await self.producer.send_and_wait(topic, body, key=quote.symbol.encode())
                await self._write_status(quote.exchange, True, None, quote=True)
        finally:
            await self.producer.stop()
            if self.redis is not None:
                await self.redis.aclose()


def build_feeds(publisher: KafkaPublisher) -> list[BaseFeed]:
    pairs = resolve_pairs(SYMBOLS)
    on_quote = publisher.enqueue
    on_status = publisher.status
    on_activity = publisher.activity
    return [
        BinanceFeed([p.binance for p in pairs], on_quote, on_status, on_activity),
        CoinbaseFeed([p.coinbase for p in pairs], on_quote, on_status, on_activity),
        KrakenFeed([p.kraken for p in pairs], on_quote, on_status, on_activity),
        ShakepayFeed([p.shakepay for p in pairs], on_quote, on_status, on_activity),
    ]


async def main() -> None:
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    publisher = KafkaPublisher()
    feeds = build_feeds(publisher)
    stop = asyncio.Event()

    def _stop() -> None:
        stop.set()
        for feed in feeds:
            feed.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    writer = asyncio.create_task(publisher.run(), name="kafka-writer")
    feed_tasks = [asyncio.create_task(feed.run(), name=feed.name) for feed in feeds]
    logger.info("producers started for %s", SYMBOLS)
    await stop.wait()
    writer.cancel()
    for task in feed_tasks:
        task.cancel()
    await asyncio.gather(writer, *feed_tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
