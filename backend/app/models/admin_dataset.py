"""
admin_dataset.py — データ運用管理画面のデータモデル定義

DatasetDefinition : データセットの静的定義（定義ファイルから読み込み）
DatasetState      : データセットの現在状態（実行時に管理）
Job               : 非同期ジョブ管理
DatasetHistory    : 操作履歴
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Enum 定義 ────────────────────────────────────────────────────────────────

class InputMode(str, Enum):
    upload = "upload"
    fetch_url = "fetch_url"
    fetch_official = "fetch_official"


class StorageStatus(str, Enum):
    none = "none"
    stored = "stored"


class NormalizeStatus(str, Enum):
    not_required = "not_required"
    not_started = "not_started"
    running = "running"
    success = "success"
    failed = "failed"


class ValidationStatus(str, Enum):
    not_required = "not_required"
    not_started = "not_started"
    running = "running"
    passed = "pass"
    failed = "fail"


class DeployStatus(str, Enum):
    not_deployed = "not_deployed"
    deployable = "deployable"
    deploying = "deploying"
    deployed = "deployed"
    failed = "failed"


class OsrmRebuildStatus(str, Enum):
    not_applicable = "not_applicable"
    not_started = "not_started"
    running = "running"
    success = "success"
    failed = "failed"


class TileBuildStatus(str, Enum):
    not_applicable = "not_applicable"
    not_started = "not_started"
    running = "running"
    success = "success"
    failed = "failed"


class JobType(str, Enum):
    ingest_upload = "ingest_upload"
    ingest_fetch_url = "ingest_fetch_url"
    ingest_fetch_official = "ingest_fetch_official"
    normalize = "normalize"
    validate = "validate"
    generate = "generate"
    deploy = "deploy"
    rollback = "rollback"
    osrm_rebuild = "osrm_rebuild"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    canceled = "canceled"


class JobStep(str, Enum):
    accepted = "accepted"
    download = "download"
    upload_store = "upload_store"
    normalize = "normalize"
    validate = "validate"
    backup = "backup"
    deploy = "deploy"
    tile_build = "tile_build"
    rollback = "rollback"
    osrm_extract = "osrm_extract"
    osrm_partition = "osrm_partition"
    osrm_customize = "osrm_customize"
    completed = "completed"
    failed = "failed"


class OperationType(str, Enum):
    ingest = "ingest"
    normalize = "normalize"
    validate = "validate"
    generate = "generate"
    deploy = "deploy"
    rollback = "rollback"
    osrm_rebuild = "osrm_rebuild"


# ── DatasetDefinition ────────────────────────────────────────────────────────

class DatasetDefinition(BaseModel):
    """データセットの静的定義。dataset_definitions.json から読み込む。"""

    dataset_id: str
    region: str
    category: str
    display_name: str
    description: str
    hint_text: str
    impact_scope: str

    accepted_input_modes: List[InputMode]
    accepted_extensions: List[str]
    max_browser_upload_mb: int = Field(ge=0)

    requires_normalize: bool
    requires_validation: bool
    requires_deploy: bool
    requires_osrm_rebuild: bool

    source_url: Optional[str] = None
    official_source_url: Optional[str] = None

    raw_storage_path: str
    normalized_storage_path: Optional[str] = None
    validated_storage_path: Optional[str] = None
    runtime_path: str

    transformer_name: Optional[str] = None
    validator_name: Optional[str] = None
    source_type: Optional[str] = None

    # "replace_dir": runtime_path ディレクトリ全体を差し替え（デフォルト）
    # "copy_file"  : runtime_path ディレクトリ内に単一ファイルをコピー（他ファイルを保持）
    deploy_mode: str = "replace_dir"

    # レイヤータイプ（shelter / tsunami / flood / storm_surge / inland_flood / landslide / admin_boundary）
    # インフラ系データセット（dem, osm）は null
    layer_type: Optional[str] = None

    # デプロイ後に vector tile（.mbtiles）をビルドするか
    # True の場合、validated GeoJSON から tippecanoe でタイル生成する
    requires_tile_build: bool = False

    # OSRM routing profile 情報（requires_osrm_rebuild=True の dataset のみ）
    # routing_profile: "driving" or "walking"
    # osrm_stem: OSRM インデックスファイルのベース名（例: "kanto-260214"）
    # osrm_dir: OSRM 成果物ディレクトリ（プロジェクトルート相対）
    routing_profile: Optional[str] = None
    osrm_stem: Optional[str] = None
    osrm_dir: Optional[str] = None

    @property
    def browser_upload_enabled(self) -> bool:
        return self.max_browser_upload_mb > 0


# ── DatasetState ──────────────────────────────────────────────────────────────

class DatasetState(BaseModel):
    """データセットの現在状態。state/{dataset_id}.json に永続化。"""

    dataset_id: str
    current_file_name: Optional[str] = None
    current_file_size: Optional[int] = None
    current_raw_path: Optional[str] = None
    current_normalized_path: Optional[str] = None
    current_validated_path: Optional[str] = None
    current_runtime_path: Optional[str] = None

    current_tile_path: Optional[str] = None

    # 最後に normalize が成功したときのパス（中断後も消えない）
    last_successful_normalized_path: Optional[str] = None

    storage_status: StorageStatus = StorageStatus.none
    normalize_status: NormalizeStatus = NormalizeStatus.not_started
    validation_status: ValidationStatus = ValidationStatus.not_started
    deploy_status: DeployStatus = DeployStatus.not_deployed
    osrm_rebuild_status: OsrmRebuildStatus = OsrmRebuildStatus.not_applicable
    tile_build_status: TileBuildStatus = TileBuildStatus.not_applicable

    is_deployable: bool = False

    updated_at: Optional[datetime] = None
    deployed_at: Optional[datetime] = None
    last_job_id: Optional[str] = None

    # バックアップパス（ロールバック用）
    backup_path: Optional[str] = None
    backup_at: Optional[datetime] = None


# ── Job ───────────────────────────────────────────────────────────────────────

class Job(BaseModel):
    """非同期ジョブ管理。jobs/{job_id}.json に永続化。"""

    job_id: str
    dataset_id: str
    job_type: JobType
    status: JobStatus = JobStatus.queued
    step: JobStep = JobStep.accepted
    progress_message: str = ""

    requested_by: str = "system"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    exit_code: Optional[int] = None
    error_code: Optional[str] = None
    user_message: Optional[str] = None
    action_message: Optional[str] = None

    log_path: Optional[str] = None

    # ジョブが開始したプロセス起動を一意に識別する ID
    # cleanup_stale_running で「別プロセス起動による中断」かどうかの判断に使う
    boot_id: Optional[str] = None

    # ingest_fetch_url 用
    fetch_url: Optional[str] = None


# ── DatasetHistory ────────────────────────────────────────────────────────────

class DatasetHistory(BaseModel):
    """操作履歴。history/{dataset_id}.jsonl に追記。"""

    history_id: str
    dataset_id: str
    operation_type: OperationType
    source_file_name: Optional[str] = None
    artifact_path: Optional[str] = None
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    job_id: Optional[str] = None
    result: str = "success"


# ── API レスポンスモデル ───────────────────────────────────────────────────────

class DatasetSummary(BaseModel):
    """一覧画面用の軽量レスポンス。"""

    dataset_id: str
    region: str
    category: str
    layer_type: Optional[str] = None
    display_name: str
    hint_text: str
    impact_scope: str
    requires_normalize: bool
    requires_osrm_rebuild: bool
    accepted_input_modes: List[InputMode]
    browser_upload_enabled: bool

    # 状態
    current_file_name: Optional[str]
    current_file_size: Optional[int]
    storage_status: StorageStatus
    normalize_status: NormalizeStatus
    validation_status: ValidationStatus
    deploy_status: DeployStatus
    osrm_rebuild_status: OsrmRebuildStatus
    tile_build_status: TileBuildStatus = TileBuildStatus.not_applicable
    is_deployable: bool
    updated_at: Optional[datetime]
    deployed_at: Optional[datetime]
    last_job_id: Optional[str]

    # ジョブ実行中フラグ
    has_running_job: bool = False

    # ロールバック可能か（バックアップが存在する場合 True）
    has_backup: bool = False

    # このデータセットがそのレイヤータイプ+地域の有効データセットかどうか
    is_active: bool = False


class DatasetDetail(BaseModel):
    """詳細画面用の完全レスポンス。"""

    definition: DatasetDefinition
    state: DatasetState
    last_job: Optional[Job] = None
    history: List[DatasetHistory] = []


class JobAccepted(BaseModel):
    """ジョブ受付レスポンス。"""

    accepted: bool = True
    job_id: str
    message: str = "処理を受け付けました"


class ErrorResponse(BaseModel):
    """統一エラーレスポンス。"""

    accepted: bool = False
    error_code: str
    user_message: str
    action_message: str
