"""
admin_config.py — 設定管理 REST API

GET /api/admin/config
PUT /api/admin/config/{key}
GET /api/admin/config/history
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.admin_config import (
    ConfigHistoryEntry,
    ConfigItem,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
)
from app.services.config_definition_service import get_config_definition_service
from app.services.config_state_service import (
    ConfigValidationError,
    get_config_state_service,
)

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
        raise HTTPException(
            status_code=400,
            detail=str(exc),
            headers={"X-Error-Code": exc.error_code},
        ) from exc

    return ConfigUpdateResponse(
        key=key,
        old_value=old_value,
        new_value=new_value,
        updated_at=updated_at,
        item=item,
    )

