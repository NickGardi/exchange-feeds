from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.models.db import Base, FeedEvent, PriceBar, PriceSnapshot
from app.models.quote import BestPrice

logger = logging.getLogger(__name__)


class SnapshotStore:
    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._engine: AsyncEngine | None = None
        self._session: async_sessionmaker[AsyncSession] | None = None
        self.available = False

    async def connect(self) -> None:
        if not self._url:
            logger.info("PostgreSQL disabled (no DATABASE_URL)")
            return
        self._engine = create_async_engine(
            self._url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
        self._session = async_sessionmaker(self._engine, expire_on_commit=False)
        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as exc:
            logger.warning("PostgreSQL unavailable: %s", exc)
            self.available = False
            await self._engine.dispose()
            self._engine = None
            self._session = None
            return
        self.available = True
        logger.info("PostgreSQL connected")

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session = None
            self.available = False

    async def save_prices(self, prices: Sequence[BestPrice]) -> None:
        if not self.available or self._session is None or not prices:
            return
        rows = [
            PriceSnapshot(
                symbol=price.symbol,
                bid=price.bid,
                ask=price.ask,
                bid_size=price.bid_size,
                ask_size=price.ask_size,
                bid_exchange=price.bid_exchange,
                ask_exchange=price.ask_exchange,
                spread=price.spread,
                mid=price.mid,
                ts=price.ts,
                quotes_json=price.to_dict(),
            )
            for price in prices
        ]
        try:
            async with self._session() as session:
                session.add_all(rows)
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to persist snapshots: %s", exc)

    async def save_event(self, kind: str, source: str, message: str) -> None:
        if not self.available or self._session is None:
            return
        event = FeedEvent(
            kind=kind,
            source=source,
            message=message,
            ts=datetime.now(timezone.utc),
        )
        try:
            async with self._session() as session:
                session.add(event)
                await session.commit()
        except Exception as exc:
            logger.debug("Failed to persist feed event: %s", exc)

    async def history(self, symbol: str, limit: int = 50) -> list[PriceSnapshot]:
        if not self.available or self._session is None:
            return []
        stmt: Select[Any] = (
            select(PriceSnapshot)
            .where(PriceSnapshot.symbol == symbol)
            .order_by(PriceSnapshot.ts.desc())
            .limit(limit)
        )
        async with self._session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def bars(self, symbol: str, limit: int = 50) -> list[PriceBar]:
        if not self.available or self._session is None:
            return []
        stmt: Select[Any] = (
            select(PriceBar)
            .where(PriceBar.symbol == symbol)
            .order_by(PriceBar.window_start.desc())
            .limit(limit)
        )
        async with self._session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())
