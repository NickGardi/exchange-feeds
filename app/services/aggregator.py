from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.quote import BestPrice, Quote


class BookAggregator:
    """In-memory top-of-book across exchanges, keyed by normalized symbol."""

    def __init__(self, stale_after: float = 60.0) -> None:
        self._stale_after = timedelta(seconds=stale_after)
        self._books: dict[str, dict[str, Quote]] = {}

    def update(self, quote: Quote) -> BestPrice | None:
        if quote.bid <= 0 or quote.ask <= 0:
            return None
        book = self._books.setdefault(quote.symbol, {})
        book[quote.exchange] = quote
        return self.best(quote.symbol)

    def best(self, symbol: str, now: datetime | None = None) -> BestPrice | None:
        quotes = self.active_quotes(symbol, now=now)
        if not quotes:
            return None
        best_bid = max(quotes, key=lambda q: (q.bid, q.bid_size))
        best_ask = min(quotes, key=lambda q: (q.ask, -q.ask_size))
        latest = max(q.received_at for q in quotes)
        return BestPrice(
            symbol=symbol,
            bid=best_bid.bid,
            ask=best_ask.ask,
            bid_size=best_bid.bid_size,
            ask_size=best_ask.ask_size,
            bid_exchange=best_bid.exchange,
            ask_exchange=best_ask.exchange,
            ts=latest,
            quotes=sorted(quotes, key=lambda q: q.exchange),
        )

    def all_best(self, now: datetime | None = None) -> dict[str, BestPrice]:
        return {
            symbol: price
            for symbol in sorted(self._books)
            if (price := self.best(symbol, now=now)) is not None
        }

    def active_quotes(self, symbol: str, now: datetime | None = None) -> list[Quote]:
        now = now or datetime.now(timezone.utc)
        book = self._books.get(symbol, {})
        return [quote for quote in book.values() if now - quote.received_at <= self._stale_after]

    def prune(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        for symbol, book in list(self._books.items()):
            for exchange, quote in list(book.items()):
                if now - quote.received_at > self._stale_after:
                    del book[exchange]
            if not book:
                del self._books[symbol]

    def quote_count(self) -> int:
        return sum(len(book) for book in self._books.values())

    def clear(self) -> None:
        self._books.clear()
