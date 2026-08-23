from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.quote import Quote
from app.services.aggregator import BookAggregator


def _quote(
    exchange: str,
    bid: str,
    ask: str,
    *,
    symbol: str = "BTCUSDT",
    age_s: float = 0,
    bid_size: str = "1",
    ask_size: str = "1",
) -> Quote:
    now = datetime.now(timezone.utc)
    return Quote(
        exchange=exchange,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=Decimal(bid_size),
        ask_size=Decimal(ask_size),
        received_at=now - timedelta(seconds=age_s),
    )


def test_best_bid_is_highest_and_best_ask_is_lowest() -> None:
    agg = BookAggregator(stale_after=60)
    agg.update(_quote("binance", "65000", "65010"))
    agg.update(_quote("coinbase", "65005", "65020"))
    agg.update(_quote("kraken", "64990", "65008"))

    best = agg.best("BTCUSDT")
    assert best is not None
    assert best.bid == Decimal("65005")
    assert best.bid_exchange == "coinbase"
    assert best.ask == Decimal("65008")
    assert best.ask_exchange == "kraken"
    assert best.spread == Decimal("3")


def test_stale_quotes_are_ignored() -> None:
    agg = BookAggregator(stale_after=10)
    agg.update(_quote("binance", "100", "101", age_s=30))
    agg.update(_quote("coinbase", "99", "102", age_s=1))

    best = agg.best("BTCUSDT")
    assert best is not None
    assert best.bid_exchange == "coinbase"
    assert best.ask_exchange == "coinbase"
    assert len(best.quotes) == 1


def test_later_update_from_same_exchange_replaces_quote() -> None:
    agg = BookAggregator(stale_after=60)
    agg.update(_quote("binance", "100", "110"))
    agg.update(_quote("binance", "105", "106"))
    best = agg.best("BTCUSDT")
    assert best is not None
    assert best.bid == Decimal("105")
    assert best.ask == Decimal("106")
    assert len(best.quotes) == 1


def test_unknown_symbol_has_no_best_price() -> None:
    agg = BookAggregator()
    assert agg.best("ETHUSDT") is None


def test_all_best_returns_only_symbols_with_live_quotes() -> None:
    agg = BookAggregator(stale_after=60)
    agg.update(_quote("binance", "100", "101", symbol="BTCUSDT"))
    agg.update(_quote("binance", "10", "11", symbol="ETHUSDT", age_s=120))
    prices = agg.all_best()
    assert set(prices) == {"BTCUSDT"}
