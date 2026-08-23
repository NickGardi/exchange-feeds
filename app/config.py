from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "exchange-feeds"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    testing: bool = False

    symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT"
    stale_quote_seconds: float = 60.0
    snapshot_interval_seconds: float = 15.0
    alert_move_pct: float = 0.5
    alert_cooldown_seconds: float = 15.0

    cassandra_host: str = ""
    cassandra_keyspace: str = "feeds"
    kafka_bootstrap_servers: str = ""
    run_local_feeds: bool = False

    database_url: str = ""
    redis_url: str = ""
    require_database: bool = False
    require_redis: bool = False

    @field_validator("symbols")
    @classmethod
    def _normalize_symbols_field(cls, value: str) -> str:
        parts = [part.strip().upper().replace("-", "").replace("/", "") for part in value.split(",")]
        return ",".join(part for part in parts if part)

    @property
    def symbol_list(self) -> list[str]:
        return [s for s in self.symbols.split(",") if s]

    @property
    def pipeline_mode(self) -> bool:
        """True when Kafka/Spark/Cassandra are configured.

        Local `uvicorn` with empty URLs still runs in-process WebSocket feeds so
        the dashboard works without Docker. Compose sets CASSANDRA_HOST / Kafka
        and the API becomes a read layer only.
        """
        if self.testing or self.run_local_feeds:
            return False
        return bool(self.cassandra_host or self.kafka_bootstrap_servers)

    @field_validator("database_url")
    @classmethod
    def _async_database_url(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://") :]
        if value.startswith("postgresql://") and "+asyncpg" not in value:
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
