CREATE KEYSPACE IF NOT EXISTS feeds
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE feeds;

-- Latest top-of-book per venue (overwrite on update).
CREATE TABLE IF NOT EXISTS latest_quotes (
    symbol text,
    exchange text,
    bid double,
    ask double,
    bid_size double,
    ask_size double,
    ts timestamp,
    PRIMARY KEY (symbol, exchange)
);

-- Serving table for the API: one row per symbol, overwritten each batch.
CREATE TABLE IF NOT EXISTS best_prices (
    symbol text PRIMARY KEY,
    bid double,
    ask double,
    bid_size double,
    ask_size double,
    bid_exchange text,
    ask_exchange text,
    mid double,
    spread double,
    spread_bps double,
    quotes_json text,
    ts timestamp
);

-- Tick history Spark appends for Airflow to roll into 1-minute bars.
CREATE TABLE IF NOT EXISTS quote_ticks (
    symbol text,
    bucket date,
    ts timestamp,
    exchange text,
    bid double,
    ask double,
    bid_size double,
    ask_size double,
    PRIMARY KEY ((symbol, bucket), ts, exchange)
) WITH CLUSTERING ORDER BY (ts DESC);
