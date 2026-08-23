from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.quote import Quote


def _client() -> tuple[TestClient, object]:
    settings = Settings(testing=True, database_url="", redis_url="")
    app = create_app(settings)
    return TestClient(app), app


def test_health_ok_without_feeds() -> None:
    client, _app = _client()
    with client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["app"] == "exchange-feeds"
        assert body["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        assert body["status"] in {"ok", "degraded", "starting"}
        assert "cassandra" in body
        assert body["cassandra"] is False


def test_price_and_prices_endpoints() -> None:
    client, app = _client()
    with client:
        runtime = app.state.runtime
        runtime.aggregator.update(
            Quote(
                exchange="binance",
                symbol="BTCUSDT",
                bid=Decimal("65000"),
                ask=Decimal("65010"),
                bid_size=Decimal("1"),
                ask_size=Decimal("2"),
                received_at=datetime.now(timezone.utc),
            )
        )
        runtime.aggregator.update(
            Quote(
                exchange="kraken",
                symbol="BTCUSDT",
                bid=Decimal("65001"),
                ask=Decimal("65012"),
                bid_size=Decimal("0.5"),
                ask_size=Decimal("0.5"),
                received_at=datetime.now(timezone.utc),
            )
        )
        response = client.get("/price", params={"symbol": "BTC-USDT"})
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "BTCUSDT"
        assert body["bid"] == 65001
        assert body["bid_exchange"] == "kraken"
        assert body["ask"] == 65010
        assert body["ask_exchange"] == "binance"
        assert "ts" in body

        all_prices = client.get("/prices").json()
        assert "BTCUSDT" in all_prices


def test_unknown_symbol_404() -> None:
    client, _app = _client()
    with client:
        response = client.get("/price", params={"symbol": "DOGEUSDT"})
        assert response.status_code == 404


def test_dashboard_served() -> None:
    client, _app = _client()
    with client:
        response = client.get("/")
        assert response.status_code == 200
        assert "exchange-feeds" in response.text
        assert "Connection history" in response.text


def test_metrics_endpoint() -> None:
    client, _app = _client()
    with client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests_total" in response.text
