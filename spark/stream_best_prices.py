"""
Spark Structured Streaming job.

Reads Kafka topics  prices.*
  -> parses JSON
  -> normalizes (producers already send BTCUSDT-style symbols)
  -> upserts latest quote per (symbol, exchange) into Cassandra
  -> computes best bid (max) / best ask (min) across venues
  -> overwrites feeds.best_prices  (API serving table)
  -> appends feeds.quote_ticks     (Airflow historical source)
  -> writes Redis price:{symbol}   (API hot cache)
  -> logs large mid-price moves
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

KAFKA = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "cassandra")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
ALERT_MOVE_PCT = float(os.getenv("ALERT_MOVE_PCT", "0.5"))
TOPICS = "prices.binance,prices.coinbase,prices.kraken,prices.shakepay"

QUOTE_SCHEMA = StructType(
    [
        StructField("exchange", StringType()),
        StructField("symbol", StringType()),
        StructField("bid", DoubleType()),
        StructField("ask", DoubleType()),
        StructField("bid_size", DoubleType()),
        StructField("ask_size", DoubleType()),
        StructField("ts", StringType()),
    ]
)

LAST_MID: dict[str, float] = {}


def _spark() -> SparkSession:
    return (
        SparkSession.builder.appName("exchange-feeds-best-prices")
        .config("spark.cassandra.connection.host", CASSANDRA_HOST)
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )


def _write_cassandra(df, table: str, mode: str = "append") -> None:
    (
        df.write.format("org.apache.spark.sql.cassandra")
        .mode(mode)
        .option("keyspace", "feeds")
        .option("table", table)
        .save()
    )


def _best_from_latest(latest):
    """Best bid = highest bid; best ask = lowest ask. May come from different venues.

    Spark compares structs left-to-right, so max(bid, bid_size, exchange) is the
    highest bid (size as tie-break). min(ask, -ask_size, ...) is the lowest ask
    with the largest size on a tie.
    """
    best_bid = latest.groupBy("symbol").agg(
        F.max(F.struct("bid", "bid_size", "exchange")).alias("b")
    )
    best_ask = latest.groupBy("symbol").agg(
        F.min(
            F.struct(
                F.col("ask").alias("ask"),
                (-F.col("ask_size")).alias("neg_size"),
                F.col("exchange").alias("exchange"),
                F.col("ask_size").alias("ask_size"),
            )
        ).alias("a")
    )
    quotes_json = latest.groupBy("symbol").agg(
        F.to_json(
            F.collect_list(
                F.struct(
                    "exchange",
                    "bid",
                    "ask",
                    "bid_size",
                    "ask_size",
                    F.col("ts").cast("string").alias("received_at"),
                )
            )
        ).alias("quotes_json")
    )
    return (
        best_bid.join(best_ask, "symbol")
        .join(quotes_json, "symbol")
        .select(
            "symbol",
            F.col("b.bid").alias("bid"),
            F.col("a.ask").alias("ask"),
            F.col("b.bid_size").alias("bid_size"),
            F.col("a.ask_size").alias("ask_size"),
            F.col("b.exchange").alias("bid_exchange"),
            F.col("a.exchange").alias("ask_exchange"),
            ((F.col("b.bid") + F.col("a.ask")) / 2).alias("mid"),
            (F.col("a.ask") - F.col("b.bid")).alias("spread"),
            "quotes_json",
            F.current_timestamp().alias("ts"),
        )
        .withColumn(
            "spread_bps",
            F.when(F.col("mid") == 0, F.lit(0.0)).otherwise((F.col("spread") / F.col("mid")) * 10000),
        )
    )


def _to_redis_and_alert(best_rows: list) -> None:
    try:
        import redis
    except ImportError:
        return
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    symbols = []
    for row in best_rows:
        data = row.asDict(recursive=True)
        ts = data.get("ts")
        if hasattr(ts, "isoformat"):
            data["ts"] = ts.isoformat()
        quotes = json.loads(data.get("quotes_json") or "[]")
        payload = {
            "symbol": data["symbol"],
            "bid": data["bid"],
            "ask": data["ask"],
            "bid_size": data["bid_size"],
            "ask_size": data["ask_size"],
            "bid_exchange": data["bid_exchange"],
            "ask_exchange": data["ask_exchange"],
            "spread": data["spread"],
            "spread_bps": data["spread_bps"],
            "mid": data["mid"],
            "ts": data["ts"],
            "quotes": quotes,
        }
        client.set(f"price:{data['symbol']}", json.dumps(payload), ex=120)
        symbols.append(data["symbol"])
        prev = LAST_MID.get(data["symbol"])
        LAST_MID[data["symbol"]] = data["mid"]
        if prev and prev > 0:
            change = abs(data["mid"] - prev) / prev * 100
            if change >= ALERT_MOVE_PCT:
                print(
                    f"LARGE MOVE  symbol={data['symbol']}  {prev:.4f} -> {data['mid']:.4f}  ({change:.3f}%)",
                    flush=True,
                )
    if symbols:
        client.set("prices:all", json.dumps(symbols), ex=120)
    client.close()


def process_batch(batch_df, _batch_id: int) -> None:
    if batch_df.rdd.isEmpty():
        return

    quotes = (
        batch_df.select(F.from_json(F.col("value").cast("string"), QUOTE_SCHEMA).alias("q"))
        .select("q.*")
        .filter(F.col("symbol").isNotNull() & (F.col("bid") > 0) & (F.col("ask") > 0))
        .withColumn("ts", F.to_timestamp("ts"))
        .withColumn("symbol", F.upper(F.regexp_replace("symbol", r"[-/_]", "")))
    )

    latest_cols = quotes.select("symbol", "exchange", "bid", "ask", "bid_size", "ask_size", "ts")
    _write_cassandra(latest_cols, "latest_quotes")

    ticks = quotes.select(
        "symbol",
        F.to_date("ts").alias("bucket"),
        "ts",
        "exchange",
        "bid",
        "ask",
        "bid_size",
        "ask_size",
    )
    _write_cassandra(ticks, "quote_ticks")

    spark = quotes.sparkSession
    all_latest = (
        spark.read.format("org.apache.spark.sql.cassandra")
        .options(keyspace="feeds", table="latest_quotes")
        .load()
    )
    best = _best_from_latest(all_latest)
    _write_cassandra(
        best.select(
            "symbol",
            "bid",
            "ask",
            "bid_size",
            "ask_size",
            "bid_exchange",
            "ask_exchange",
            "mid",
            "spread",
            "spread_bps",
            "quotes_json",
            "ts",
        ),
        "best_prices",
    )
    _to_redis_and_alert(best.collect())


def main() -> None:
    spark = _spark()
    spark.sparkContext.setLogLevel("WARN")
    raw = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", KAFKA)
        .option("subscribe", TOPICS)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )
    (
        raw.writeStream.foreachBatch(process_batch)
        .option("checkpointLocation", "/tmp/spark-checkpoints/best-prices")
        .outputMode("update")
        .start()
        .awaitTermination()
    )


if __name__ == "__main__":
    main()
