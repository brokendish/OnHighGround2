"""
admin_config.py — 設定管理 REST API

GET  /api/admin/config
PUT  /api/admin/config/{key}
GET  /api/admin/config/history
GET  /api/admin/config/stream   SSE — Config更新通知
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models.admin_config import (
    ConfigHistoryEntry,
    ConfigItem,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
)
from app.services.config_definition_service import get_config_definition_service
from app.services.admin_log_service import write_app_log
from app.services.config_state_service import (
    ConfigValidationError,
    get_config_state_service,
)
from app.services.config_change_notifier import get_config_change_notifier

router = APIRouter(prefix="/api/admin/config", tags=["admin-config"])


@router.get("", response_model=List[ConfigItem])
async def list_config(category: Optional[str] = Query(None)):
    defn_svc = get_config_definition_service()
    state_svc = get_config_state_service()
    definitions = defn_svc.list_all()
    if category:
        definitions = [defn for defn in definitions if defn.category == category]
    return state_svc.list_items(definitions)


@router.get("/history", response_model=List[ConfigHistoryEntry])
async def list_config_history(
    key: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return get_config_state_service().list_history(key=key, limit=limit)


@router.put("/{key:path}", response_model=ConfigUpdateResponse)
async def update_config(key: str, request: ConfigUpdateRequest):
    defn_svc = get_config_definition_service()
    state_svc = get_config_state_service()
    defn = defn_svc.get(key)
    if defn is None:
        raise HTTPException(status_code=404, detail="指定された設定が見つかりません。")

    try:
        old_value, new_value, updated_at, item = state_svc.update_value(defn, request.value)
    except ConfigValidationError as exc:
        try:
            write_app_log(
                f"config update failed key={key} value={request.value} reason={exc}",
                level="ERROR",
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail=str(exc),
            headers={"X-Error-Code": exc.error_code},
        ) from exc

    try:
        write_app_log(
            f"config updated key={key} old={old_value} new={new_value}",
            level="INFO",
        )
    except Exception:
        pass

    try:
        get_config_change_notifier().broadcast(key, new_value)
    except Exception:
        pass

    return ConfigUpdateResponse(
        key=key,
        old_value=old_value,
        new_value=new_value,
        updated_at=updated_at,
        item=item,
    )


@router.get("/stream")
async def stream_config_changes():
    """SSE — Config更新を全接続クライアントにリアルタイム通知する。"""
    async def event_generator():
        async for event in get_config_change_notifier().stream():
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
