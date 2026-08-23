from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.services.aggregator import BookAggregator
from app.services.alerts import AlertService
from app.services.feeds import FeedManager
from app.services.hub import FeedState, iso_utc


def test_iso_utc_uses_milliseconds_and_z() -> None:
    stamp = datetime(2026, 8, 23, 1, 48, 14, 756347, tzinfo=timezone.utc)
    assert iso_utc(stamp) == "2026-08-23T01:48:14.756Z"
    assert iso_utc(None) is None


def test_disconnect_does_not_double_count_or_wipe_reason() -> None:
    settings = Settings(testing=True, database_url="", redis_url="")
    manager = FeedManager(settings, BookAggregator(), AlertService(0.5, 15))
    state = manager.states["binance"]

    manager._set_connected(state)
    manager._set_disconnected(state, "socket closed")
    manager._set_disconnected(state, "connection closed (1006)")

    assert state.connected is False
    assert state.reconnects == 0
    assert state.last_error == "connection closed (1006)"
    assert state.up_seconds > 0 or state.disconnected_since is not None

    manager._set_connected(state)
    assert state.connected is True
    assert state.reconnects == 1
    assert state.last_error == "connection closed (1006)"


def test_feed_state_dict_timestamps_are_parseable() -> None:
    now = datetime.now(timezone.utc)
    state = FeedState(name="kraken", connected=True, connected_since=now, last_quote_at=now)
    payload = state.to_dict()
    parsed = datetime.fromisoformat(str(payload["connected_since"]).replace("Z", "+00:00"))
    assert abs((parsed - now).total_seconds()) < 1
    assert str(payload["connected_since"]).endswith("Z")
    assert "." in str(payload["connected_since"])
    frac = str(payload["connected_since"]).split(".")[1]
    assert len(frac) == 4  # 756Z
