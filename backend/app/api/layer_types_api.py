"""
layer_types_api.py — レイヤータイプ定義 & アクティブマッピング REST API

GET  /api/admin/layer-types                          レイヤータイプ一覧
GET  /api/admin/layer-types/{layer_type}             レイヤータイプ詳細

GET  /api/admin/active-mappings                      有効マッピング一覧
PUT  /api/admin/active-mappings/{layer_type}/{region}  有効データセット設定
DELETE /api/admin/active-mappings/{layer_type}/{region} 有効設定解除
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.active_mapping_service import get_active_mapping_service
from app.services.dataset_definition_service import get_definition_service
from app.services.dataset_state_service import get_state_service
from app.models.admin_dataset import DeployStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-layer-types"])

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LAYER_TYPES_PATH = _PROJECT_ROOT / "data_lake" / "registry" / "layer_types.json"


# ── レイヤータイプ定義ロード ───────────────────────────────────────────────────

def _load_layer_types() -> List[Dict[str, Any]]:
    if not _LAYER_TYPES_PATH.exists():
        logger.warning("layer_types.json not found: %s", _LAYER_TYPES_PATH)
        return []
    try:
        with _LAYER_TYPES_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load layer_types.json: %s", exc)
        return []


# ── Pydantic モデル ───────────────────────────────────────────────────────────

class LayerTypeOut(BaseModel):
    layer_type: str
    display_name: str
    description: str
    delivery_mode: str
    icon: str
    sort_order: int


class ActiveMappingOut(BaseModel):
    layer_type: str
    region: str
    dataset_id: str
    dataset_display_name: Optional[str] = None


class SetActiveMappingRequest(BaseModel):
    dataset_id: str


# ── GET /api/admin/layer-types ────────────────────────────────────────────────

@router.get("/layer-types", response_model=List[LayerTypeOut])
async def list_layer_types():
    """登録済みレイヤータイプの一覧を返す。"""
    return _load_layer_types()


# ── GET /api/admin/layer-types/{layer_type} ───────────────────────────────────

@router.get("/layer-types/{layer_type}", response_model=LayerTypeOut)
async def get_layer_type(layer_type: str):
    """指定レイヤータイプの詳細を返す。"""
    for lt in _load_layer_types():
        if lt.get("layer_type") == layer_type:
            return lt
    raise HTTPException(status_code=404, detail=f"layer_type '{layer_type}' not found")


# ── GET /api/admin/active-mappings ────────────────────────────────────────────

@router.get("/active-mappings", response_model=List[ActiveMappingOut])
async def list_active_mappings():
    """全レイヤータイプ×地域の有効データセットマッピングを返す。"""
    svc = get_active_mapping_service()
    ds_svc = get_definition_service()
    mappings = svc.list_all()
    result = []
    for m in mappings:
        defn = ds_svc.get(m["dataset_id"])
        result.append(ActiveMappingOut(
            layer_type=m["layer_type"],
            region=m["region"],
            dataset_id=m["dataset_id"],
            dataset_display_name=defn.display_name if defn else None,
        ))
    return result


# ── PUT /api/admin/active-mappings/{layer_type}/{region} ─────────────────────

@router.put("/active-mappings/{layer_type}/{region}")
async def set_active_mapping(layer_type: str, region: str, body: SetActiveMappingRequest):
    """
    指定レイヤータイプ+地域の有効データセットを設定する。

    対象データセットが存在し、layer_type が一致していることを確認する。
    deploy済みでなくても設定可能（事前宣言ユースケースに対応）。
    """
    ds_svc = get_definition_service()
    defn = ds_svc.get(body.dataset_id)

    if defn is None:
        raise HTTPException(
            status_code=404,
            detail=f"dataset_id '{body.dataset_id}' not found",
        )
    if defn.region != region:
        raise HTTPException(
            status_code=400,
            detail=f"dataset '{body.dataset_id}' belongs to region '{defn.region}', not '{region}'",
        )
    if defn.layer_type != layer_type:
        raise HTTPException(
            status_code=400,
            detail=(
                f"dataset '{body.dataset_id}' has layer_type '{defn.layer_type}', "
                f"expected '{layer_type}'"
            ),
        )

    # デプロイ済みでなければ有効化不可（データが実際に利用可能であることを保証）
    state = get_state_service().init_from_definition(defn)
    if state.deploy_status != DeployStatus.deployed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"dataset '{body.dataset_id}' is not deployed "
                f"(current status: {state.deploy_status.value}). "
                "Deploy the dataset first before setting it as active."
            ),
        )

    get_active_mapping_service().set_active(layer_type, region, body.dataset_id)

    # active mapping 変更を live serving に即時反映（TTL 経過待ちなし）
    if layer_type == "shelter":
        from app.services.shelter_service import get_shelter_registry
        get_shelter_registry().invalidate()
        logger.info("ShelterRegistry cache invalidated after active mapping set: %s:%s", layer_type, region)

    return {
        "accepted": True,
        "layer_type": layer_type,
        "region": region,
        "dataset_id": body.dataset_id,
        "message": f"{defn.display_name} を有効データセットに設定しました。",
    }


# ── DELETE /api/admin/active-mappings/{layer_type}/{region} ──────────────────

@router.delete("/active-mappings/{layer_type}/{region}")
async def unset_active_mapping(layer_type: str, region: str):
    """有効データセット設定を解除する。"""
    removed = get_active_mapping_service().unset_active(layer_type, region)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"No active mapping for {layer_type}:{region}",
        )

    # active mapping 解除を live serving に即時反映（TTL 経過待ちなし）
    if layer_type == "shelter":
        from app.services.shelter_service import get_shelter_registry
        get_shelter_registry().invalidate()
        logger.info("ShelterRegistry cache invalidated after active mapping unset: %s:%s", layer_type, region)

    return {
        "accepted": True,
        "layer_type": layer_type,
        "region": region,
        "message": "有効データセット設定を解除しました。",
    }
