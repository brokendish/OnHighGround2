"""
admin.py — 管理 API エンドポイント（read-only）

GET /api/admin/hazards             ハザードレイヤー一覧
GET /api/admin/hazards/{layer_key} レイヤー詳細
GET /api/admin/runtime/summary     runtime 全体サマリー
"""
import os

from fastapi import APIRouter, HTTPException

from app.services.admin_hazard_service import AdminHazardService

router = APIRouter(prefix="/api/admin", tags=["admin"])

_martin_url = os.getenv("MARTIN_INTERNAL_URL", "http://martin:3000")
_service = AdminHazardService(martin_url=_martin_url)


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
