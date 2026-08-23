from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class FeedState:
    name: str
    connected: bool = False
    last_message_at: datetime | None = None
    last_quote_at: datetime | None = None
    last_error: str | None = None
    reconnects: int = 0
    connected_since: datetime | None = None
    disconnected_since: datetime | None = None
    up_seconds: float = 0.0
    _seen_connected: bool = field(default=False, repr=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "connected": self.connected,
            "last_message_at": iso_utc(self.last_message_at),
            "last_quote_at": iso_utc(self.last_quote_at),
            "last_error": self.last_error,
            "reconnects": self.reconnects,
            "connected_since": iso_utc(self.connected_since),
            "disconnected_since": iso_utc(self.disconnected_since),
            "up_seconds": round(self.up_seconds, 3),
        }


class PriceHub:
    """Fan-out live prices to dashboard WebSocket clients."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, payload: dict[str, object]) -> None:
        stale: list[WebSocket] = []
        for client in self._clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale.append(client)
        for client in stale:
            self._clients.discard(client)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    """Millisecond UTC timestamps. Safari rejects ISO strings with microseconds."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
