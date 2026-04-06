"""
dataset_state_service.py — データセット状態の永続管理サービス

状態ファイルは data_lake/admin/state/{dataset_id}.json に保存する。
履歴は data_lake/admin/history/{dataset_id}.jsonl に追記する。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.models.admin_dataset import (
    DatasetDefinition,
    DatasetHistory,
    DatasetState,
    DeployStatus,
    NormalizeStatus,
    OsrmRebuildStatus,
    StorageStatus,
    ValidationStatus,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ADMIN_STATE_DIR = _PROJECT_ROOT / "data_lake" / "admin" / "state"
_ADMIN_HISTORY_DIR = _PROJECT_ROOT / "data_lake" / "admin" / "history"

_MAX_HISTORY_LINES = 200


class DatasetStateService:
    """データセット状態を JSON ファイルで永続管理する。"""

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        history_dir: Optional[Path] = None,
    ) -> None:
        self._state_dir = (state_dir or _ADMIN_STATE_DIR).resolve()
        self._history_dir = (history_dir or _ADMIN_HISTORY_DIR).resolve()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._history_dir.mkdir(parents=True, exist_ok=True)

    # ── state CRUD ────────────────────────────────────────────────────────────

    def _state_path(self, dataset_id: str) -> Path:
        return self._state_dir / f"{dataset_id}.json"

    def load(self, dataset_id: str) -> DatasetState:
        path = self._state_path(dataset_id)
        if not path.exists():
            return self._default_state(dataset_id)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # 古い状態ファイルが別マシンの絶対パスを持っている場合は無効化して再推定させる
        state = DatasetState(**data)
        if self._has_stale_paths(state):
            logger.info("Stale absolute paths detected in state for %s, will re-infer.", dataset_id)
            path.unlink()
            return self._default_state(dataset_id)
        return state

    def _has_stale_paths(self, state: DatasetState) -> bool:
        """状態ファイルのパスが現在のマシンに存在しない場合 True を返す。"""
        for attr in ("current_raw_path", "current_normalized_path",
                     "current_validated_path", "current_runtime_path"):
            val = getattr(state, attr, None)
            if val and not Path(val).exists():
                return True
        return False

    def save(self, state: DatasetState) -> None:
        path = self._state_path(state.dataset_id)
        with path.open("w", encoding="utf-8") as f:
            json.dump(state.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)

    def load_all(self, dataset_ids: List[str]) -> Dict[str, DatasetState]:
        return {did: self.load(did) for did in dataset_ids}

    def _default_state(self, dataset_id: str) -> DatasetState:
        return DatasetState(dataset_id=dataset_id)

    def init_from_definition(self, defn: DatasetDefinition) -> DatasetState:
        """
        定義に基づいて現在状態を返す。

        状態ファイルが存在しない場合はファイルシステムをスキャンして
        既存データを自動検出し、状態を推定して保存する。
        既存の状態ファイルがあればそれをそのまま使う。
        """
        state_path = self._state_path(defn.dataset_id)
        if not state_path.exists():
            state = self._infer_state_from_filesystem(defn)
            self.save(state)
        else:
            state = self.load(defn.dataset_id)

        # not_required フラグを常に定義から上書き（定義変更に追従）
        if not defn.requires_normalize and state.normalize_status == NormalizeStatus.not_started:
            state.normalize_status = NormalizeStatus.not_required
        if not defn.requires_validation and state.validation_status == ValidationStatus.not_started:
            state.validation_status = ValidationStatus.not_required
        if not defn.requires_osrm_rebuild:
            state.osrm_rebuild_status = OsrmRebuildStatus.not_applicable

        return state

    def _infer_state_from_filesystem(self, defn: DatasetDefinition) -> DatasetState:
        """
        状態ファイルが存在しない初回起動時に、
        data_lake のディレクトリ構造から状態を推定する。

        優先順位: validated > normalized > raw
        OSRM は .osrm ファイルの有無で判定する。
        """
        state = DatasetState(dataset_id=defn.dataset_id)

        # not_required を初期設定
        if not defn.requires_normalize:
            state.normalize_status = NormalizeStatus.not_required
        if not defn.requires_validation:
            state.validation_status = ValidationStatus.not_required
        if not defn.requires_osrm_rebuild:
            state.osrm_rebuild_status = OsrmRebuildStatus.not_applicable

        # validated ディレクトリをスキャン
        validated_file = self._find_representative_file(
            defn.validated_storage_path, defn
        ) if defn.validated_storage_path else None

        # normalized ディレクトリをスキャン
        # normalized_storage_path が null の場合でも raw パスから派生パスを試みる
        normalized_path = defn.normalized_storage_path
        if not normalized_path and defn.raw_storage_path:
            normalized_path = defn.raw_storage_path.replace("/raw/", "/normalized/")
        normalized_file = self._find_representative_file(normalized_path, defn) if normalized_path else None

        # raw ディレクトリをスキャン
        raw_file = self._find_representative_file(defn.raw_storage_path, defn)

        # 状態を推定
        if validated_file and validated_file.exists():
            state.storage_status = StorageStatus.stored
            state.current_file_name = validated_file.name
            state.current_file_size = validated_file.stat().st_size
            state.current_validated_path = str(validated_file)
            state.current_raw_path = str(raw_file) if raw_file and raw_file.exists() else None
            if defn.requires_normalize:
                state.normalize_status = NormalizeStatus.success
                if normalized_file and normalized_file.exists():
                    state.current_normalized_path = str(normalized_file)
            if defn.requires_validation:
                state.validation_status = ValidationStatus.passed
            # deploy_status は runtime の有無で判定
            runtime_path = (_PROJECT_ROOT / defn.runtime_path).resolve()
            if defn.deploy_mode == "copy_file":
                # copy_file モード: 同じ runtime_path を複数データセットが共有する場合があるため
                # ディレクトリ存在だけでは deployed と判定しない。
                # validated ファイルと同名のファイルが runtime 内にあれば deployed とみなす。
                if validated_file and runtime_path.exists():
                    deployed_file = runtime_path / validated_file.name
                    if deployed_file.exists():
                        state.deploy_status = DeployStatus.deployed
                        state.current_runtime_path = str(deployed_file)
                    else:
                        state.deploy_status = DeployStatus.deployable
                else:
                    state.deploy_status = DeployStatus.deployable
            elif runtime_path.exists() and any(runtime_path.iterdir()):
                state.deploy_status = DeployStatus.deployed
                state.current_runtime_path = str(runtime_path)
            else:
                state.deploy_status = DeployStatus.deployable
            state.updated_at = datetime.utcfromtimestamp(validated_file.stat().st_mtime)

        elif normalized_file and normalized_file.exists():
            state.storage_status = StorageStatus.stored
            state.current_file_name = normalized_file.name
            state.current_file_size = normalized_file.stat().st_size
            state.current_normalized_path = str(normalized_file)
            state.current_raw_path = str(raw_file) if raw_file and raw_file.exists() else None
            if defn.requires_normalize:
                state.normalize_status = NormalizeStatus.success
            if defn.requires_validation:
                state.validation_status = ValidationStatus.not_started
            state.updated_at = datetime.utcfromtimestamp(normalized_file.stat().st_mtime)

        elif raw_file and raw_file.exists():
            state.storage_status = StorageStatus.stored
            state.current_file_name = raw_file.name
            state.current_file_size = raw_file.stat().st_size
            state.current_raw_path = str(raw_file)
            if defn.requires_normalize:
                state.normalize_status = NormalizeStatus.not_started
            state.updated_at = datetime.utcfromtimestamp(raw_file.stat().st_mtime)

        # OSRM: .osrm ファイルが存在すれば構築済みとみなす
        if defn.requires_osrm_rebuild:
            osrm_driving = _PROJECT_ROOT / "data_lake" / "validated" / "tokyo" / "osm" / "driving"
            if (osrm_driving / "kanto-260214.osrm").exists():
                state.osrm_rebuild_status = OsrmRebuildStatus.success
            else:
                state.osrm_rebuild_status = OsrmRebuildStatus.not_started

        return state

    def _find_representative_file(
        self, storage_path: Optional[str], defn: DatasetDefinition
    ) -> Optional[Path]:
        """
        指定ディレクトリから代表ファイルを1件返す。
        .DS_Store など隠しファイルは除外。
        """
        if not storage_path:
            return None
        dir_path = (_PROJECT_ROOT / storage_path).resolve()
        if not dir_path.exists():
            return None

        # 対応拡張子のファイルを優先探索
        preferred_exts = set(defn.accepted_extensions)
        # 変換後の中間ファイルは .geojson / .tif も対象
        all_exts = preferred_exts | {".geojson", ".tif", ".tiff", ".pbf"}

        candidates = [
            p for p in sorted(dir_path.iterdir())
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in all_exts
        ]
        if candidates:
            # 最終更新日時が新しいものを優先
            return max(candidates, key=lambda p: p.stat().st_mtime)

        # 拡張子不問でファイルがあれば返す
        all_files = [p for p in dir_path.iterdir() if p.is_file() and not p.name.startswith(".")]
        return max(all_files, key=lambda p: p.stat().st_mtime) if all_files else None

    # ── deployable 判定 ───────────────────────────────────────────────────────

    def update_deployable(self, state: DatasetState, defn: DatasetDefinition) -> None:
        """
        deploy 可能条件をすべて満たすか評価し、state.is_deployable を更新する。
        条件:
          - storage_status == stored
          - requires_normalize → normalize_status == success
          - requires_validation → validation_status == pass
          - deploy_status != deploying
        """
        ok = state.storage_status == StorageStatus.stored
        if defn.requires_normalize:
            ok = ok and state.normalize_status == NormalizeStatus.success
        if defn.requires_validation:
            ok = ok and state.validation_status == ValidationStatus.passed
        ok = ok and state.deploy_status != DeployStatus.deploying
        state.is_deployable = ok

        if ok and state.deploy_status == DeployStatus.not_deployed:
            state.deploy_status = DeployStatus.deployable

    # ── 履歴 ──────────────────────────────────────────────────────────────────

    def _history_path(self, dataset_id: str) -> Path:
        return self._history_dir / f"{dataset_id}.jsonl"

    def append_history(self, history: DatasetHistory) -> None:
        path = self._history_path(history.dataset_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(history.model_dump(mode="json"), ensure_ascii=False, default=str) + "\n")

    def load_history(self, dataset_id: str, limit: int = 50) -> List[DatasetHistory]:
        path = self._history_path(dataset_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        # 末尾 limit 件を返す
        recent = lines[-limit:]
        records = []
        for line in reversed(recent):
            try:
                records.append(DatasetHistory(**json.loads(line)))
            except Exception as exc:
                logger.warning("Failed to parse history line: %s", exc)
        return records


# シングルトン
_instance: Optional[DatasetStateService] = None


def get_state_service() -> DatasetStateService:
    global _instance
    if _instance is None:
        _instance = DatasetStateService()
    return _instance
