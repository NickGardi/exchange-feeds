from __future__ import annotations

import pytest

from app.exchanges.symbols import normalize_symbol, resolve_pairs


def test_normalize_strips_separators() -> None:
    assert normalize_symbol("btc-usdt") == "BTCUSDT"
    assert normalize_symbol("BTC/USDT") == "BTCUSDT"
    assert normalize_symbol("eth_usdt") == "ETHUSDT"


def test_resolve_known_pairs() -> None:
    pairs = resolve_pairs(["BTC-USDT", "ETHUSDT"])
    assert [p.normalized for p in pairs] == ["BTCUSDT", "ETHUSDT"]
    assert pairs[0].binance == "BTCUSDT"
    assert pairs[0].coinbase == "BTC-USDT"
    assert pairs[0].kraken == "BTC/USDT"
    assert pairs[0].shakepay == "BTC_USD"


def test_resolve_rejects_unknown_symbol() -> None:
    with pytest.raises(ValueError):
        resolve_pairs(["DOGEUSDT"])
