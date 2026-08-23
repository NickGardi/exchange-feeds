from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

try:
    from cassandra.cluster import Cluster
    from cassandra.query import dict_factory
except ImportError:  # pragma: no cover
    Cluster = None  # type: ignore[misc, assignment]
    dict_factory = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)


class CassandraStore:
    """Read path for the API. Spark is the only writer."""

    def __init__(self, host: str, keyspace: str = "feeds") -> None:
        self._host = host
        self._keyspace = keyspace
        self._cluster: Cluster | None = None
        self._session = None
        self.available = False

    def connect(self) -> None:
        if not self._host:
            logger.info("Cassandra disabled (no CASSANDRA_HOST)")
            return
        if Cluster is None:
            logger.warning("cassandra-driver is not installed; Cassandra reads disabled")
            return
        try:
            self._cluster = Cluster([self._host])
            self._session = self._cluster.connect(self._keyspace)
            self._session.row_factory = dict_factory
        except Exception as exc:
            logger.warning("Cassandra unavailable: %s", exc)
            self.available = False
            self._cluster = None
            self._session = None
            return
        self.available = True
        logger.info("Cassandra connected at %s", self._host)

    def close(self) -> None:
        if self._cluster is not None:
            self._cluster.shutdown()
            self._cluster = None
            self._session = None
            self.available = False

    def get_best(self, symbol: str) -> dict[str, Any] | None:
        if not self.available or self._session is None:
            return None
        row = self._session.execute(
            "SELECT * FROM best_prices WHERE symbol = %s", (symbol,)
        ).one()
        if not row:
            return None
        return _row_to_price(row)

    def get_all_best(self) -> dict[str, dict[str, Any]]:
        if not self.available or self._session is None:
            return {}
        rows = self._session.execute("SELECT * FROM best_prices")
        return {row["symbol"]: _row_to_price(row) for row in rows}

    def quote_count(self) -> int:
        if not self.available or self._session is None:
            return 0
        row = self._session.execute("SELECT COUNT(*) AS n FROM latest_quotes").one()
        return int(row["n"]) if row else 0


def _row_to_price(row: dict[str, Any]) -> dict[str, Any]:
    ts = row.get("ts")
    if isinstance(ts, datetime):
        ts_out = ts.astimezone(timezone.utc).isoformat() if ts.tzinfo else ts.replace(tzinfo=timezone.utc).isoformat()
    else:
        ts_out = datetime.now(timezone.utc).isoformat()
    quotes = json.loads(row.get("quotes_json") or "[]")
    return {
        "symbol": row["symbol"],
        "bid": row["bid"],
        "ask": row["ask"],
        "bid_size": row["bid_size"],
        "ask_size": row["ask_size"],
        "bid_exchange": row["bid_exchange"],
        "ask_exchange": row["ask_exchange"],
        "spread": row["spread"],
        "spread_bps": row["spread_bps"],
        "mid": row["mid"],
        "ts": ts_out,
        "quotes": quotes,
    }
