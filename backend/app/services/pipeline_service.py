"""
pipeline_service.py — データ処理パイプラインの実行サービス

各ジョブタイプに対応する非同期処理コルーチンを提供する。
ingest → normalize → validate → deploy → (osrm_rebuild)

全処理は asyncio.create_subprocess_exec を使い、stdout/stderr を
ジョブログファイルへリアルタイム書き出しする。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
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
    TileBuildStatus,
    ValidationStatus,
)
from app.services.config_definition_service import get_config_definition_service
from app.services.config_state_service import get_config_state_service
from app.services.dataset_state_service import DatasetStateService
from app.services.job_manager import JobManager

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
_OSRM_REQUIRED_SUFFIXES = (
    ".osrm",
    ".osrm.partition",
    ".osrm.mldgr",
    ".osrm.cells",
    ".osrm.fileIndex",
    ".osrm.ramIndex",
)
_OSRM_CONTAINER_NAMES = {
    "driving": "evacuation-navi-osrm-driving",
    "walking": "evacuation-navi-osrm-walking",
}


# ── 共通ユーティリティ ─────────────────────────────────────────────────────────

async def _run_subprocess(
    args: list[str],
    job: Job,
    jm: JobManager,
    cwd: Optional[Path] = None,
    timeout: Optional[int] = None,
) -> int:
    """サブプロセスを実行し、stdout/stderr をジョブログへ書き出す。戻り値は returncode。

    timeout: 秒数。超過した場合はプロセスを強制終了して returncode=124 を返す。
    """
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

        try:
            await asyncio.wait_for(
                asyncio.gather(_reader(), proc.wait()),
                timeout=float(timeout) if timeout else None,
            )
        except asyncio.TimeoutError:
            jm.log(job, f"[ERROR] タイムアウト ({timeout}秒) でプロセスを強制終了します")
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            return 124

        return proc.returncode
    except FileNotFoundError as exc:
        jm.log(job, f"ERROR: Command not found: {exc}")
        return 127
    except Exception as exc:
        jm.log(job, f"ERROR: {exc}")
        return 1


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _resolve_project_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return (_PROJECT_ROOT / path).resolve()


def _find_first_geojson(paths: list[Path]) -> Optional[Path]:
    for base in paths:
        if base.is_file() and base.suffix.lower() == ".geojson":
            return base
        if base.is_dir():
            candidates = sorted(p for p in base.rglob("*.geojson") if p.is_file())
            if candidates:
                return candidates[0]
    return None


def _resolve_walking_boundary_paths() -> list[Path]:
    tokyo_boundary = _find_first_geojson([
        _resolve_project_path("data_runtime/frontend/layers/tokyo/boundary"),
        _resolve_project_path("data_lake/validated/tokyo/boundary"),
        _resolve_project_path("data_lake/normalized/tokyo/boundary"),
    ])
    kanagawa_boundary = _find_first_geojson([
        _resolve_project_path("data_runtime/frontend/layers/kanagawa/boundary"),
        _resolve_project_path("data_lake/validated/kanagawa/boundary"),
        _resolve_project_path("data_lake/normalized/kanagawa/boundary"),
    ])

    missing = []
    if tokyo_boundary is None:
        missing.append("東京都境界")
    if kanagawa_boundary is None:
        missing.append("神奈川県境界")
    if missing:
        joined = " / ".join(missing)
        raise FileNotFoundError(
            f"{joined} の GeoJSON が見つかりません。管理画面で行政区域データ（東京都・神奈川県）を先に取り込み、反映してください。"
        )

    return [tokyo_boundary, kanagawa_boundary]


async def _build_walking_extract(
    source_pbf: Path,
    output_pbf: Path,
    job: Job,
    jm: JobManager,
) -> bool:
    boundary_paths = _resolve_walking_boundary_paths()
    build_script = _SCRIPTS_DIR / "extract" / "build_walking_extract.py"
    if not build_script.exists():
        raise FileNotFoundError(f"walking extract build script not found: {build_script}")

    output_dir = output_pbf.parent
    _ensure_dir(output_dir)

    cmd = [
        "python3",
        "-u",
        str(build_script),
        "--source",
        str(source_pbf),
        "--output-dir",
        str(output_dir),
        "--output-stem",
        output_pbf.stem.replace(".osm", ""),
        "--force",
    ]
    for boundary_path in boundary_paths:
        cmd.extend(["--boundary", str(boundary_path)])

    jm.log(job, f"Building walking extract from {source_pbf}")
    ret = await _run_subprocess(cmd, job, jm, timeout=3600)
    return ret == 0 and output_pbf.exists()


async def _wait_for_osrm_artifacts(
    mode_dir: Path,
    stem: str,
    job: Job,
    jm: JobManager,
    timeout_seconds: int = 7200,
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if all((mode_dir / f"{stem}{suffix}").exists() for suffix in _OSRM_REQUIRED_SUFFIXES):
            jm.log(job, f"OSRM artifacts ready: {mode_dir / (stem + '.osrm')}")
            return True
        await asyncio.sleep(5)
    jm.log(job, f"Timed out waiting for OSRM artifacts in {mode_dir}")
    return False


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
    # ingest が成功した場合、以前の deploy が中断して "deploying" のまま
    # 残っていても deployable に戻す（stale state のリセット）
    if state.deploy_status == DeployStatus.deploying:
        state.deploy_status = DeployStatus.not_deployed
        jm.log(job, "deploy_status was stuck at 'deploying', reset to 'not_deployed'")

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

    # -u: Python stdout/stderr をアンバッファードにしてリアルタイムログを実現する
    cmd = ["python3", "-u", str(script_path), "--input", input_path, "--output", str(output_path)]
    if defn.transformer_name in {
        "normalize_shelter", "normalize_tsunami",
        "normalize_storm_surge", "normalize_river_flood", "normalize_inland_flood",
    }:
        cmd.extend(["--dataset-id", defn.dataset_id])
    # 避難場所データは layer_type に応じた designation を付与する
    if defn.transformer_name == "normalize_shelter":
        _DESIGNATION_MAP = {
            "evacuation_shelter": "指定避難所",
            "emergency_shelter":  "指定緊急避難場所",
            "shelter":            "指定緊急避難場所",
        }
        designation = _DESIGNATION_MAP.get(defn.layer_type or "")
        if designation:
            cmd.extend(["--designation", designation])
    # 大規模データセット（洪水など）は処理に時間がかかるため 30 分のタイムアウトを設ける
    ret = await _run_subprocess(cmd, job, jm, timeout=1800)

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
    state.last_successful_normalized_path = str(output_path)
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

    cmd = ["python3", str(script_path), "--input", input_path, "--output", str(output_path)]
    if defn.layer_type in {"tsunami", "storm_surge", "flood", "inland_flood"}:
        cmd.extend(["--allowed-geometry-types", "Polygon,MultiPolygon", "--require-bbox"])

    ret = await _run_subprocess(cmd, job, jm, timeout=600)

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

    # OSM は raw を優先し、最新取得データから runtime 用成果物を作る。
    if defn.category == "osm":
        src_path_str = (
            state.current_raw_path
            or state.current_runtime_path
            or state.current_validated_path
        )
    else:
        # コピー元決定: validated > normalized > raw
        src_path_str = (
            state.current_validated_path
            or state.current_normalized_path
            or state.current_raw_path
        )
    if not src_path_str:
        state.deploy_status = DeployStatus.failed
        ss.save(state)
        _fail(job, jm, "DEPLOY_FAILED",
              "反映対象のデータが見つかりませんでした。",
              "先にデータを取り込んでください。")
        return

    src_path = Path(src_path_str)

    if defn.deploy_mode == "copy_file":
        # ── copy_file モード: ディレクトリ内に単一ファイルをコピー（他ファイル保持）─
        if src_path.is_dir():
            # ディレクトリの場合は代表ファイルを探す
            candidates = list(src_path.rglob("*.geojson")) + list(src_path.rglob("*.json"))
            if not candidates:
                state.deploy_status = DeployStatus.failed
                ss.save(state)
                _fail(job, jm, "DEPLOY_FAILED",
                      "反映対象のファイルが見つかりませんでした。",
                      "先にデータを取り込んでください。")
                return
            src_file = candidates[0]
        elif src_path.is_file():
            src_file = src_path
        else:
            state.deploy_status = DeployStatus.failed
            ss.save(state)
            _fail(job, jm, "DEPLOY_FAILED",
                  "反映対象のファイルが存在しません。",
                  "先にデータを取り込んでください。")
            return

        if defn.category == "osm" and defn.osrm_stem:
            dest_file = runtime_dir / f"{defn.osrm_stem}.osm.pbf"
        else:
            dest_file = runtime_dir / src_file.name

        # ── バックアップ（ファイル単位）──────────────────────────────────
        jm.update(job, step=JobStep.backup, progress_message="現在のファイルをバックアップ中...")
        backup_file = runtime_dir / f"{dest_file.stem}.backup{dest_file.suffix}"
        try:
            runtime_dir.mkdir(parents=True, exist_ok=True)
            if dest_file.exists():
                shutil.copy2(dest_file, backup_file)
                state.backup_path = str(backup_file)
                state.backup_at = datetime.utcnow()
                ss.save(state)
                jm.log(job, f"Backup created: {backup_file}")
            else:
                jm.log(job, f"No existing file to backup at: {dest_file}")
        except Exception as exc:
            state.deploy_status = DeployStatus.failed
            ss.save(state)
            _fail(job, jm, "DEPLOY_BACKUP_FAILED",
                  "バックアップの作成に失敗しました。",
                  "ディスク容量または権限を確認してください。")
            return

        # ── ファイルコピー ──────────────────────────────────────────────
        jm.update(job, step=JobStep.deploy, progress_message="実行環境へ反映中...")
        try:
            if defn.category == "osm" and defn.routing_profile == "walking":
                with tempfile.TemporaryDirectory(prefix="ohg-walking-extract-") as tmpdir:
                    tmp_output = Path(tmpdir) / dest_file.name
                    ok = await _build_walking_extract(src_file, tmp_output, job, jm)
                    if not ok:
                        raise RuntimeError("walking extract build failed")
                    shutil.copy2(tmp_output, dest_file)
            else:
                shutil.copy2(src_file, dest_file)
            jm.log(job, f"Deployed file: {dest_file}")
        except Exception as exc:
            state.deploy_status = DeployStatus.failed
            ss.save(state)
            jm.log(job, f"DEPLOY error: {type(exc).__name__}: {exc}")
            _fail(job, jm, "DEPLOY_FAILED",
                  "実行環境への反映に失敗しました。",
                  "ディスク容量または権限を確認してください。バックアップからロールバックできます。")
            return

        state.deploy_status = DeployStatus.deployed
        if defn.category == "osm":
            state.current_validated_path = str(dest_file)
        state.current_runtime_path = str(dest_file)
        state.deployed_at = datetime.utcnow()
        state.is_deployable = False
        state.last_job_id = job.job_id
        ss.save(state)

    else:
        # ── replace_dir モード（デフォルト）: ディレクトリ全体を差し替え ─────
        # ── バックアップ ─────────────────────────────────────────────────────
        jm.update(job, step=JobStep.backup, progress_message="現在のデータをバックアップ中...")
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
                state.deploy_status = DeployStatus.failed
                ss.save(state)
                _fail(job, jm, "DEPLOY_BACKUP_FAILED",
                      "バックアップの作成に失敗しました。",
                      "ディスク容量または権限を確認してください。")
                return

        # ── staging へコピー ────────────────────────────────────────────────
        jm.update(job, step=JobStep.deploy, progress_message="実行環境へ反映中...")
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
                state.deploy_status = DeployStatus.failed
                ss.save(state)
                _fail(job, jm, "DEPLOY_FAILED",
                      "反映対象のファイルが存在しません。",
                      "先にデータを取り込んでください。")
                return

            jm.log(job, f"Staged: {staging_dir}")
        except Exception as exc:
            state.deploy_status = DeployStatus.failed
            ss.save(state)
            _fail(job, jm, "DEPLOY_FAILED",
                  "実行環境へのコピーに失敗しました。",
                  "ディスク容量または権限を確認してください。")
            return

        # ── staging → current に差し替え ─────────────────────────────────
        try:
            if runtime_dir.exists():
                shutil.rmtree(runtime_dir)
            shutil.move(str(staging_dir), str(runtime_dir))
            jm.log(job, f"Deployed to: {runtime_dir}")
        except Exception as exc:
            state.deploy_status = DeployStatus.failed
            ss.save(state)
            jm.log(job, f"DEPLOY error: {type(exc).__name__}: {exc}")
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

    # shelter データを更新した場合は ShelterRegistry のキャッシュを即時クリアする
    if defn.layer_type in ("shelter", "evacuation_shelter", "emergency_shelter"):
        from app.services.shelter_service import get_shelter_registry
        get_shelter_registry().invalidate()
        jm.log(job, "ShelterRegistry cache invalidated")

    # タイルビルドが必要なレイヤーはデプロイ後に非同期で実行
    if defn.requires_tile_build:
        await _do_tile_build(job, defn, state, jm, ss)

    jm.update(job, status=JobStatus.success, step=JobStep.completed,
               progress_message="実行環境への反映が完了しました。",
               exit_code=0)
    jm.log(job, "=== deploy completed ===")


# ── tile_build ────────────────────────────────────────────────────────────────

async def _do_tile_build(
    job: Job,
    defn: DatasetDefinition,
    state: DatasetState,
    jm: JobManager,
    ss: DatasetStateService,
) -> None:
    """
    validated GeoJSON から vector tile（.mbtiles）を生成する。

    出力先: data_runtime/frontend/tiles/{region}/{layer_type}/{dataset_id_snake}.mbtiles
    Martin がこのディレクトリをスキャンし *.mbtiles を自動認識する。

    失敗しても deploy ジョブは成功扱いにする（GeoJSON API が引き続き有効）。
    """
    jm.update(job, step=JobStep.tile_build,
               progress_message="ベクタータイルをビルド中（完了まで数分かかります）...")
    jm.log(job, "--- tile_build start ---")

    state.tile_build_status = TileBuildStatus.running
    ss.save(state)

    # 入力: validated → normalized の順で解決
    src_geojson = state.current_validated_path or state.current_normalized_path
    if not src_geojson or not Path(src_geojson).is_file():
        jm.log(job, "WARN: tile build をスキップ — validated/normalized GeoJSON が存在しません")
        state.tile_build_status = TileBuildStatus.failed
        ss.save(state)
        return

    # 出力パス: data_runtime/frontend/tiles/{region}/{layer_type}/{snake_id}.mbtiles
    tile_stem = defn.dataset_id.lower().replace("-", "_")
    tile_dir  = (_PROJECT_ROOT / "data_runtime" / "frontend" / "tiles"
                 / defn.region / defn.layer_type)
    tile_dir.mkdir(parents=True, exist_ok=True)
    tile_path = tile_dir / f"{tile_stem}.mbtiles"

    # すでに最新の mbtiles が存在する場合はスキップ（ホスト上で手動生成した場合も含む）
    # ただし build スクリプトが要求する maxzoom と MBTiles 内の maxzoom が一致しない場合は再ビルドする。
    # （スクリプトの zoom 設定変更が GeoJSON 変更なしに行われた場合の対策）
    _EXPECTED_MAXZOOM = 16  # build_tiles_flood.sh の --maximum-zoom と合わせること

    def _mbtiles_maxzoom(path: Path) -> int | None:
        """SQLite で MBTiles の maxzoom を読む。失敗時は None を返す。"""
        try:
            import sqlite3 as _sqlite3
            with _sqlite3.connect(str(path)) as con:
                row = con.execute(
                    "SELECT value FROM metadata WHERE name='maxzoom'"
                ).fetchone()
                return int(row[0]) if row else None
        except Exception:
            return None

    if tile_path.exists() and tile_path.stat().st_mtime >= Path(src_geojson).stat().st_mtime:
        current_maxzoom = _mbtiles_maxzoom(tile_path)
        if current_maxzoom is not None and current_maxzoom < _EXPECTED_MAXZOOM:
            jm.log(job, f"tile build 強制実行 — maxzoom 不一致 ({current_maxzoom} < {_EXPECTED_MAXZOOM}): {tile_path}")
        else:
            jm.log(job, f"tile build スキップ — 既存 mbtiles が最新かつ maxzoom={current_maxzoom} (期待値={_EXPECTED_MAXZOOM}): {tile_path}")
            state.tile_build_status = TileBuildStatus.success
            state.current_tile_path = str(tile_path)
            ss.save(state)
            return

    build_script = _SCRIPTS_DIR / "tiles" / "build_tiles_flood.sh"
    if not build_script.exists():
        jm.log(job, f"WARN: tile build スクリプトが見つかりません: {build_script}")
        state.tile_build_status = TileBuildStatus.failed
        ss.save(state)
        return

    ret = await _run_subprocess(
        ["bash", str(build_script), src_geojson, str(tile_path), defn.layer_type],
        job, jm,
        timeout=3600,
    )

    if ret != 0:
        jm.log(job, f"WARN: tile build が失敗しました (exit={ret})。GeoJSON API は引き続き有効です。")
        state.tile_build_status = TileBuildStatus.failed
        ss.save(state)
        return

    state.tile_build_status = TileBuildStatus.success
    state.current_tile_path = str(tile_path)
    ss.save(state)
    jm.log(job, f"tile build 完了: {tile_path}")


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

    backup_path = Path(state.backup_path)
    if not backup_path.exists():
        _fail(job, jm, "ROLLBACK_NOT_AVAILABLE",
              "バックアップが見つかりません。",
              "バックアップファイルが削除されている可能性があります。")
        return

    runtime_dir = (_PROJECT_ROOT / defn.runtime_path).resolve()

    if defn.deploy_mode == "copy_file":
        # ── copy_file モード: バックアップファイルを元のファイル名に戻す ─
        # backup_path 例: /data_runtime/backend/shelters/foo.backup.geojson
        # 元のファイル名を復元: foo.backup.geojson → foo.geojson
        backup_file = backup_path
        original_name = backup_file.stem  # "foo.backup" → stem without .suffix
        # stem は "foo.backup" のままなので suffix を除く処理
        # backup_file.name 例: "tokyo-shelter-001.backup.geojson"
        # → original: "tokyo-shelter-001.geojson"
        parts = backup_file.name.split(".")
        # format: stem + ".backup" + ext → remove the ".backup" part
        if ".backup." in backup_file.name:
            original_name = backup_file.name.replace(".backup.", ".", 1)
        else:
            original_name = backup_file.name
        dest_file = runtime_dir / original_name
        try:
            shutil.copy2(backup_file, dest_file)
            backup_file.unlink()  # バックアップ消費
            jm.log(job, f"Rolled back file: {dest_file} from {backup_file}")
        except Exception as exc:
            _fail(job, jm, "ROLLBACK_FAILED",
                  "ロールバックに失敗しました。",
                  "ディスク容量または権限を確認してください。")
            return

        state.deploy_status = DeployStatus.deployed
        state.current_runtime_path = str(dest_file)
        state.backup_path = None
        state.backup_at = None
        state.is_deployable = False
        state.last_job_id = job.job_id
        ss.save(state)

    else:
        # ── replace_dir モード: ディレクトリ全体をバックアップから復元 ──
        backup_dir = backup_path
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

    # shelter データをロールバックした場合は ShelterRegistry のキャッシュを即時クリアする
    if defn.layer_type in ("shelter", "evacuation_shelter", "emergency_shelter"):
        from app.services.shelter_service import get_shelter_registry
        get_shelter_registry().invalidate()
        jm.log(job, "ShelterRegistry cache invalidated")

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
    runtime 配置済みの PBF を使って OSRM コンテナを再起動し、
    必要な .osrm 成果物が揃うまで待機する。
    """
    jm.update(job, status=JobStatus.running, step=JobStep.osrm_extract,
               progress_message="OSRMルートエンジンの再構築を開始しています...")
    jm.log(job, f"=== osrm_rebuild start: {defn.dataset_id} ===")

    state.osrm_rebuild_status = OsrmRebuildStatus.running
    ss.save(state)

    routing_profile = defn.routing_profile  # "driving" / "walking" / None
    if routing_profile == "driving":
        target_modes = ["driving"]
    elif routing_profile == "walking":
        target_modes = ["walking"]
    else:
        target_modes = ["driving", "walking"]

    jm.log(job, f"routing_profile={routing_profile!r} → modes={target_modes}")

    pbf_src = state.current_runtime_path
    if not pbf_src:
        pbf_src = state.current_validated_path
    if not pbf_src:
        pbf_src = state.current_raw_path

    pbf_path = Path(pbf_src)
    if not pbf_src or not pbf_path.exists():
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "OSM道路データが見つかりませんでした。",
              "先に道路データを取り込み、管理画面で反映してください。")
        state.osrm_rebuild_status = OsrmRebuildStatus.failed
        ss.save(state)
        return

    jm.log(job, f"OSM PBF source: {pbf_path}")

    mode_dirs: dict[str, Path] = {}
    for mode in target_modes:
        if mode == routing_profile and defn.osrm_dir:
            mode_dir = (_PROJECT_ROOT / defn.osrm_dir).resolve()
        elif mode == "driving":
            mode_dir = _resolve_project_path("data_lake/validated/tokyo/osm/driving")
        else:
            mode_dir = _resolve_project_path("data_lake/validated/tokyo/osm/walking/tokyo-kanagawa")
        mode_dir.mkdir(parents=True, exist_ok=True)
        mode_dirs[mode] = mode_dir
        stem = defn.osrm_stem if mode == routing_profile and defn.osrm_stem else (
            "kanto-260214" if mode == "driving" else "tokyo-kanagawa-260214"
        )
        dest_pbf = mode_dir / f"{stem}.osm.pbf"
        if not dest_pbf.exists() or dest_pbf.stat().st_size != pbf_path.stat().st_size:
            jm.log(job, f"Copying PBF to {dest_pbf}...")
            shutil.copy2(pbf_path, dest_pbf)

        for osrm_file in mode_dir.glob("*.osrm*"):
            osrm_file.unlink(missing_ok=True)
        jm.log(job, f"Cleared OSRM index files in {mode_dir}")

    jm.update(job, step=JobStep.osrm_extract,
               progress_message="ルートエンジンを再起動中（この処理は数分かかります）...")

    ret = await _run_subprocess(
        ["docker", "restart"] + [_OSRM_CONTAINER_NAMES[mode] for mode in target_modes],
        job, jm, cwd=_PROJECT_ROOT,
    )

    if ret != 0:
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "OSRM コンテナの再起動に失敗しました。",
              "backend コンテナから Docker を実行できる設定か確認してください。",
              exit_code=ret)
        state.osrm_rebuild_status = OsrmRebuildStatus.failed
        ss.save(state)
        return

    for mode in target_modes:
        stem = defn.osrm_stem if mode == routing_profile and defn.osrm_stem else (
            "kanto-260214" if mode == "driving" else "tokyo-kanagawa-260214"
        )
        jm.update(job,
                  step=JobStep.osrm_customize,
                  progress_message=f"{mode} 用 OSRM 成果物の生成完了を待機中...")
        ready = await _wait_for_osrm_artifacts(mode_dirs[mode], stem, job, jm)
        if not ready:
            _fail(job, jm, "OSRM_REBUILD_FAILED",
                  "OSRM 成果物の生成が時間内に完了しませんでした。",
                  "OSRM コンテナのログを確認してください。")
            state.osrm_rebuild_status = OsrmRebuildStatus.failed
            ss.save(state)
            return

    state.osrm_rebuild_status = OsrmRebuildStatus.success
    state.last_job_id = job.job_id
    ss.save(state)

    _append_history(ss, defn.dataset_id, OperationType.osrm_rebuild, job)

    jm.update(job, status=JobStatus.success, step=JobStep.completed,
               progress_message="ルートエンジンの再構築が完了しました。",
               exit_code=0)
    jm.log(job, "=== osrm_rebuild completed ===")


# ── osrm_profile_rebuild ──────────────────────────────────────────────────────

_PROFILE_CONTAINER = "evacuation-navi-osrm-walking"
_PROFILE_PBF       = "/data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf"
_PROFILE_OSRM      = _PROFILE_PBF.replace(".osm.pbf", ".osrm")
_PROFILE_STEM      = "tokyo-kanagawa-260214"


def _read_osrm_profile_config() -> dict:
    """Config サービス経由で osrm.* ペナルティ値を読む。定義が見つからない場合はデフォルト値を返す。"""
    DEFAULTS = {
        "osrm.trunk_penalty":    0.15,
        "osrm.primary_penalty":  0.25,
        "osrm.secondary_factor": 0.80,
    }
    try:
        def_svc   = get_config_definition_service()
        state_svc = get_config_state_service()
        result = {}
        for key, fallback in DEFAULTS.items():
            defn = def_svc.get(key)
            result[key] = float(state_svc.resolve_value(defn)) if defn else fallback
        return result
    except Exception as exc:
        logger.warning("osrm profile config read failed, using defaults: %s", exc)
        return dict(DEFAULTS)


async def run_osrm_profile_rebuild(job: Job, jm: JobManager) -> None:
    """
    Config 値に基づいて foot.lua を更新し、OSRM ウォーキングエンジンを再ビルドする。

    安全方針:
    - foot.lua は更新前にメモリにバックアップし、失敗時に自動復元する
    - osrm-extract/partition/customize は docker exec で実行（コンテナ停止なし）
    - 全ステップ成功後のみ docker restart でリロード
    - osrm-extract 失敗時は .osrm ファイルに触れないため既存ルート計算は継続できる
    """
    jm.update(job, status=JobStatus.running, step=JobStep.osrm_extract,
               progress_message="OSRMプロファイル再ビルドを準備中...")
    jm.log(job, "=== osrm_profile_rebuild start ===")

    # ── Config 値取得 ─────────────────────────────────────────────────────────
    cfg = _read_osrm_profile_config()
    trunk    = cfg["osrm.trunk_penalty"]
    primary  = cfg["osrm.primary_penalty"]
    secondary = cfg["osrm.secondary_factor"]
    jm.log(job, f"Config: trunk={trunk} primary={primary} secondary={secondary}")

    # ── foot.lua 更新 ─────────────────────────────────────────────────────────
    lua_path = _PROJECT_ROOT / "osrm" / "foot.lua"
    if not lua_path.exists():
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "foot.lua が見つかりません。",
              "docker-compose.yml の osrm マウントを確認してください。")
        return

    original_lua = lua_path.read_text(encoding="utf-8")

    def restore_lua() -> None:
        try:
            lua_path.write_text(original_lua, encoding="utf-8")
            jm.log(job, "foot.lua を元の内容に復元しました")
        except Exception as exc:
            jm.log(job, f"WARNING: foot.lua 復元失敗: {exc}")

    updated = re.sub(r'local OHG_TRUNK_PENALTY\s*=\s*[\d.]+',
                     f'local OHG_TRUNK_PENALTY    = {trunk}', original_lua)
    updated = re.sub(r'local OHG_PRIMARY_PENALTY\s*=\s*[\d.]+',
                     f'local OHG_PRIMARY_PENALTY  = {primary}', updated)
    updated = re.sub(r'local OHG_SECONDARY_FACTOR\s*=\s*[\d.]+',
                     f'local OHG_SECONDARY_FACTOR = {secondary}', updated)

    if updated == original_lua:
        jm.log(job, "WARNING: foot.lua に OHG_* 定数が見つかりません。テンプレートを確認してください。")

    lua_path.write_text(updated, encoding="utf-8")
    jm.log(job, "foot.lua 更新完了")

    # ── osrm-extract ──────────────────────────────────────────────────────────
    jm.update(job, step=JobStep.osrm_extract,
               progress_message="osrm-extract を実行中（数分かかります）...")
    ret = await _run_subprocess(
        ["docker", "exec", _PROFILE_CONTAINER,
         "osrm-extract", "--threads", "2", "-p", "/opt/foot.lua", _PROFILE_PBF],
        job, jm,
    )
    if ret != 0:
        restore_lua()
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "osrm-extract に失敗しました。既存のルートエンジンは変更されていません。",
              "foot.lua の構文またはコンテナの状態を確認してください。",
              exit_code=ret)
        return

    # ── osrm-partition ────────────────────────────────────────────────────────
    jm.update(job, step=JobStep.osrm_partition,
               progress_message="osrm-partition を実行中...")
    ret = await _run_subprocess(
        ["docker", "exec", _PROFILE_CONTAINER,
         "osrm-partition", "--threads", "2", _PROFILE_OSRM],
        job, jm,
    )
    if ret != 0:
        restore_lua()
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "osrm-partition に失敗しました。",
              "ログを確認してください。",
              exit_code=ret)
        return

    # ── osrm-customize ────────────────────────────────────────────────────────
    jm.update(job, step=JobStep.osrm_customize,
               progress_message="osrm-customize を実行中...")
    ret = await _run_subprocess(
        ["docker", "exec", _PROFILE_CONTAINER,
         "osrm-customize", "--threads", "2", _PROFILE_OSRM],
        job, jm,
    )
    if ret != 0:
        restore_lua()
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "osrm-customize に失敗しました。",
              "ログを確認してください。",
              exit_code=ret)
        return

    # ── docker restart（新 .osrm をリロード）──────────────────────────────────
    jm.update(job, step=JobStep.osrm_customize,
               progress_message="OSRMコンテナを再起動中...")
    ret = await _run_subprocess(
        ["docker", "restart", _PROFILE_CONTAINER],
        job, jm,
    )
    if ret != 0:
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "OSRMコンテナの再起動に失敗しました。.osrm ファイルは更新済みです。",
              "Docker の状態を確認し、手動で再起動してください。",
              exit_code=ret)
        return

    # ── 成果物確認（restart 後に osrm-routed が起動するまで待機）────────────────
    jm.update(job, step=JobStep.osrm_customize,
               progress_message="OSRMコンテナの起動完了を確認中...")
    mode_dir = _resolve_project_path(
        "data_lake/validated/tokyo/osm/walking/tokyo-kanagawa"
    )
    ready = await _wait_for_osrm_artifacts(mode_dir, _PROFILE_STEM, job, jm, timeout_seconds=300)
    if not ready:
        _fail(job, jm, "OSRM_REBUILD_FAILED",
              "OSRMコンテナの起動確認がタイムアウトしました。",
              "コンテナログを確認してください。ルート計算は数分後に回復する可能性があります。")
        return

    jm.update(job, status=JobStatus.success, step=JobStep.completed,
               progress_message="OSRMプロファイルの再ビルドが完了しました。",
               exit_code=0)
    jm.log(job, "=== osrm_profile_rebuild completed ===")
