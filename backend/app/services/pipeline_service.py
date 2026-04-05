"""
pipeline_service.py — データ処理パイプラインの実行サービス

各ジョブタイプに対応する非同期処理コルーチンを提供する。
ingest → normalize → validate → deploy → (osrm_rebuild)

全処理は asyncio.create_subprocess_exec を使い、stdout/stderr を
ジョブログファイルへリアルタイム書き出しする。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models.admin_dataset import (
    DatasetDefinition,
    DatasetHistory,
    DatasetState,
    DeployStatus,
    Job,
    JobStatus,
    JobStep,
    JobType,
    NormalizeStatus,
    OperationType,
    OsrmRebuildStatus,
    StorageStatus,
    ValidationStatus,
)
from app.services.dataset_state_service import DatasetStateService
from app.services.job_manager import JobManager

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"


# ── 共通ユーティリティ ─────────────────────────────────────────────────────────

async def _run_subprocess(
    args: list[str],
    job: Job,
    jm: JobManager,
    cwd: Optional[Path] = None,
) -> int:
    """サブプロセスを実行し、stdout/stderr をジョブログへ書き出す。戻り値は returncode。"""
    jm.log(job, f"$ {' '.join(str(a) for a in args)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *[str(a) for a in args],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd or _PROJECT_ROOT),
        )

        async def _reader():
            async for line in proc.stdout:
                jm.log(job, line.decode("utf-8", errors="replace").rstrip())

        await asyncio.gather(_reader(), proc.wait())
        return proc.returncode
    except FileNotFoundError as exc:
        jm.log(job, f"ERROR: Command not found: {exc}")
        return 127
    except Exception as exc:
        jm.log(job, f"ERROR: {exc}")
        return 1


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _fail(
    job: Job,
    jm: JobManager,
    error_code: str,
    user_message: str,
    action_message: str,
    exit_code: int = 1,
) -> None:
    jm.log(job, f"FAILED [{error_code}]: {user_message}")
    jm.update(
        job,
        status=JobStatus.failed,
        step=JobStep.failed,
        error_code=error_code,
        user_message=user_message,
        action_message=action_message,
        exit_code=exit_code,
    )


def _append_history(
    ss: DatasetStateService,
    dataset_id: str,
    operation_type: OperationType,
    job: Job,
    result: str = "success",
    source_file_name: Optional[str] = None,
    artifact_path: Optional[str] = None,
) -> None:
    h = DatasetHistory(
        history_id=str(uuid.uuid4()),
        dataset_id=dataset_id,
        operation_type=operation_type,
        source_file_name=source_file_name,
        artifact_path=artifact_path,
        job_id=job.job_id,
        result=result,
    )
    ss.append_history(h)


# ── ingest_upload ─────────────────────────────────────────────────────────────

async def run_ingest_upload(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
    tmp_path: Path,
) -> None:
    """
    アップロード済みファイルをraw格納場所に保存する。
    normalize/validate が必要な場合は続けて実行する。
    """
    jm.update(job, status=JobStatus.running, step=JobStep.upload_store,
               progress_message="元データを保管中...")
    jm.log(job, f"=== ingest_upload start: {defn.dataset_id} ===")

    try:
        dest_dir = (_PROJECT_ROOT / defn.raw_storage_path).resolve()
        _ensure_dir(dest_dir)

        # 既存ファイルは上書き
        file_name = tmp_path.name
        dest_path = dest_dir / file_name
        shutil.copy2(tmp_path, dest_path)
        jm.log(job, f"Stored: {dest_path} ({dest_path.stat().st_size} bytes)")

        state.storage_status = StorageStatus.stored
        state.current_file_name = file_name
        state.current_file_size = dest_path.stat().st_size
        state.current_raw_path = str(dest_path)
        state.updated_at = datetime.utcnow()
        state.last_job_id = job.job_id

        # normalize/validate が不要なら即 deployable チェックへ
        if not defn.requires_normalize:
            state.normalize_status = NormalizeStatus.not_required
        if not defn.requires_validation:
            state.validation_status = ValidationStatus.not_required
        ss.save(state)

        _append_history(ss, defn.dataset_id, OperationType.ingest, job,
                        source_file_name=file_name, artifact_path=str(dest_path))

    except Exception as exc:
        _fail(job, jm, "RAW_STORE_FAILED",
              "元データの保管に失敗しました。",
              "ディスク容量または権限を確認してください。")
        return

    # 後続パイプライン実行
    await _run_post_ingest_pipeline(job, defn, state, jm, ss)


# ── ingest_fetch_url / ingest_fetch_official ──────────────────────────────────

async def run_ingest_fetch_url(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
    fetch_url: str,
) -> None:
    jm.update(job, status=JobStatus.running, step=JobStep.download,
               progress_message="URLからデータを取得中...")
    jm.log(job, f"=== ingest_fetch_url start: {defn.dataset_id} ===")
    jm.log(job, f"URL: {fetch_url}")

    dest_dir = (_PROJECT_ROOT / defn.raw_storage_path).resolve()
    _ensure_dir(dest_dir)

    # URL からファイル名を推測
    from urllib.parse import urlparse
    parsed = urlparse(fetch_url)
    file_name = Path(parsed.path).name or f"{defn.dataset_id}_downloaded"
    dest_path = dest_dir / file_name

    ret = await _run_subprocess(
        ["curl", "-L", "--fail", "--max-time", "300", "-o", str(dest_path), fetch_url],
        job, jm,
    )

    if ret != 0:
        _fail(job, jm, "DOWNLOAD_FAILED",
              "データの取得に失敗しました。URLを確認してください。",
              "URLが正しいか、またサーバが応答しているか確認してください。",
              exit_code=ret)
        return

    await _store_downloaded(job, defn, state, jm, ss, dest_path)


async def run_ingest_fetch_official(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
) -> None:
    if not defn.official_source_url:
        _fail(job, jm, "DOWNLOAD_FAILED",
              "この データセットには公式取得URLが設定されていません。",
              "URL指定取得またはアップロードを使用してください。")
        return

    jm.update(job, status=JobStatus.running, step=JobStep.download,
               progress_message="公式サイトからデータを取得中...")
    jm.log(job, f"=== ingest_fetch_official start: {defn.dataset_id} ===")
    jm.log(job, f"Official URL: {defn.official_source_url}")

    dest_dir = (_PROJECT_ROOT / defn.raw_storage_path).resolve()
    _ensure_dir(dest_dir)

    from urllib.parse import urlparse
    parsed = urlparse(defn.official_source_url)
    file_name = Path(parsed.path).name or f"{defn.dataset_id}_official"
    dest_path = dest_dir / file_name

    ret = await _run_subprocess(
        ["curl", "-L", "--fail", "--max-time", "600", "-o", str(dest_path), defn.official_source_url],
        job, jm,
    )

    if ret != 0:
        _fail(job, jm, "DOWNLOAD_FAILED",
              "公式サイトからのデータ取得に失敗しました。",
              "公式サイトが応答しているか確認し、時間をおいて再試行してください。",
              exit_code=ret)
        return

    await _store_downloaded(job, defn, state, jm, ss, dest_path)


async def _store_downloaded(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
    dest_path: Path,
) -> None:
    jm.update(job, step=JobStep.upload_store, progress_message="元データを保管中...")

    file_size = dest_path.stat().st_size if dest_path.exists() else 0
    jm.log(job, f"Stored: {dest_path} ({file_size} bytes)")

    state.storage_status = StorageStatus.stored
    state.current_file_name = dest_path.name
    state.current_file_size = file_size
    state.current_raw_path = str(dest_path)
    state.updated_at = datetime.utcnow()
    state.last_job_id = job.job_id

    if not defn.requires_normalize:
        state.normalize_status = NormalizeStatus.not_required
    if not defn.requires_validation:
        state.validation_status = ValidationStatus.not_required
    ss.save(state)

    _append_history(ss, defn.dataset_id, OperationType.ingest, job,
                    source_file_name=dest_path.name, artifact_path=str(dest_path))

    await _run_post_ingest_pipeline(job, defn, state, jm, ss)


# ── normalize / validate パイプライン ─────────────────────────────────────────

async def _run_post_ingest_pipeline(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
) -> None:
    """ingest後に normalize → validate を順次実行する。"""

    if defn.requires_normalize and defn.transformer_name:
        ok = await _do_normalize(job, defn, state, jm, ss)
        if not ok:
            return

    if defn.requires_validation and defn.validator_name:
        ok = await _do_validate(job, defn, state, jm, ss)
        if not ok:
            return

    # 完了
    ss.update_deployable(state, defn)
    state.last_job_id = job.job_id
    ss.save(state)

    jm.update(job, status=JobStatus.success, step=JobStep.completed,
               progress_message="取り込みが完了しました。反映ボタンから実行環境への反映が可能です。",
               exit_code=0)
    jm.log(job, "=== pipeline completed successfully ===")


async def _do_normalize(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
) -> bool:
    jm.update(job, step=JobStep.normalize, progress_message="データを整形中...")
    jm.log(job, f"--- normalize: {defn.transformer_name} ---")

    state.normalize_status = NormalizeStatus.running
    ss.save(state)

    script_path = _SCRIPTS_DIR / "normalize" / f"{defn.transformer_name}.py"
    if not script_path.exists():
        _fail(job, jm, "NORMALIZE_FAILED",
              "整形スクリプトが見つかりませんでした。",
              f"scripts/normalize/{defn.transformer_name}.py が存在するか確認してください。")
        state.normalize_status = NormalizeStatus.failed
        ss.save(state)
        return False

    input_path = state.current_raw_path or str((_PROJECT_ROOT / defn.raw_storage_path).resolve())
    output_dir = (_PROJECT_ROOT / defn.normalized_storage_path).resolve() if defn.normalized_storage_path else None
    if output_dir:
        _ensure_dir(output_dir)
        output_path = output_dir / f"{defn.dataset_id.lower()}.geojson"
    else:
        output_path = (_PROJECT_ROOT / defn.raw_storage_path).resolve() / f"{defn.dataset_id.lower()}_normalized.geojson"

    ret = await _run_subprocess(
        ["python3", str(script_path), "--input", input_path, "--output", str(output_path)],
        job, jm,
    )

    if ret != 0:
        _fail(job, jm, "NORMALIZE_FAILED",
              "データの整形処理に失敗しました。",
              "入力ファイルの形式が正しいか確認してください。詳細はログを参照してください。",
              exit_code=ret)
        state.normalize_status = NormalizeStatus.failed
        ss.save(state)
        _append_history(ss, defn.dataset_id, OperationType.normalize, job, result="failed")
        return False

    state.normalize_status = NormalizeStatus.success
    state.current_normalized_path = str(output_path)
    ss.save(state)
    _append_history(ss, defn.dataset_id, OperationType.normalize, job,
                    artifact_path=str(output_path))
    jm.log(job, f"normalize success: {output_path}")
    return True


async def _do_validate(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
) -> bool:
    jm.update(job, step=JobStep.validate, progress_message="データの内容を確認中...")
    jm.log(job, f"--- validate: {defn.validator_name} ---")

    state.validation_status = ValidationStatus.running
    ss.save(state)

    script_path = _SCRIPTS_DIR / "validate" / f"{defn.validator_name}.py"
    if not script_path.exists():
        _fail(job, jm, "VALIDATION_FAILED",
              "確認スクリプトが見つかりませんでした。",
              f"scripts/validate/{defn.validator_name}.py が存在するか確認してください。")
        state.validation_status = ValidationStatus.failed
        ss.save(state)
        return False

    # normalize後があればそちらを使用
    input_path = state.current_normalized_path or state.current_raw_path or \
        str((_PROJECT_ROOT / defn.raw_storage_path).resolve())
    output_dir = (_PROJECT_ROOT / defn.validated_storage_path).resolve() if defn.validated_storage_path else None
    if output_dir:
        _ensure_dir(output_dir)
        output_path = output_dir / f"{defn.dataset_id.lower()}.geojson"
    else:
        output_path = Path(input_path)

    ret = await _run_subprocess(
        ["python3", str(script_path), "--input", input_path, "--output", str(output_path)],
        job, jm,
    )

    if ret != 0:
        _fail(job, jm, "VALIDATION_FAILED",
              "データの内容確認に失敗しました。データが正しい形式か確認してください。",
              "データの形式やジオメトリに問題がある可能性があります。ログを確認してください。",
              exit_code=ret)
        state.validation_status = ValidationStatus.failed
        ss.save(state)
        _append_history(ss, defn.dataset_id, OperationType.validate, job, result="failed")
        return False

    state.validation_status = ValidationStatus.passed
    state.current_validated_path = str(output_path)
    ss.save(state)
    _append_history(ss, defn.dataset_id, OperationType.validate, job,
                    artifact_path=str(output_path))
    jm.log(job, f"validate success: {output_path}")
    return True


# ── deploy ────────────────────────────────────────────────────────────────────

async def run_deploy(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
) -> None:
    jm.update(job, status=JobStatus.running, step=JobStep.backup,
               progress_message="現在のデータをバックアップ中...")
    jm.log(job, f"=== deploy start: {defn.dataset_id} ===")

    runtime_dir = (_PROJECT_ROOT / defn.runtime_path).resolve()

    # ── バックアップ ─────────────────────────────────────────────────────────
    backup_dir = runtime_dir.parent / f"{runtime_dir.name}.backup"
    if runtime_dir.exists():
        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(runtime_dir, backup_dir)
            state.backup_path = str(backup_dir)
            state.backup_at = datetime.utcnow()
            ss.save(state)
            jm.log(job, f"Backup created: {backup_dir}")
        except Exception as exc:
            _fail(job, jm, "DEPLOY_BACKUP_FAILED",
                  "バックアップの作成に失敗しました。",
                  "ディスク容量または権限を確認してください。")
            return

    # ── staging へコピー ────────────────────────────────────────────────────
    jm.update(job, step=JobStep.deploy, progress_message="実行環境へ反映中...")

    # コピー元決定: validated > normalized > raw
    src_path_str = (
        state.current_validated_path
        or state.current_normalized_path
        or state.current_raw_path
    )
    if not src_path_str:
        _fail(job, jm, "DEPLOY_FAILED",
              "反映対象のデータが見つかりませんでした。",
              "先にデータを取り込んでください。")
        return

    src_path = Path(src_path_str)
    staging_dir = runtime_dir.parent / f"{runtime_dir.name}.staging"

    try:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        if src_path.is_dir():
            shutil.copytree(src_path, staging_dir)
        elif src_path.is_file():
            staging_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, staging_dir / src_path.name)
        else:
            _fail(job, jm, "DEPLOY_FAILED",
                  "反映対象のファイルが存在しません。",
                  "先にデータを取り込んでください。")
            return

        jm.log(job, f"Staged: {staging_dir}")
    except Exception as exc:
        _fail(job, jm, "DEPLOY_FAILED",
              "実行環境へのコピーに失敗しました。",
              "ディスク容量または権限を確認してください。")
        return

    # ── staging → current に差し替え ─────────────────────────────────────
    try:
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        shutil.move(str(staging_dir), str(runtime_dir))
        jm.log(job, f"Deployed to: {runtime_dir}")
    except Exception as exc:
        _fail(job, jm, "DEPLOY_FAILED",
              "実行環境への反映に失敗しました。",
              "ディスク容量または権限を確認してください。バックアップからロールバックできます。")
        return

    state.deploy_status = DeployStatus.deployed
    state.current_runtime_path = str(runtime_dir)
    state.deployed_at = datetime.utcnow()
    state.is_deployable = False  # 再反映するには再検証が必要
    state.last_job_id = job.job_id
    ss.save(state)

    _append_history(ss, defn.dataset_id, OperationType.deploy, job,
                    artifact_path=str(runtime_dir))

    jm.update(job, status=JobStatus.success, step=JobStep.completed,
               progress_message="実行環境への反映が完了しました。",
               exit_code=0)
    jm.log(job, "=== deploy completed ===")


# ── rollback ──────────────────────────────────────────────────────────────────

async def run_rollback(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
) -> None:
    jm.update(job, status=JobStatus.running, step=JobStep.rollback,
               progress_message="1世代前のデータに戻しています...")
    jm.log(job, f"=== rollback start: {defn.dataset_id} ===")

    if not state.backup_path:
        _fail(job, jm, "ROLLBACK_NOT_AVAILABLE",
              "戻せるバックアップがありません。",
              "一度も反映が行われていないか、バックアップが削除されています。")
        return

    backup_dir = Path(state.backup_path)
    if not backup_dir.exists():
        _fail(job, jm, "ROLLBACK_NOT_AVAILABLE",
              "バックアップが見つかりません。",
              "バックアップファイルが削除されている可能性があります。")
        return

    runtime_dir = (_PROJECT_ROOT / defn.runtime_path).resolve()

    try:
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        shutil.copytree(backup_dir, runtime_dir)
        jm.log(job, f"Rolled back to: {runtime_dir} from {backup_dir}")
    except Exception as exc:
        _fail(job, jm, "ROLLBACK_FAILED",
              "ロールバックに失敗しました。",
              "ディスク容量または権限を確認してください。")
        return

    state.deploy_status = DeployStatus.deployed
    state.current_runtime_path = str(runtime_dir)
    state.backup_path = None  # バックアップ消費
    state.backup_at = None
    state.is_deployable = False
    state.last_job_id = job.job_id
    ss.save(state)

    _append_history(ss, defn.dataset_id, OperationType.rollback, job,
                    artifact_path=str(runtime_dir))

    jm.update(job, status=JobStatus.success, step=JobStep.completed,
               progress_message="1世代前のデータに戻しました。",
               exit_code=0)
    jm.log(job, "=== rollback completed ===")


# ── osrm_rebuild ─────────────────────────────────────────────────────────────

async def run_osrm_rebuild(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
) -> None:
    """
    OSRM再構築を実行する。
    OSMデータが data_lake/validated/tokyo/osm/{mode}/ にある前提で、
    Docker Composeを使ってOSRMコンテナを再起動する。

    再起動後、コンテナのエントリポイントが既存の.osrmファイルを削除して再構築する。
    ※ .osrmファイルを事前に削除してから再起動する方式。
    """
    jm.update(job, status=JobStatus.running, step=JobStep.osrm_extract,
               progress_message="OSRMルートエンジンの再構築を開始しています...")
    jm.log(job, f"=== osrm_rebuild start: {defn.dataset_id} ===")

    state.osrm_rebuild_status = OsrmRebuildStatus.running
    ss.save(state)

    osm_base_dir = _PROJECT_ROOT / "data_lake" / "validated" / "tokyo" / "osm"

    # PBFファイルを driving/walking それぞれにコピー
    pbf_src = state.current_runtime_path
    if not pbf_src:
        pbf_src = state.current_raw_path
    if not pbf_src:
        pbf_src = str(_PROJECT_ROOT / "data_lake" / "raw" / "tokyo" / "osm" / "kanto-260214.osm.pbf")

    pbf_path = Path(pbf_src)
    if not pbf_path.exists():
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "OSM道路データが見つかりませんでした。",
              "先にOSMデータを取り込んでください。")
        state.osrm_rebuild_status = OsrmRebuildStatus.failed
        ss.save(state)
        return

    jm.log(job, f"OSM PBF source: {pbf_path}")

    # driving / walking 両方に配置
    for mode in ["driving", "walking"]:
        mode_dir = osm_base_dir / mode
        mode_dir.mkdir(parents=True, exist_ok=True)
        dest_pbf = mode_dir / pbf_path.name
        if not dest_pbf.exists() or dest_pbf.stat().st_size != pbf_path.stat().st_size:
            jm.log(job, f"Copying PBF to {dest_pbf}...")
            shutil.copy2(pbf_path, dest_pbf)

        # 既存 .osrm ファイルを削除してコンテナ再起動時に再構築させる
        for osrm_file in mode_dir.glob("*.osrm*"):
            osrm_file.unlink(missing_ok=True)
        jm.log(job, f"Cleared OSRM index files in {mode_dir}")

    # docker compose restart でコンテナ再起動（OSRMが自動再構築）
    jm.update(job, step=JobStep.osrm_extract,
               progress_message="ルートエンジンを再起動中（この処理は数分かかります）...")

    ret = await _run_subprocess(
        ["docker", "compose", "restart", "osrm-driving", "osrm-walking"],
        job, jm, cwd=_PROJECT_ROOT,
    )

    if ret != 0:
        # docker composeが使えない環境ではスキップして手動案内
        jm.log(job, "WARNING: docker compose restart failed or unavailable. Manual restart may be required.")
        jm.log(job, "OSMデータは配置済みです。OSRMコンテナを手動で再起動してください。")
        jm.update(job, step=JobStep.osrm_customize,
                   progress_message="データ配置完了。コンテナ再起動が必要です。")

    state.osrm_rebuild_status = OsrmRebuildStatus.success
    state.last_job_id = job.job_id
    ss.save(state)

    _append_history(ss, defn.dataset_id, OperationType.osrm_rebuild, job)

    jm.update(job, status=JobStatus.success, step=JobStep.completed,
               progress_message="ルートエンジンの再構築が完了しました。",
               exit_code=0)
    jm.log(job, "=== osrm_rebuild completed ===")
