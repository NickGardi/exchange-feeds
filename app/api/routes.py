from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.models.schemas import BestPriceResponse, FeedStatusResponse, HealthResponse, HistoryPoint
from app.runtime import AppRuntime
from app.services.metrics import HTTP_REQUESTS

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
router = APIRouter()


def _runtime(request_app) -> AppRuntime:  # type: ignore[no-untyped-def]
    runtime = getattr(request_app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Aggregator is not running")
    return runtime


def _feed_responses(feeds: list) -> list[FeedStatusResponse]:
    out: list[FeedStatusResponse] = []
    for feed in feeds:
        data = feed.to_dict() if hasattr(feed, "to_dict") else feed
        out.append(FeedStatusResponse.model_validate(data))
    return out


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    runtime = _runtime(request.app)
    HTTP_REQUESTS.labels(path="/health").inc()
    if runtime.settings.pipeline_mode:
        feeds = _feed_responses(await runtime.cache.get_feeds())
        tracked = await asyncio.to_thread(runtime.cassandra.quote_count)
    else:
        feeds = _feed_responses(runtime.feeds.statuses())
        tracked = runtime.aggregator.quote_count()
    connected = sum(1 for feed in feeds if feed.connected)
    status = "ok" if connected == len(feeds) else "degraded" if connected else "starting"
    return HealthResponse(
        status=status,
        app=runtime.settings.app_name,
        symbols=runtime.settings.symbol_list,
        feeds=feeds,
        postgres=runtime.store.available,
        redis=runtime.cache.available,
        cassandra=runtime.cassandra.available,
        tracked_quotes=tracked,
    )


@router.get("/price", response_model=BestPriceResponse)
async def get_price(
    request: Request,
    symbol: str = Query(..., description="Normalized symbol, e.g. BTCUSDT"),
) -> BestPriceResponse:
    runtime = _runtime(request.app)
    HTTP_REQUESTS.labels(path="/price").inc()
    normalized = symbol.strip().upper().replace("-", "").replace("/", "")
    if normalized not in runtime.settings.symbol_list:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} is not tracked")
    body = await runtime.get_price_dict(normalized)
    if body is None:
        raise HTTPException(status_code=404, detail=f"No live quotes yet for {normalized}")
    return BestPriceResponse.model_validate(body)


@router.get("/prices", response_model=dict[str, BestPriceResponse])
async def get_prices(request: Request) -> dict[str, BestPriceResponse]:
    runtime = _runtime(request.app)
    HTTP_REQUESTS.labels(path="/prices").inc()
    return {
        symbol: BestPriceResponse.model_validate(price)
        for symbol, price in (await runtime.get_all_price_dicts()).items()
    }


@router.get("/history", response_model=list[HistoryPoint])
async def get_history(
    request: Request,
    symbol: str = Query(..., description="Normalized symbol, e.g. BTCUSDT"),
    limit: int = Query(50, ge=1, le=500),
) -> list[HistoryPoint]:
    runtime = _runtime(request.app)
    HTTP_REQUESTS.labels(path="/history").inc()
    normalized = symbol.strip().upper().replace("-", "").replace("/", "")
    bars = await runtime.store.bars(normalized, limit=limit)
    if bars:
        return [
            HistoryPoint(
                symbol=row.symbol,
                bid=row.price,
                ask=row.price,
                bid_exchange=row.exchange,
                ask_exchange=row.exchange,
                spread=Decimal("0"),
                mid=row.price,
                ts=row.window_start,
            )
            for row in bars
        ]
    rows = await runtime.store.history(normalized, limit=limit)
    return [
        HistoryPoint(
            symbol=row.symbol,
            bid=row.bid,
            ask=row.ask,
            bid_exchange=row.bid_exchange,
            ask_exchange=row.ask_exchange,
            spread=row.spread,
            mid=row.mid,
            ts=row.ts,
        )
        for row in rows
    ]


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.websocket("/ws/prices")
async def prices_socket(ws: WebSocket) -> None:
    runtime = getattr(ws.app.state, "runtime", None)
    if runtime is None:
        await ws.close(code=1011)
        return
    await runtime.hub.connect(ws)
    try:
        if runtime.settings.pipeline_mode:
            await ws.send_json(await runtime.pipeline_snapshot())
        else:
            await ws.send_json(runtime.snapshot_payload())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        runtime.hub.disconnect(ws)
    except Exception:
        runtime.hub.disconnect(ws)


@router.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
