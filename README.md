# exchange-feeds

Live crypto bids and asks from Binance, Coinbase, Kraken, and Shakepay, run through a streaming pipeline and served as the best bid / best ask.

## How it works

`producers/` stay on each venue’s public feed, parse JSON, and write bid/ask to Kafka — `prices.binance`, `prices.coinbase`, `prices.kraken`, `prices.shakepay`. Shakepay has no public socket, so that one polls REST.

`spark/stream_best_prices.py` reads those topics, normalizes symbols (`BTC-USDT` → `BTCUSDT`), and computes best bid/ask across the active feeds. Latest quote per venue goes in Cassandra `feeds.latest_quotes`. The serving row is `feeds.best_prices` (one per symbol, overwritten). Ticks append to `feeds.quote_ticks`.

FastAPI (`app/`) reads Redis, then Cassandra. `GET /price?symbol=BTCUSDT` is the main endpoint. Also `/prices`, `/health`, `/history`, `/metrics`, and a websocket for the dashboard.

Airflow DAG `crypto_price_bars_1m` every minute writes Postgres `price_bars`: `window_start`, `symbol`, `exchange`, `price`, `volume`.

Docker Compose runs the lot. Prometheus + Grafana on `/metrics`. Logs when mid moves a lot.

## Run

Needs Docker and roughly 8 GB RAM. Cassandra is slow to become healthy. Spark pulls Kafka/Cassandra jars on first start (`docker compose logs -f spark` if it hangs). Quotes appear after the first Spark batch.

```bash
docker compose up --build
```

| | |
| --- | --- |
| API / dashboard | http://localhost:8000 |
| Grafana (`admin` / `admin`) | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Airflow (`admin` / `admin`) | http://localhost:8085 |

```bash
pytest
```

Pairs: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`. Add more in `app/exchanges/symbols.py`. Env knobs in `.env.example`.

Binance `bookTicker` is real top of book. Kraken is WS v2 ticker with `event_trigger=bbo`. Coinbase `ticker` updates on trades, so it can go stale. Shakepay is a USD retail quote mapped onto BTC/ETH — wide spread, no SOL.
