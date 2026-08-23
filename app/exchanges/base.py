from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.models.quote import Quote

logger = logging.getLogger(__name__)

OnQuote = Callable[[Quote], None]
OnStatus = Callable[[str, bool, str | None], None]
OnActivity = Callable[[str], None]


class BaseFeed(ABC):
    """Reconnecting public WebSocket client for a single exchange."""

    name: str
    ping_interval: float | None = 20.0

    def __init__(
        self,
        native_symbols: list[str],
        on_quote: OnQuote,
        on_status: OnStatus,
        on_activity: OnActivity | None = None,
    ) -> None:
        self.native_symbols = native_symbols
        self._on_quote = on_quote
        self._on_status = on_status
        self._on_activity = on_activity
        self._stopped = False

    @abstractmethod
    def ws_url(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, ws: object) -> None:
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw: str) -> Iterable[Quote]:
        raise NotImplementedError

    def ping_message(self) -> str | None:
        return None

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        delay = 1.0
        while not self._stopped:
            try:
                await self._session()
                delay = 1.0
            except asyncio.CancelledError:
                self._on_status(self.name, False, "cancelled")
                raise
            except Exception as exc:
                logger.warning("%s disconnected: %s", self.name, exc)
                self._on_status(self.name, False, str(exc))
                if self._stopped:
                    return
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _session(self) -> None:
        url = self.ws_url()
        logger.info("%s connecting to %s", self.name, url)
        async with connect(
            url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=2**22,
            additional_headers={"User-Agent": "exchange-feeds/0.1"},
            open_timeout=15,
        ) as ws:
            logger.info("%s connected", self.name)
            self._on_status(self.name, True, None)
            await self.subscribe(ws)
            ping_task = asyncio.create_task(self._ping_loop(ws), name=f"{self.name}-ping")
            closed_reason = "socket closed"
            try:
                async for raw in ws:
                    if self._stopped:
                        break
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    if self._on_activity:
                        self._on_activity(self.name)
                    try:
                        for quote in self.parse(raw):
                            self._on_quote(quote)
                    except Exception:
                        logger.exception("%s failed to parse message", self.name)
            except ConnectionClosed as exc:
                closed_reason = f"connection closed ({exc.code})"
                raise RuntimeError(closed_reason) from exc
            finally:
                ping_task.cancel()
                self._on_status(self.name, False, closed_reason)

    async def _ping_loop(self, ws: object) -> None:
        payload = self.ping_message()
        if not payload or not self.ping_interval:
            return
        try:
            while True:
                await asyncio.sleep(self.ping_interval)
                await ws.send(payload)  # type: ignore[union-attr]
        except asyncio.CancelledError:
            return
        except Exception:
            return


def parse_decimal(value: object, *, allow_zero: bool = False) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if number < 0:
        return None
    if number == 0 and not allow_zero:
        return None
    return number


def parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Heuristic: ns/ms/s
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def load_json(raw: str) -> object | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
