"""
Airflow DAG: historical storage.

Every minute, roll Cassandra quote_ticks into 1-minute bars in PostgreSQL:

    window_start, symbol, exchange, price (avg mid), volume (sum of sizes)

Open http://localhost:8085  (admin / admin from `airflow standalone`).
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from airflow import DAG
from airflow.operators.python import PythonOperator

CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "cassandra")
POSTGRES_URL = os.getenv(
    "AIRFLOW_POSTGRES_URL",
    "postgresql://feeds:feeds@postgres:5432/feeds",
)


def rollup_minute_bars() -> None:
    from cassandra.cluster import Cluster
    import psycopg2

    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=5)
    symbols = [s.strip() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
    buckets = {start.date(), now.date()}

    cluster = Cluster([CASSANDRA_HOST])
    session = cluster.connect("feeds")
    groups: dict[tuple, list] = defaultdict(list)
    for symbol in symbols:
        for bucket in buckets:
            rows = session.execute(
                """
                SELECT ts, exchange, bid, ask, bid_size, ask_size
                FROM quote_ticks
                WHERE symbol = %s AND bucket = %s
                """,
                (symbol, bucket),
            )
            for row in rows:
                ts = row.ts
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < start:
                    continue
                window = ts.replace(second=0, microsecond=0)
                mid = (float(row.bid) + float(row.ask)) / 2
                volume = float(row.bid_size or 0) + float(row.ask_size or 0)
                groups[(window, symbol, row.exchange)].append((mid, volume))
    cluster.shutdown()

    conn = psycopg2.connect(POSTGRES_URL)
    conn.autocommit = True
    cur = conn.cursor()
    for (window, symbol, exchange), points in groups.items():
        price = sum(p for p, _ in points) / len(points)
        volume = sum(v for _, v in points)
        cur.execute(
            """
            INSERT INTO price_bars (window_start, symbol, exchange, price, volume)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (window_start, symbol, exchange)
            DO UPDATE SET price = EXCLUDED.price, volume = EXCLUDED.volume
            """,
            (window, symbol, exchange, Decimal(str(price)), Decimal(str(volume))),
        )
    cur.close()
    conn.close()
    print(f"rolled up {len(groups)} one-minute bars", flush=True)


with DAG(
    dag_id="crypto_price_bars_1m",
    start_date=datetime(2026, 1, 1),
    schedule="* * * * *",
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(seconds=20)},
    tags=["exchange-feeds", "historical"],
    doc_md="1-minute bars from Cassandra ticks into PostgreSQL.",
) as dag:
    PythonOperator(task_id="rollup_minute_bars", python_callable=rollup_minute_bars)
