from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.models.quote import BestPrice

logger = logging.getLogger(__name__)


class PriceCache:
    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._client: Redis | None = None
        self.available = False

    async def connect(self) -> None:
        if not self._url:
            logger.info("Redis disabled (no REDIS_URL)")
            return
        self._client = Redis.from_url(self._url, decode_responses=True)
        try:
            await self._client.ping()
        except Exception as exc:
            logger.warning("Redis unavailable: %s", exc)
            self.available = False
            self._client = None
            return
        self.available = True
        logger.info("Redis connected")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self.available = False

    async def set_many(self, prices: dict[str, BestPrice]) -> None:
        if not self.available or self._client is None or not prices:
            return
        payload = {symbol: json.dumps(price.to_dict()) for symbol, price in prices.items()}
        try:
            pipe = self._client.pipeline()
            for symbol, body in payload.items():
                pipe.set(f"price:{symbol}", body, ex=120)
            pipe.set("prices:all", json.dumps(list(payload.keys())), ex=120)
            await pipe.execute()
        except Exception as exc:
            logger.warning("Redis write failed: %s", exc)
            self.available = False

    async def get_all(self) -> dict[str, Any]:
        if not self.available or self._client is None:
            return {}
        try:
            raw = await self._client.get("prices:all")
            if not raw:
                return {}
            symbols = json.loads(raw)
            out: dict[str, Any] = {}
            for symbol in symbols:
                body = await self._client.get(f"price:{symbol}")
                if body:
                    out[symbol] = json.loads(body)
            return out
        except Exception:
            return {}

    async def get_feeds(self) -> list[dict[str, Any]]:
        names = ["binance", "coinbase", "kraken", "shakepay"]
        if not self.available or self._client is None:
            return [
                {
                    "name": n,
                    "connected": False,
                    "reconnects": 0,
                    "up_seconds": 0,
                    "connected_since": None,
                    "disconnected_since": None,
                }
                for n in names
            ]
        feeds = []
        for name in names:
            raw = await self._client.get(f"feed:{name}")
            if raw:
                feeds.append(json.loads(raw))
            else:
                feeds.append(
                    {
                        "name": name,
                        "connected": False,
                        "reconnects": 0,
                        "up_seconds": 0,
                        "connected_since": None,
                        "disconnected_since": None,
                    }
                )
        return feeds

    async def get(self, symbol: str) -> dict[str, Any] | None:
        if not self.available or self._client is None:
            return None
        try:
            raw = await self._client.get(f"price:{symbol}")
        except Exception:
            return None
        if not raw:
            return None
        return json.loads(raw)
