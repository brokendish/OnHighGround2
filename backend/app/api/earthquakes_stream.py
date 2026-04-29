"""
earthquakes_stream.py — 地震リアルタイムSSE + 開発用publish + ステータスAPI
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.earthquake_event_bus import get_earthquake_event_bus

router = APIRouter(prefix="/api/earthquakes", tags=["earthquakes"])
dev_router = APIRouter(prefix="/api/dev", tags=["dev"])
logger = logging.getLogger(__name__)

_DEV_PUBLISH_ENABLED = os.getenv("DEV_EARTHQUAKE_PUBLISH", "true").lower() not in ("false", "0", "no")
_KEEPALIVE_INTERVAL = 30  # seconds

# SSEペイロードから除去するメタフィールド（内部用、クライアントへ送らない）
_SSE_STRIP_FIELDS = {"_sse_type", "raw"}


async def _sse_generator(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    logger.info("SSE client connected")
    yield ": ping\n\n"
    try:
        from app.services.earthquake_realtime_service import get_realtime_service
        status = get_realtime_service().get_status()
        status_payload = {
            "state": status.get("state"),
            "source": status.get("source", "p2p_ws"),
            "retry_count": status.get("retry_count", 0),
            "next_retry_at": status.get("next_retry_at"),
        }
        data = json.dumps(status_payload, ensure_ascii=False)
        yield f"event: status\ndata: {data}\n\n"
    except Exception as exc:
        logger.debug("SSE initial status skipped: %s", exc)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                event_type = event.get("_sse_type", "earthquake")
                data_payload = {k: v for k, v in event.items() if k not in _SSE_STRIP_FIELDS}
                data = json.dumps(data_payload, ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        get_earthquake_event_bus().unsubscribe(queue)
        logger.info("SSE client disconnected")


@router.get("/stream")
async def earthquake_stream() -> StreamingResponse:
    """地震リアルタイムSSEストリーム。"""
    bus = get_earthquake_event_bus()
    queue = bus.subscribe()
    return StreamingResponse(
        _sse_generator(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/realtime/status")
async def get_realtime_status() -> Dict[str, Any]:
    """P2P WebSocket接続状態を返す。"""
    from app.services.earthquake_realtime_service import get_realtime_service
    return get_realtime_service().get_status()


class DevEarthquakePublishRequest(BaseModel):
    event_id: str
    occurred_at: str
    epicenter_name: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    depth_km: Optional[int] = None
    magnitude: Optional[float] = None
    max_intensity: Optional[str] = None
    tsunami_info: Optional[str] = "津波の心配なし"
    source: str = "dev"


@dev_router.post("/earthquakes/publish")
async def dev_publish_earthquake(body: DevEarthquakePublishRequest) -> Dict[str, Any]:
    """開発用: ダミー地震イベントをSSEに配信する。DEV_EARTHQUAKE_PUBLISH=false で無効化。"""
    if not _DEV_PUBLISH_ENABLED:
        raise HTTPException(status_code=403, detail="dev publish is disabled")
    event = body.model_dump()
    get_earthquake_event_bus().publish(event)
    logger.info("dev publish: event_id=%s epicenter=%s", body.event_id, body.epicenter_name)
    return {"published": True, "event_id": body.event_id}
