from __future__ import annotations

from prometheus_client import Counter, Gauge

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["path"])
FEEDS_MID = Gauge("feeds_mid", "Best mid price", ["symbol"])
FEEDS_SPREAD_BPS = Gauge("feeds_spread_bps", "Best spread in bps", ["symbol"])
LARGE_MOVE = Counter("feeds_large_move_total", "Large mid-price moves")


def observe_prices(prices: dict) -> None:
    for symbol, price in prices.items():
        try:
            FEEDS_MID.labels(symbol=symbol).set(float(price["mid"]))
            FEEDS_SPREAD_BPS.labels(symbol=symbol).set(float(price["spread_bps"]))
        except (KeyError, TypeError, ValueError):
            continue
