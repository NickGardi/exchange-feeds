from __future__ import annotations

import json

from app.exchanges.binance import BinanceFeed
from app.exchanges.coinbase import CoinbaseFeed
from app.exchanges.kraken import KrakenFeed
from app.exchanges.shakepay import ShakepayFeed


def _feed(cls):  # type: ignore[no-untyped-def]
    return cls(["BTCUSDT"], lambda _q: None, lambda *_a: None)


def test_binance_book_ticker() -> None:
    raw = json.dumps(
        {
            "stream": "btcusdt@bookTicker",
            "data": {
                "u": 1,
                "s": "BTCUSDT",
                "b": "65000.10",
                "B": "1.25",
                "a": "65000.20",
                "A": "0.80",
            },
        }
    )
    quotes = list(_feed(BinanceFeed).parse(raw))
    assert len(quotes) == 1
    quote = quotes[0]
    assert quote.exchange == "binance"
    assert quote.symbol == "BTCUSDT"
    assert str(quote.bid) == "65000.10"
    assert str(quote.ask) == "65000.20"


def test_coinbase_ticker() -> None:
    raw = json.dumps(
        {
            "type": "ticker",
            "product_id": "BTC-USDT",
            "best_bid": "65001.00",
            "best_bid_size": "0.4",
            "best_ask": "65002.00",
            "best_ask_size": "0.5",
            "time": "2026-08-22T00:00:00.000000Z",
        }
    )
    quotes = list(_feed(CoinbaseFeed).parse(raw))
    assert len(quotes) == 1
    assert quotes[0].exchange == "coinbase"
    assert quotes[0].symbol == "BTCUSDT"
    assert str(quotes[0].bid) == "65001.00"


def test_coinbase_ignores_heartbeat() -> None:
    raw = json.dumps({"type": "heartbeat", "product_id": "BTC-USDT"})
    assert list(_feed(CoinbaseFeed).parse(raw)) == []


def test_kraken_ticker() -> None:
    raw = json.dumps(
        {
            "channel": "ticker",
            "type": "update",
            "data": [
                {
                    "symbol": "BTC/USDT",
                    "bid": 64999.5,
                    "bid_qty": 2.0,
                    "ask": 65003.1,
                    "ask_qty": 1.1,
                    "timestamp": "2026-08-22T00:00:00.000000Z",
                }
            ],
        }
    )
    quotes = list(_feed(KrakenFeed).parse(raw))
    assert len(quotes) == 1
    assert quotes[0].exchange == "kraken"
    assert quotes[0].symbol == "BTCUSDT"
    assert float(quotes[0].ask) == 65003.1


def test_shakepay_two_way_usd_quote() -> None:
    raw = json.dumps(
        [
            {"symbol": "BTC_USD", "rate": 76000.0},
            {"symbol": "USD_BTC", "rate": 0.0000125},
            {"symbol": "ETH_USD", "rate": 2400.0},
            {"symbol": "USD_ETH", "rate": 0.0004},
        ]
    )
    feed = ShakepayFeed(["BTC_USD", "ETH_USD"], lambda _q: None, lambda *_a: None)
    quotes = {q.symbol: q for q in feed.parse(raw)}
    assert quotes["BTCUSDT"].exchange == "shakepay"
    assert float(quotes["BTCUSDT"].bid) == 76000.0
    assert float(quotes["BTCUSDT"].ask) == 80000.0
    assert float(quotes["ETHUSDT"].bid) == 2400.0
    assert float(quotes["ETHUSDT"].ask) == 2500.0


def test_shakepay_skips_missing_pairs() -> None:
    raw = json.dumps([{"symbol": "BTC_CAD", "rate": 100000.0}])
    feed = ShakepayFeed(["BTC_USD"], lambda _q: None, lambda *_a: None)
    assert list(feed.parse(raw)) == []
