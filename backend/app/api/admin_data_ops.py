"""
admin_data_ops.py — Data Operations Console API（operator 専用・認証は app_operator の router 一括 dependency）

GET  /api/admin/data-ops                          一覧（hash / SQLite 全走査なし）
GET  /api/admin/data-ops/{dataset_id}             詳細（反映元 sha256・tile 検査を初回のみ計算しキャッシュ）
GET  /api/admin/data-ops/{dataset_id}/acquisitions 取得履歴（新しい順）
POST /api/admin/data-ops/{dataset_id}/source-set/check
                                                  選択ファイル名集合の取込可否（UI の唯一の判定源。
                                                  upload API / pipeline も同じ source_group で拒否する）

取込自体は既存の /api/admin/datasets/{id}/upload・/fetch-url・/api/admin/upload/* を使う（重複 API を作らない）。
runtime 判定は dataset_runtime_reconcile を再利用し、本 API は DatasetState を保存しない（読み取り専用）。
"""
from __future__ import annotations

import logging
import re
from typing import List

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.services import data_ops_service, source_group
from app.services.acquisition_history import get_acquisition_store
from app.services.dataset_definition_service import get_definition_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/data-ops", tags=["admin-data-ops"])

_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _not_found(dataset_id: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error_code": "DATASET_NOT_FOUND", "detail": f"dataset_id={dataset_id}"})


def _get_defn(dataset_id: str):
    if not _DATASET_ID_RE.fullmatch(dataset_id or ""):
        return None
    return get_definition_service().get(dataset_id)


@router.get("")
async def list_data_ops():
    return data_ops_service.build_console(allow_hash=False, allow_heavy=False)


@router.get("/{dataset_id}")
async def get_data_ops(dataset_id: str):
    if _get_defn(dataset_id) is None:
        return _not_found(dataset_id)
    console = data_ops_service.build_console(dataset_id=dataset_id, allow_hash=True, allow_heavy=True)
    row = next((d for d in console["datasets"] if d["dataset_id"] == dataset_id), None)
    if row is None:
        return JSONResponse(status_code=500, content={"error_code": "DATA_OPS_BUILD_FAILED", "errors": console["errors"]})
    row["current_version"] = console["current_version"]
    row["runtime_error"] = console["runtime_error"]
    row["published_at"] = console["published_at"]
    row["unregistered_runtime_artifacts"] = [
        u for u in console["unregistered_runtime_artifacts"]
        if u["hazard_type"] == row["layer_type"] and u["region"] in (row["region"], None)
    ]
    return row


@router.get("/{dataset_id}/provenance")
async def get_provenance(dataset_id: str):
    """取得元・provenance 健全性だけの軽量版（hash しない）。更新画面の警告表示用。"""
    defn = _get_defn(dataset_id)
    if defn is None:
        return _not_found(dataset_id)
    from app.services.dataset_state_service import get_state_service
    state = get_state_service().init_from_definition(defn)
    return data_ops_service.acquisition_section(defn, state=state)


@router.get("/{dataset_id}/acquisitions")
async def list_acquisitions(dataset_id: str):
    if _get_defn(dataset_id) is None:
        return _not_found(dataset_id)
    records = get_acquisition_store().list(dataset_id)
    return {"dataset_id": dataset_id, "acquisitions": [r.model_dump(mode="json") for r in records]}


class SourceSetCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filenames: List[str] = Field(default_factory=list, max_length=200)
    # True: 単一ファイルを chunk upload で投入する（pattern 不一致の zip は bundle 候補として許可し、
    # zip 内はアップロード完了時にサーバーが判定する）
    single_upload: bool = False


@router.post("/{dataset_id}/source-set/check")
async def check_source_set(dataset_id: str, body: SourceSetCheckRequest):
    defn = _get_defn(dataset_id)
    if defn is None:
        return _not_found(dataset_id)
    names = [n[:255] for n in body.filenames]
    if body.single_upload and len(names) == 1:
        ev = source_group.upload_start_evaluation(defn, names[0])
    else:
        ev = source_group.evaluate_source_set(defn, names)
    return ev.as_dict()
