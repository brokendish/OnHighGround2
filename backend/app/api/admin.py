"""
admin.py — 管理 API エンドポイント

GET /api/admin/hazards             ハザードレイヤー一覧
GET /api/admin/hazards/{layer_key} レイヤー詳細
GET /api/admin/runtime/summary     runtime 全体サマリー
GET /api/admin/logs/sources        利用可能なログソース一覧
GET /api/admin/logs                ログ末尾一覧
GET /api/admin/logs/status         ログサイズ一覧
POST /api/admin/logs/cleanup       ログクリーンアップ
GET /api/admin/logs/stream         SSEログストリーム
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.admin_hazard_service import AdminHazardService
from app.services.admin_log_service import get_admin_log_service, write_navigation_log

router = APIRouter(prefix="/api/admin", tags=["admin"])

_martin_url = os.getenv("MARTIN_INTERNAL_URL", "http://martin:3000")
_service = AdminHazardService(martin_url=_martin_url)
_log_service = get_admin_log_service()


class NavigationLogRequest(BaseModel):
    level: str = Field(default="INFO")
    message: str
    context: Optional[dict] = None


@router.get("/hazards")
async def list_hazard_layers():
    return _service.list_layers()


@router.get("/runtime/summary")
async def get_runtime_summary():
    return _service.get_runtime_summary()


@router.get("/hazards/{layer_key}")
async def get_hazard_layer(layer_key: str):
    try:
        return _service.get_layer(layer_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/logs/sources")
async def list_log_sources():
    return _log_service.list_sources()


@router.get("/logs")
async def get_logs(
    source: str = Query("app"),
    limit: int = Query(200, ge=1, le=1000),
):
    try:
        return {"lines": _log_service.tail_lines(source=source, limit=limit)}
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"invalid source: {exc.args[0]}") from exc


@router.get("/logs/status")
async def get_logs_status():
    return _log_service.status()


@router.post("/logs/cleanup")
async def cleanup_logs():
    return _log_service.cleanup_logs()


@router.post("/logs/navigation")
async def post_navigation_log(payload: NavigationLogRequest):
    try:
        level = str(payload.level or "INFO").upper()
        context = payload.context if isinstance(payload.context, dict) else None
        context_text = ""
        if context:
            compact_items = []
            for key, value in context.items():
                compact_items.append(f"{key}={value}")
            if compact_items:
                context_text = " " + " ".join(compact_items)
        write_navigation_log(f"{payload.message}{context_text}", level=level)
    except Exception:
        return {"ok": False}
    return {"ok": True}


@router.get("/logs/stream")
async def stream_logs(
    source: str = Query("app"),
):
    try:
        _log_service.validate_source(source)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"invalid source: {exc.args[0]}") from exc

    async def event_generator():
        async for event in _log_service.stream_lines(source):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
