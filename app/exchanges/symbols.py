from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SymbolMap:
    """Canonical symbol plus each venue's native product id."""

    normalized: str
    binance: str
    coinbase: str
    kraken: str
    shakepay: str


DEFAULT_PAIRS: tuple[SymbolMap, ...] = (
    SymbolMap("BTCUSDT", "BTCUSDT", "BTC-USDT", "BTC/USDT", "BTC_USD"),
    SymbolMap("ETHUSDT", "ETHUSDT", "ETH-USDT", "ETH/USDT", "ETH_USD"),
    SymbolMap("SOLUSDT", "SOLUSDT", "SOL-USDT", "SOL/USDT", "SOL_USD"),
)

_PAIRS: dict[str, SymbolMap] = {pair.normalized: pair for pair in DEFAULT_PAIRS}


def normalize_symbol(raw: str) -> str:
    return raw.strip().upper().replace("-", "").replace("/", "").replace("_", "")


def resolve_pairs(symbols: list[str]) -> list[SymbolMap]:
    resolved: list[SymbolMap] = []
    for symbol in symbols:
        key = normalize_symbol(symbol)
        pair = _PAIRS.get(key)
        if pair is None:
            raise ValueError(f"Unsupported symbol {symbol!r}; known: {sorted(_PAIRS)}")
        resolved.append(pair)
    return resolved


def binance_to_normalized(native: str) -> str:
    return normalize_symbol(native)


def coinbase_to_normalized(native: str) -> str:
    return normalize_symbol(native)


def kraken_to_normalized(native: str) -> str:
    return normalize_symbol(native)


def shakepay_to_normalized(native: str) -> str | None:
    for pair in DEFAULT_PAIRS:
        if pair.shakepay == native:
            return pair.normalized
    return None
