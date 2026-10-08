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
POST /api/admin/datasets/{dataset_id}/railway-pmtiles-update 鉄道路線PMTiles更新
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

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.admin_upload import _sanitize_filename

from app.services.operator_auth import OperatorPrincipal, require_operator_role
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
from app.services import admin_atomic_publish as aap
from app.services import dataset_runtime_reconcile as drr
from app.services import source_group

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
    # Data Operations Console: 取得原本セット（source_group_mode）の hard guard
    "SOURCE_SET_INCOMPLETE": {
        "user_message": "必須の原本ファイルが揃っていないため取り込めません。",
        "action_message": "必要な原本を全て選択し、1 回の処理で投入してください（個別投入は canonical を置き換えるため禁止）。",
    },
    "SOURCE_SET_DUPLICATE": {
        "user_message": "同じ種類の原本ファイルが複数選択されています。",
        "action_message": "年度・版が混在していないか確認し、各原本を 1 ファイルずつ選択してください。",
    },
    "SOURCE_SET_UNEXPECTED_FILE": {
        "user_message": "想定外のファイルが含まれています。",
        "action_message": "データセットの原本ファイル名規約を確認してください。",
    },
    "SOURCE_SET_TOO_MANY_FILES": {
        "user_message": "このデータセットに投入できるファイル数を超えています。",
        "action_message": "原本を 1 ファイルだけ選択してください。",
    },
    "SOURCE_SET_EMPTY": {
        "user_message": "ファイルが選択されていません。",
        "action_message": "原本ファイルを選択してください。",
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
    "FLOOD_ROUTING_MIGRATION_REQUIRED": {
        "user_message": "洪水データの判定用形式（routing）への初回移行が必要です。通常の反映はできません。",
        "action_message": "OWNER の承認参照を入力し、「初回移行として反映」を実行してください。",
    },
    "FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE": {
        "user_message": "洪水 routing 形式への移行指定は、この状態では使用できません。",
        "action_message": "移行は洪水データ（flood）で、旧形式が実行環境に残っている場合だけ指定できます。通常の反映を実行してください。",
    },
    "FLOOD_ROUTING_MIGRATION_APPROVAL_REQUIRED": {
        "user_message": "初回移行には OWNER の承認参照が必要です。",
        "action_message": "3〜200 文字の英数字と . _ : @ / + ( ) - 空白で承認参照を入力してください。",
    },
    "ATOMIC_PUBLISH_UNSUPPORTED": {
        "user_message": "このデータ種別は管理画面から実行環境へ反映できません（正式公開経路へ未統合）。",
        "action_message": "津波データの公開方式（どの版を判定に使うか）の決定後に対応します。管理者に連絡してください。",
    },
    "ROLLBACK_ATOMIC_PUBLISH_MANAGED": {
        "user_message": "このデータは実行環境の version 単位で管理されているため、ここからは戻せません。",
        "action_message": "operator が activate_version.py --rollback <version-id> で version を戻してください。",
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
    # 実 runtime（current + manifest）と照合して表示を同期する。一覧は 5 秒周期で呼ばれるため、
    # 反映元 sha256 がキャッシュに無ければ計算しない（判定不能なら state を変更しない）。
    _reconcile_quietly(defn, state, ss, allow_hash=False)

    is_active = am.is_active(defn.layer_type, defn.region, dataset_id)
    has_backup = bool(state.backup_path)

    return DatasetSummary(
        dataset_id=defn.dataset_id,
        region=defn.region,
        category=defn.category,
        layer_type=defn.layer_type,
        source_type=defn.source_type,
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


def _reconcile_quietly(defn, state, ss, allow_hash: bool):
    """runtime 照合の失敗で API 自体を失敗させない（state はそのまま返す）。"""
    try:
        return drr.reconcile_one(defn, state, ss, allow_hash=allow_hash, persist=True)
    except Exception as exc:  # noqa: BLE001 — 表示用の同期であり API の成否に影響させない
        logger.warning("runtime reconcile failed: dataset_id=%s: %s", defn.dataset_id, exc)
        return None


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

@router.get("/runtime-reconcile")
async def get_runtime_reconcile_report():
    """全 dataset の runtime 照合結果と registry 外 runtime artifact（整合性ダッシュボード用の素材）。
    反映元 sha256 はキャッシュのみ使用し、ここでは計算しない（state も変更しない）。"""
    return drr.reconcile_all(allow_hash=False, persist=False)


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
    _reconcile_quietly(defn, state, ss, allow_hash=True)

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
async def upload_dataset(
    dataset_id: str,
    request: Request,
    files: List[UploadFile] = File(...),
    principal: OperatorPrincipal = Depends(require_operator_role),
):
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

    # 取得原本セットの hard guard（UI の判定と同じ source_group.evaluate_source_set）。
    # 複数ファイルは原本名の集合で判定する（内容を読む前に拒否）。単一ファイルは bundle zip の
    # 可能性があるため一時保存後に zip 内を判定する（下記）。
    if len(files) > 1:
        ev = source_group.evaluate_source_set(defn, [_sanitize_filename(f.filename or "") for f in files])
        if not ev.ok:
            return _error_response(ev.error_code, 422, detail=" / ".join(ev.blocking_reasons),
                                   source_set=ev.as_dict())

    # 全ファイルの内容を読み込み（拡張子チェック・サイズ集計も同時に行う）
    contents: List[tuple[str, bytes]] = []
    total_bytes = 0
    for f in files:
        # クライアント供給のfilenameは、ディレクトリ成分（path traversal対策）と
        # 英数字・`-`・`.`・space以外の文字（admin UIでの表示時にHTML/JS
        # injectionの経路となり得るため）をあらかじめ除去する
        # （admin_upload.pyの_sanitize_filenameと同一規則、単一の真実源）。
        safe_filename = _sanitize_filename(f.filename or "")
        ext = Path(safe_filename).suffix.lower()
        if defn.accepted_extensions and ext not in defn.accepted_extensions:
            return _error_response(
                "UPLOAD_EXTENSION_NOT_ALLOWED",
                detail=f"ファイル '{safe_filename}' の形式は非対応です。allowed: {defn.accepted_extensions}",
            )
        data = await f.read()
        total_bytes += len(data)
        contents.append((safe_filename or f"file{len(contents)}{ext}", data))

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
        ev = source_group.evaluate_stored_file(defn, final_tmp)
        if not ev.ok:
            final_tmp.unlink(missing_ok=True)
            return _error_response(ev.error_code, 422, detail=" / ".join(ev.blocking_reasons),
                                   source_set=ev.as_dict())
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
    job = jm.create(
        dataset_id, JobType.ingest_upload,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_ingest_upload(
        job, defn, state, jm, ss, final_tmp,
        acquisition={"method": "upload", "original_files": [name for name, _ in contents]},
    ))
    _safe_write_app_log(
        f"dataset request accepted action=ingest_upload dataset_id={dataset_id} job_id={job.job_id}"
    )

    n = len(contents)
    msg = "ファイルを受け付けました。処理を開始します。" if n == 1 else f"{n} ファイルを受け付けました。bundle.zip として処理を開始します。"
    return JobAccepted(job_id=job.job_id, message=msg)


# ── POST /datasets/{dataset_id}/fetch-url ────────────────────────────────────

class FetchUrlRequest(BaseModel):
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

    url: str


@router.post("/{dataset_id}/fetch-url", response_model=JobAccepted)
async def fetch_url_dataset(
    dataset_id: str,
    body: FetchUrlRequest,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
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
    job = jm.create(
        dataset_id, JobType.ingest_fetch_url, fetch_url=body.url,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_ingest_fetch_url(job, defn, state, jm, ss, body.url))
    _safe_write_app_log(
        f"dataset request accepted action=ingest_fetch_url dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="URL取得を受け付けました。バックグラウンドで処理を開始します。")


# ── POST /datasets/{dataset_id}/fetch-official ────────────────────────────────

@router.post("/{dataset_id}/fetch-official", response_model=JobAccepted)
async def fetch_official_dataset(
    dataset_id: str,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
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
    job = jm.create(
        dataset_id, JobType.ingest_fetch_official,
        fetch_url=defn.official_source_url or "",
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_ingest_fetch_official(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=ingest_fetch_official dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="公式サイトからの取得を受け付けました。バックグラウンドで処理を開始します。")


# ── POST /datasets/{dataset_id}/generate ─────────────────────────────────────

@router.post("/{dataset_id}/generate", response_model=JobAccepted)
async def generate_dataset(
    dataset_id: str,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
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
    job = jm.create(
        dataset_id, JobType.generate,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_generate(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=generate dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="データの生成を受け付けました。バックグラウンドで処理を開始します。")


# ── POST /datasets/{dataset_id}/railway-pmtiles-update ───────────────────────

@router.post("/{dataset_id}/railway-pmtiles-update", response_model=JobAccepted)
async def railway_pmtiles_update(
    dataset_id: str,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
    """
    鉄道路線 PMTiles 更新。source_type="railway_pmtiles" のデータセット専用。
    OSM PBF ダウンロード → PMTiles 生成 → 検証 → atomic rename を一括実行する。
    """
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    if defn.source_type != "railway_pmtiles":
        return _error_response("INVALID_INPUT_MODE",
                                detail="このエンドポイントは source_type=railway_pmtiles のデータセット専用です")

    if guard := _check_running_job(dataset_id):
        return guard

    state = ss.init_from_definition(defn)
    job = jm.create(
        dataset_id, JobType.railway_pmtiles_update,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_railway_pmtiles_update(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=railway_pmtiles_update dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id,
                       message="鉄道路線 PMTiles の更新を受け付けました。OSM ダウンロードから PMTiles 生成まで自動実行します。")


# ── GET /datasets/{dataset_id}/publish-status ────────────────────────────────

@router.get("/{dataset_id}/publish-status")
async def get_publish_status(dataset_id: str):
    """実行環境（current + manifest + artifact）を正とした反映状態。DatasetState もここで同期する。

    publish_mode: atomic / unsupported（管理画面から反映不可）/ legacy（従来経路）
    runtime_status: published / not_published / stale / mismatch / unsupported / legacy / unknown
    （定義は app/services/dataset_runtime_reconcile.py）
    """
    defn = get_definition_service().get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)
    ss = get_state_service()
    state = ss.init_from_definition(defn)
    ss.update_deployable(state, defn)
    view = drr.load_runtime_view()
    try:
        res = drr.reconcile_one(defn, state, ss, allow_hash=True, persist=True, view=view)
        reconciled = res.runtime_status != drr.UNKNOWN
    except Exception as exc:  # noqa: BLE001 — 判定不能は unknown として返す（fail-open にしない）
        logger.warning("publish-status reconcile failed: dataset_id=%s: %s", dataset_id, exc)
        res = drr.ReconcileResult(dataset_id=dataset_id, layer_type=defn.layer_type, region=defn.region,
                                  publish_mode="unknown", runtime_status=drr.UNKNOWN,
                                  current_version=view.version_id, reason=str(exc))
        reconciled = False
    legacy = aap.legacy_flood_files_in_current() if res.publish_mode == "atomic" else []
    unregistered = [a for a in drr.unregistered_runtime_artifacts(view, {res.runtime_rel} if res.runtime_rel else set())
                    if a["hazard_type"] == defn.layer_type and a["region"] == defn.region]
    return {
        "dataset_id": dataset_id,
        "current_version": res.current_version,
        "publish_mode": res.publish_mode,
        "runtime_status": res.runtime_status,
        "artifact_present": res.artifact_present,
        "runtime_path": res.runtime_path,
        "runtime_sha256": res.runtime_sha256,
        "source_sha256": res.source_sha256,
        "matches_source": res.matches_source,
        "state_reconciled": reconciled,
        "reason": res.reason,
        "deployable": bool(state.is_deployable),
        "deploy_status": state.deploy_status,
        "provenance": res.provenance,
        "flood_routing_migration_required": bool(legacy),
        "migration_allowed_for_dataset": res.publish_mode == "atomic" and defn.layer_type == "flood",
        "legacy_flood_files": legacy,
        # 同じ layer_type / region に存在する registry 外の runtime artifact（削除はしない）
        "unregistered_runtime_artifacts": unregistered,
        # provenance 健全性（警告のみ・反映は止めない）。atomic publish は current を種に全 region を
        # 積み直すため、他 dataset の不整合データも同じ publish で再公開される → 範囲内の mismatch を列挙する
        **_provenance_warnings(defn, state, res.publish_mode),
    }


def _provenance_warnings(defn, state, publish_mode) -> dict:
    from app.services import data_ops_service
    out = {"provenance_validity": None, "provenance_reason": None, "provenance_mismatch_in_publish_scope": []}
    try:
        own = data_ops_service.acquisition_section(defn, state=state)
        out["provenance_validity"], out["provenance_reason"] = own["validity"], own["validity_reason"]
        if publish_mode != "atomic":
            return out
        regions = set(aap.publish_regions())
        ss = get_state_service()
        for other in get_definition_service().list_all():
            if other.layer_type not in aap.HAZARD_PUBLISH_LAYER_TYPES or other.region not in regions:
                continue
            acq = own if other.dataset_id == defn.dataset_id else data_ops_service.acquisition_section(
                other, state=ss.init_from_definition(other))
            if acq["validity"] == "provenance_mismatch":
                out["provenance_mismatch_in_publish_scope"].append(
                    {"dataset_id": other.dataset_id, "reason": acq["validity_reason"]})
    except Exception as exc:  # noqa: BLE001 — 警告情報の取得失敗で publish-status 全体を失敗させない
        logger.warning("provenance warning lookup failed: %s: %s", defn.dataset_id, exc)
        out["provenance_error"] = f"{type(exc).__name__}: {exc}"
    return out


# ── POST /datasets/{dataset_id}/deploy ───────────────────────────────────────

class DeployRequest(BaseModel):
    """反映リクエスト（body 省略時は通常反映）。"""
    model_config = ConfigDict(extra="forbid")

    # 洪水 routing 初回移行（OWNER 承認参照必須）。通常反映では指定しない。暗黙に付与しない。
    allow_flood_routing_migration: bool = False
    owner_approval_ref: Optional[str] = None


@router.post("/{dataset_id}/deploy", response_model=JobAccepted)
async def deploy_dataset(
    dataset_id: str,
    request: Request,
    body: Optional[DeployRequest] = None,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
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

    if defn.layer_type in aap.ATOMIC_PUBLISH_UNSUPPORTED_LAYER_TYPES:
        return _error_response("ATOMIC_PUBLISH_UNSUPPORTED", detail=f"layer_type={defn.layer_type}")

    # 洪水 routing 初回移行の指定を検証する（暗黙の migration 許可はしない）
    body = body or DeployRequest()
    migration_ref: Optional[str] = None
    if body.allow_flood_routing_migration:
        if defn.layer_type != "flood":
            return _error_response("FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE",
                                    detail=f"layer_type={defn.layer_type}")
        try:
            migration_ref = aap.validate_owner_approval_ref(body.owner_approval_ref)
        except ValueError as exc:
            return _error_response("FLOOD_ROUTING_MIGRATION_APPROVAL_REQUIRED", detail=str(exc))
        if not aap.legacy_flood_files_in_current():
            return _error_response("FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE",
                                    detail="実行環境は routing 形式へ移行済みです")
    elif body.owner_approval_ref:
        return _error_response("FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE",
                                detail="owner_approval_ref は allow_flood_routing_migration と併用してください")
    elif defn.layer_type in aap.ATOMIC_PUBLISH_LAYER_TYPES and aap.legacy_flood_files_in_current():
        # atomic publish は全 region をまとめて検証するため、旧 flood が残る間は flood 以外の反映も拒否される
        return _error_response("FLOOD_ROUTING_MIGRATION_REQUIRED",
                                detail=f"legacy={aap.legacy_flood_files_in_current()[:3]}")

    job = jm.create(
        dataset_id, JobType.deploy,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.deploy_status = DeployStatus.deploying
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_deploy(job, defn, state, jm, ss,
                                               flood_routing_migration_ref=migration_ref))
    _safe_write_app_log(
        f"dataset request accepted action=deploy dataset_id={dataset_id} job_id={job.job_id}"
        f"{' flood_routing_migration=1' if migration_ref else ''}"
    )

    if migration_ref:
        return JobAccepted(job_id=job.job_id, message="洪水 routing 形式への初回移行として反映を開始しました。")
    return JobAccepted(job_id=job.job_id, message="実行環境への反映を開始しました。")


# ── POST /datasets/{dataset_id}/rollback ─────────────────────────────────────

@router.post("/{dataset_id}/rollback", response_model=JobAccepted)
async def rollback_dataset(
    dataset_id: str,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(dataset_id)
    if defn is None:
        return _not_found(dataset_id)

    state = ss.init_from_definition(defn)

    if jm.has_running_job(dataset_id):
        return _error_response("DEPLOY_BLOCKED_RUNNING_JOB")

    if defn.layer_type in aap.ATOMIC_PUBLISH_LAYER_TYPES | aap.ATOMIC_PUBLISH_UNSUPPORTED_LAYER_TYPES:
        return _error_response("ROLLBACK_ATOMIC_PUBLISH_MANAGED")

    if not state.backup_path:
        return _error_response("ROLLBACK_NOT_AVAILABLE")

    job = jm.create(
        dataset_id, JobType.rollback,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_rollback(job, defn, state, jm, ss))
    _safe_write_app_log(
        f"dataset request accepted action=rollback dataset_id={dataset_id} job_id={job.job_id}"
    )

    return JobAccepted(job_id=job.job_id, message="1世代前へのロールバックを開始しました。")


# ── POST /datasets/{dataset_id}/rebuild-osrm ─────────────────────────────────

@router.post("/{dataset_id}/rebuild-osrm", response_model=JobAccepted)
async def rebuild_osrm(
    dataset_id: str,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
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
    job = jm.create(
        dataset_id, JobType.osrm_rebuild,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
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
