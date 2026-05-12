"""
admin_datasets.py — データ運用管理画面 REST API

GET  /api/admin/datasets                           データセット一覧
GET  /api/admin/datasets/{dataset_id}              データセット詳細
POST /api/admin/datasets/{dataset_id}/upload       ファイルアップロード
POST /api/admin/datasets/{dataset_id}/fetch-url    URL取得
POST /api/admin/datasets/{dataset_id}/fetch-official 公式取得
POST /api/admin/datasets/{dataset_id}/deploy       実行環境へ反映
POST /api/admin/datasets/{dataset_id}/rollback     ロールバック
POST /api/admin/datasets/{dataset_id}/rebuild-osrm OSRM再構築
GET  /api/admin/datasets/{dataset_id}/history      操作履歴
GET  /api/admin/jobs                               ジョブ一覧
GET  /api/admin/jobs/{job_id}                      ジョブ詳細
GET  /api/admin/jobs/{job_id}/log                  ジョブログ末尾
"""
from __future__ import annotations

import io
import logging
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.models.admin_dataset import (
    DatasetDetail,
    DatasetHistory,
    DatasetState,
    DatasetSummary,
    DeployStatus,
    InputMode,
    Job,
    JobAccepted,
    JobStatus,
    JobType,
    NormalizeStatus,
    OsrmRebuildStatus,
    StorageStatus,
    ValidationStatus,
)
from app.services.dataset_definition_service import get_definition_service
from app.services.dataset_state_service import get_state_service
from app.services.job_manager import get_job_manager
from app.services.active_mapping_service import get_active_mapping_service
from app.services.admin_log_service import write_app_log
from app.services import pipeline_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/datasets", tags=["admin-datasets"])
jobs_router = APIRouter(prefix="/api/admin/jobs", tags=["admin-jobs"])

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# ── エラーコード → レスポンス マッピング ──────────────────────────────────────

_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "DATASET_NOT_FOUND": {
        "user_message": "指定されたデータセットが見つかりません。",
        "action_message": "データセットIDを確認してください。",
    },
    "INVALID_INPUT_MODE": {
        "user_message": "このデータセットでは選択された投入方式は利用できません。",
        "action_message": "別の投入方式を選択してください。",
    },
    "UPLOAD_FILE_TOO_LARGE": {
        "user_message": "ファイルサイズが大きすぎるため、アップロードできませんでした。",
        "action_message": "URL取得または公式サイトから取得を利用してください。",
    },
    "UPLOAD_EXTENSION_NOT_ALLOWED": {
        "user_message": "このファイル形式は受け付けられません。",
        "action_message": "対応ファイル形式を確認してください。",
    },
    "DEPLOY_BLOCKED_VALIDATION_FAILED": {
        "user_message": "内容確認（バリデーション）が完了していないため、反映できません。",
        "action_message": "先にデータの取り込みと内容確認を完了させてください。",
    },
    "DEPLOY_BLOCKED_RUNNING_JOB": {
        "user_message": "現在このデータセットで処理が実行中です。",
        "action_message": "処理が完了するまでお待ちください。",
    },
    "ROLLBACK_NOT_AVAILABLE": {
        "user_message": "戻せるバックアップがありません。",
        "action_message": "一度も反映が行われていないか、バックアップが削除されています。",
    },
    "JOB_ALREADY_RUNNING": {
        "user_message": "このデータセットでは現在別の処理が実行中です。",
        "action_message": "処理が完了してから再実行してください。",
    },
}


def _error_response(error_code: str, status_code: int = 400, **extra) -> JSONResponse:
    msg = _ERROR_MESSAGES.get(error_code, {
        "user_message": "エラーが発生しました。",
        "action_message": "管理者に連絡してください。",
    })
    body = {
        "accepted": False,
        "error_code": error_code,
        **msg,
        **extra,
    }
    return JSONResponse(status_code=status_code, content=body)


def _not_found(dataset_id: str) -> JSONResponse:
    return _error_response("DATASET_NOT_FOUND", 404,
                            detail=f"dataset_id={dataset_id}")


# ── 共通チェック ──────────────────────────────────────────────────────────────

def _check_running_job(dataset_id: str) -> Optional[JSONResponse]:
    jm = get_job_manager()
    if jm.has_running_job(dataset_id):
        return _error_response("JOB_ALREADY_RUNNING")
    return None


def _safe_write_app_log(message: str, level: str = "INFO") -> None:
    try:
        write_app_log(message, level=level)
    except Exception:
        pass


# ── ヘルパー: DatasetSummary 組み立て ─────────────────────────────────────────

def _build_summary(dataset_id: str) -> Optional[DatasetSummary]:
    ds = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()
    am = get_active_mapping_service()

    defn = ds.get(dataset_id)
    if defn is None:
        return None

    state = ss.init_from_definition(defn)
    ss.update_deployable(state, defn)

    is_active = am.is_active(defn.layer_type, defn.region, dataset_id)
    has_backup = bool(state.backup_path)

    return DatasetSummary(
        dataset_id=defn.dataset_id,
        region=defn.region,
        category=defn.category,
        layer_type=defn.layer_type,
        display_name=defn.display_name,
        hint_text=defn.hint_text,
        impact_scope=defn.impact_scope,
        requires_normalize=defn.requires_normalize,
        requires_osrm_rebuild=defn.requires_osrm_rebuild,
        accepted_input_modes=defn.accepted_input_modes,
        browser_upload_enabled=defn.browser_upload_enabled,
        current_file_name=state.current_file_name,
        current_file_size=state.current_file_size,
        storage_status=state.storage_status,
        normalize_status=state.normalize_status,
        validation_status=state.validation_status,
        deploy_status=state.deploy_status,
        osrm_rebuild_status=state.osrm_rebuild_status,
        tile_build_status=state.tile_build_status,
        is_deployable=state.is_deployable,
        updated_at=state.updated_at,
        deployed_at=state.deployed_at,
        last_job_id=state.last_job_id,
        has_running_job=jm.has_running_job(dataset_id),
        has_backup=has_backup,
        is_active=is_active,
    )


# ── GET /datasets ─────────────────────────────────────────────────────────────

@router.get("", response_model=List[DatasetSummary])
async def list_datasets(
    region: Optional[str] = Query(None),
    layer_type: Optional[str] = Query(None),
):
    ds = get_definition_service()
    defns = ds.list_by_region(region) if region else ds.list_all()
    if layer_type:
        defns = [d for d in defns if d.layer_type == layer_type]
    result = []
    for defn in defns:
        s = _build_summary(defn.dataset_id)
        if s:
            result.append(s)
    return result


# ── GET /datasets/{dataset_id} ────────────────────────────────────────────────

@router.get("/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(dataset_id: str):
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    state = ss.init_from_definition(defn)
    ss.update_deployable(state, defn)

    last_job: Optional[Job] = None
    if state.last_job_id:
        last_job = jm.get(state.last_job_id)

    history = ss.load_history(dataset_id)

    return DatasetDetail(
        definition=defn,
        state=state,
        last_job=last_job,
        history=history,
    )


# ── POST /datasets/{dataset_id}/upload ────────────────────────────────────────

@router.post("/{dataset_id}/upload", response_model=JobAccepted)
async def upload_dataset(dataset_id: str, files: List[UploadFile] = File(...)):
    """
    ファイルアップロード。単一ファイルでも複数ファイルでも受け付ける。

    複数ファイルの場合は bundle.zip に自動梱包して正規化スクリプトへ渡す。
    normalize_river_flood.py はこの ZIP を再帰展開してマージする。
    """
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    if InputMode.upload not in defn.accepted_input_modes:
        return _error_response("INVALID_INPUT_MODE")

    if defn.max_browser_upload_mb == 0:
        return _error_response("INVALID_INPUT_MODE",
                                detail="このデータセットはブラウザアップロード非対応です。URL取得を使用してください。")

    if not files:
        return _error_response("UPLOAD_NO_FILE", detail="ファイルが選択されていません")

    # 全ファイルの内容を読み込み（拡張子チェック・サイズ集計も同時に行う）
    contents: List[tuple[str, bytes]] = []
    total_bytes = 0
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if defn.accepted_extensions and ext not in defn.accepted_extensions:
            return _error_response(
                "UPLOAD_EXTENSION_NOT_ALLOWED",
                detail=f"ファイル '{f.filename}' の形式は非対応です。allowed: {defn.accepted_extensions}",
            )
        data = await f.read()
        total_bytes += len(data)
        contents.append((f.filename or f"file{len(contents)}{ext}", data))

    actual_mb = total_bytes / (1024 * 1024)
    if actual_mb > defn.max_browser_upload_mb:
        return _error_response(
            "UPLOAD_FILE_TOO_LARGE",
            detail=f"limit={defn.max_browser_upload_mb}MB actual={actual_mb:.1f}MB",
        )

    # ジョブ二重実行防止
    if guard := _check_running_job(dataset_id):
        return guard

    # 単一ファイル: そのまま保存
    # 複数ファイル: bundle.zip に梱包（normalize スクリプトが ZIP 内を全件展開・マージ）
    if len(contents) == 1:
        filename, data = contents[0]
        ext = Path(filename).suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix=f"{dataset_id}_") as tmp:
            tmp.write(data)
            final_tmp = Path(tmp.name)
        final_tmp = final_tmp.parent / filename
        Path(tmp.name).rename(final_tmp)
    else:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for filename, data in contents:
                zf.writestr(filename, data)
        bundle_bytes = buf.getvalue()
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".zip", prefix=f"{dataset_id}_bundle_"
        ) as tmp:
            tmp.write(bundle_bytes)
            final_tmp = Path(tmp.name)
        logger.info(
            "multi-file upload bundled: %d files → %s (%.1f MB)",
            len(contents), final_tmp.name, len(bundle_bytes) / 1024 / 1024,
        )

    state = ss.init_from_definition(defn)
    job = jm.create(dataset_id, JobType.ingest_upload)
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_ingest_upload(job, defn, state, jm, ss, final_tmp))
    _safe_write_app_log(
        f"dataset request accepted action=ingest_upload dataset_id={dataset_id} job_id={job.job_id}"
    )

    n = len(contents)
    msg = "ファイルを受け付けました。処理を開始します。" if n == 1 else f"{n} ファイルを受け付けました。bundle.zip として処理を開始します。"
    return JobAccepted(job_id=job.job_id, message=msg)


# ── POST /datasets/{dataset_id}/fetch-url ────────────────────────────────────

class FetchUrlRequest(BaseModel):
    url: str


@router.post("/{dataset_id}/fetch-url", response_model=JobAccepted)
async def fetch_url_dataset(dataset_id: str, body: FetchUrlRequest):
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    if InputMode.fetch_url not in defn.accepted_input_modes:
        return _error_response("INVALID_INPUT_MODE")

    if guard := _check_running_job(dataset_id):
        return guard

    state = ss.init_from_definition(defn)
    job = jm.create(dataset_id, JobType.ingest_fetch_url, fetch_url=body.url)
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_ingest_fetch_url(job, defn, state, jm, ss, body.url))
    _safe_write_app_log(
        f"dataset request accepted action=ingest_fetch_url dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="URL取得を受け付けました。バックグラウンドで処理を開始します。")


# ── POST /datasets/{dataset_id}/fetch-official ────────────────────────────────

@router.post("/{dataset_id}/fetch-official", response_model=JobAccepted)
async def fetch_official_dataset(dataset_id: str):
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    if InputMode.fetch_official not in defn.accepted_input_modes:
        return _error_response("INVALID_INPUT_MODE")

    # downloader_name があれば official_source_url は不要（バッチDLスクリプトを使う）
    if not defn.official_source_url and not defn.downloader_name:
        return _error_response("INVALID_INPUT_MODE",
                                detail="official_source_url not configured")

    if guard := _check_running_job(dataset_id):
        return guard

    state = ss.init_from_definition(defn)
    job = jm.create(dataset_id, JobType.ingest_fetch_official,
                     fetch_url=defn.official_source_url or "")
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_ingest_fetch_official(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=ingest_fetch_official dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="公式サイトからの取得を受け付けました。バックグラウンドで処理を開始します。")


# ── POST /datasets/{dataset_id}/generate ─────────────────────────────────────

@router.post("/{dataset_id}/generate", response_model=JobAccepted)
async def generate_dataset(dataset_id: str):
    """
    自動生成データセット（source_type="generated"）の生成を実行する。
    ファイル入力は不要。scripts/derive/{transformer_name}.py を実行する。
    """
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    if not defn.transformer_name:
        return _error_response("INVALID_INPUT_MODE",
                                detail="このデータセットには生成スクリプトが設定されていません")

    if guard := _check_running_job(dataset_id):
        return guard

    state = ss.init_from_definition(defn)
    job = jm.create(dataset_id, JobType.generate)
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_generate(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=generate dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="データの生成を受け付けました。バックグラウンドで処理を開始します。")


# ── POST /datasets/{dataset_id}/deploy ───────────────────────────────────────

@router.post("/{dataset_id}/deploy", response_model=JobAccepted)
async def deploy_dataset(dataset_id: str):
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    state = ss.init_from_definition(defn)
    ss.update_deployable(state, defn)

    # サーバ側 deploy 可能チェック
    if jm.has_running_job(dataset_id):
        return _error_response("DEPLOY_BLOCKED_RUNNING_JOB")

    if not state.is_deployable:
        # 理由を特定
        if defn.requires_validation and state.validation_status != ValidationStatus.passed:
            return _error_response("DEPLOY_BLOCKED_VALIDATION_FAILED")
        return _error_response("DEPLOY_BLOCKED_VALIDATION_FAILED",
                                detail="deploy conditions not met")

    job = jm.create(dataset_id, JobType.deploy)
    state.deploy_status = DeployStatus.deploying
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_deploy(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=deploy dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="実行環境への反映を開始しました。")


# ── POST /datasets/{dataset_id}/rollback ─────────────────────────────────────

@router.post("/{dataset_id}/rollback", response_model=JobAccepted)
async def rollback_dataset(dataset_id: str):
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    state = ss.init_from_definition(defn)

    if jm.has_running_job(dataset_id):
        return _error_response("DEPLOY_BLOCKED_RUNNING_JOB")

    if not state.backup_path:
        return _error_response("ROLLBACK_NOT_AVAILABLE")

    job = jm.create(dataset_id, JobType.rollback)
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_rollback(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=rollback dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="1世代前へのロールバックを開始しました。")


# ── POST /datasets/{dataset_id}/rebuild-osrm ─────────────────────────────────

@router.post("/{dataset_id}/rebuild-osrm", response_model=JobAccepted)
async def rebuild_osrm(dataset_id: str):
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    if not defn.requires_osrm_rebuild:
        return _error_response("INVALID_INPUT_MODE",
                                detail="This dataset does not require OSRM rebuild")

    if jm.has_running_job(dataset_id):
        return _error_response("JOB_ALREADY_RUNNING")

    state = ss.init_from_definition(defn)
    job = jm.create(dataset_id, JobType.osrm_rebuild)
    state.osrm_rebuild_status = OsrmRebuildStatus.running
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_osrm_rebuild(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=osrm_rebuild dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id,
                       message="ルートエンジンの再構築を開始しました。完了まで数分かかります。")


# ── GET /datasets/{dataset_id}/history ───────────────────────────────────────

@router.get("/{dataset_id}/history", response_model=List[DatasetHistory])
async def get_dataset_history(dataset_id: str, limit: int = Query(50, le=200)):
    ds_svc = get_definition_service()
    if ds_svc.get(dataset_id) is None:
        return _not_found(dataset_id)

    ss = get_state_service()
    return ss.load_history(dataset_id, limit=limit)


# ── Jobs API ─────────────────────────────────────────────────────────────────

class JobLogResponse(BaseModel):
    job_id: str
    lines: List[str]
    total_lines: int


@jobs_router.get("", response_model=List[Job])
async def list_jobs(dataset_id: Optional[str] = Query(None), limit: int = Query(20, le=100)):
    jm = get_job_manager()
    return jm.list_recent(dataset_id=dataset_id, limit=limit)


@jobs_router.get("/{job_id}", response_model=Job)
async def get_job(job_id: str):
    jm = get_job_manager()
    job = jm.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id={job_id} not found")
    return job


@jobs_router.get("/{job_id}/log", response_model=JobLogResponse)
async def get_job_log(job_id: str):
    jm = get_job_manager()
    job = jm.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id={job_id} not found")
    lines = jm.log_tail(job_id)
    return JobLogResponse(job_id=job_id, lines=lines, total_lines=len(lines))
