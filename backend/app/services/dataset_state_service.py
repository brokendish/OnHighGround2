"""
dataset_state_service.py — データセット状態の永続管理サービス

状態ファイルは data_lake/admin/state/{dataset_id}.json に保存する。
履歴は data_lake/admin/history/{dataset_id}.jsonl に追記する。
"""
from __future__ import annotations

import json
import os
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
from app.services.admin_metadata_fs import chmod_quiet
from app.services.admin_atomic_publish import (
    ATOMIC_PUBLISH_LAYER_TYPES,
    data_runtime_root,
    find_artifact_in_current,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

PATH_PRESENT = "present"
PATH_MISSING = "missing"
PATH_UNOBSERVABLE = "unobservable"
# data_lake/admin の root。テストは OHG2_ADMIN_DIR で tmp に隔離する（tests/admin_isolation.py）。
# 未設定時は従来どおり <project>/data_lake/admin（本番 container では /data_lake/admin）。
_ADMIN_DIR = Path(os.environ.get("OHG2_ADMIN_DIR") or (_PROJECT_ROOT / "data_lake" / "admin"))
_ADMIN_STATE_DIR = _ADMIN_DIR / "state"
_ADMIN_HISTORY_DIR = _ADMIN_DIR / "history"

_MAX_HISTORY_LINES = 200
_OSRM_REQUIRED_SUFFIXES = (
    ".osrm",
    ".osrm.partition",
    ".osrm.mldgr",
    ".osrm.cells",
    ".osrm.fileIndex",
    ".osrm.ramIndex",
)
# 後方互換用のデフォルト OSRM パス（routing_profile 未設定の dataset 向け）
_OSRM_DRIVING_DIR = _PROJECT_ROOT / "data_lake" / "validated" / "tokyo" / "osm" / "driving"
_OSRM_WALKING_DIR = _PROJECT_ROOT / "data_lake" / "validated" / "tokyo" / "osm" / "walking" / "tokyo-kanagawa"
_OSRM_DRIVING_STEM = "kanto-260214"
_OSRM_WALKING_STEM = "tokyo-kanagawa-260214"


class DatasetStateService:
    """データセット状態を JSON ファイルで永続管理する。"""

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        history_dir: Optional[Path] = None,
    ) -> None:
        self._state_dir = (state_dir or _ADMIN_STATE_DIR).resolve()
        self._history_dir = (history_dir or _ADMIN_HISTORY_DIR).resolve()
        # 本serviceはimport chain経由でプロセス起動時に即時instantiateされる
        # （shelter_service.py._resolve_paths() -> get_state_service()）。
        # 実運用では`data_lake`は常にbind mountされ配下directoryの作成は
        # 問題なく成功するが、`data_lake`自体が存在しない・書込不可な環境
        # （volumeを持たない隔離image smoke test等）ではmkdir失敗がimport
        # chain全体をcrashさせてしまうため、失敗時は警告のみで起動を継続する。
        for d in (self._state_dir, self._history_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("Failed to create dataset state directory %s: %s", d, exc)

    # ── state CRUD ────────────────────────────────────────────────────────────

    def _state_path(self, dataset_id: str) -> Path:
        return self._state_dir / f"{dataset_id}.json"

    def load(self, dataset_id: str) -> DatasetState:
        """state file を読むだけ。削除・再推定・保存はしない（読み込みは非破壊）。

        STATE-DESTRUCTIVE-LOAD 修正: 旧実装は記録 path が現在の process から見えないと
        「別マシンの stale」として state file を削除し再推定していた。host（/Users/...）と
        container（/data_lake, /data_runtime）の namespace 差異だけで operator の state が
        消える実害があった（2026-10-07）。path の可視性は path_status() で報告し、
        runtime 側の正否は dataset_runtime_reconcile に委ねる。"""
        path = self._state_path(dataset_id)
        if not path.exists():
            return self._default_state(dataset_id)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        state = DatasetState(**data)
        report = self.path_status(state)
        if any(v != PATH_PRESENT for v in report.values()):
            logger.info("state %s: recorded paths not all visible from this process (kept as-is): %s",
                        dataset_id, {k: v for k, v in report.items() if v != PATH_PRESENT})
        return state

    @staticmethod
    def path_visibility(path_str: Optional[str]) -> Optional[str]:
        """記録 path の可視性。present / missing / unobservable（namespace 外・権限なし）。

        path の最上位 2 要素（例: /data_runtime, /data_lake, /Users）が この process に存在しない
        場合は「別 namespace の path」であり、存在しないとは断定できない（unobservable）。"""
        if not path_str:
            return None
        p = Path(path_str)
        if p.is_absolute() and len(p.parts) >= 2:
            anchor = Path(p.parts[0]) / p.parts[1]
            try:
                if not anchor.exists():
                    return PATH_UNOBSERVABLE
            except PermissionError:
                return PATH_UNOBSERVABLE
        try:
            return PATH_PRESENT if p.exists() else PATH_MISSING
        except PermissionError:
            return PATH_UNOBSERVABLE

    @staticmethod
    def _outside_namespace(path_str: Optional[str]) -> bool:
        """記録 path の最上位 2 要素がこの process に存在しない（別 namespace の path）。"""
        if not path_str:
            return False
        p = Path(path_str)
        if not p.is_absolute() or len(p.parts) < 2:
            return False
        try:
            return not (Path(p.parts[0]) / p.parts[1]).exists()
        except PermissionError:
            return True

    def path_status(self, state: DatasetState) -> Dict[str, Optional[str]]:
        return {attr: self.path_visibility(getattr(state, attr, None))
                for attr in ("current_raw_path", "current_normalized_path",
                             "current_validated_path", "current_runtime_path")
                if getattr(state, attr, None)}

    @staticmethod
    def _exists_or_inaccessible(path: Path) -> bool:
        """存在すれば True。このプロセスから stat できない（PermissionError）場合も、
        「存在しない」とは断定できないため True（stale として state を破棄しない）。
        例: backend-public（gid 20001）は operator 専用 dir（10002:10002 0770）を traverse できない。"""
        try:
            return path.exists()
        except PermissionError:
            return True

    def save(self, state: DatasetState) -> None:
        path = self._state_path(state.dataset_id)
        with path.open("w", encoding="utf-8") as f:
            json.dump(state.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)
        chmod_quiet(path)

    def load_all(self, dataset_ids: List[str]) -> Dict[str, DatasetState]:
        return {did: self.load(did) for did in dataset_ids}

    def _default_state(self, dataset_id: str) -> DatasetState:
        return DatasetState(dataset_id=dataset_id)

    def _osrm_dataset_is_ready(self, mode_dir: Path, stem: str) -> bool:
        return all((mode_dir / f"{stem}{suffix}").exists() for suffix in _OSRM_REQUIRED_SUFFIXES)

    def _check_osrm_ready(self, defn: DatasetDefinition) -> bool:
        """
        dataset 定義の routing_profile と osrm_dir / osrm_stem を使い、
        そのプロファイル専用の成果物が揃っているか確認する。

        routing_profile が設定されている場合はそのプロファイルのみを確認する。
        未設定（後方互換）の場合は driving + walking 両方を確認する。
        """
        if defn.routing_profile and defn.osrm_dir and defn.osrm_stem:
            # プロファイル別チェック（新方式）
            osrm_dir = _PROJECT_ROOT / defn.osrm_dir
            return self._osrm_dataset_is_ready(osrm_dir, defn.osrm_stem)
        else:
            # 後方互換: driving + walking の両方が揃っていれば ready（旧 TOKYO-ROAD-001 向け）
            return (
                self._osrm_dataset_is_ready(_OSRM_DRIVING_DIR, _OSRM_DRIVING_STEM)
                and self._osrm_dataset_is_ready(_OSRM_WALKING_DIR, _OSRM_WALKING_STEM)
            )

    def init_from_definition(self, defn: DatasetDefinition) -> DatasetState:
        """
        定義に基づいて現在状態を返す。

        状態ファイルが存在しない場合はファイルシステムをスキャンして
        既存データを自動検出し、状態を推定して保存する。
        既存の状態ファイルは、definitionのruntime_pathと矛盾しない
        （stale状態でない）限りそのまま使う。
        """
        state_path = self._state_path(defn.dataset_id)
        if not state_path.exists():
            state = self._infer_state_from_filesystem(defn)
            # このsaveはfilesystem scan結果を次回起動のためにcache する
            # best-effort最適化であり、成功はrequirementではない
            # （呼び出し元はいずれにせよ推定済みのstateをそのまま使う）。
            # import chain経由でプロセス起動時に即時実行されるため、
            # data_lakeがread-only mountの環境（隔離test container等）で
            # crashさせない。明示的なユーザー操作によるsave()（他の
            # 呼び出し元）はこのtry/exceptの対象外で、従来どおり例外を
            # 呼び出し元へ伝播する。
            try:
                self.save(state)
            except OSError as exc:
                logger.warning("Failed to cache inferred state for %s: %s", defn.dataset_id, exc)
        else:
            state = self.load(defn.dataset_id)
            # Residual Finding Remediation 02 (DATASET-STATE-INVALIDATION):
            # dataset_definitions.jsonのruntime_pathを修正しても、永続化された
            # state.current_runtime_pathが無条件で採用され続け、definition側の
            # 変更がruntimeへ反映されない欠陥があった。deploy_status=deployedな
            # stateについてのみ、persisted current_runtime_pathが現在のdefinition
            # のruntime_path配下の実在artifactかを確認し、そうでなければstale
            # stateとしてfilesystemから再解決する。既存の正常なstate（definition
            # と矛盾しない大多数）はこの分岐に入らず従来どおり即座にloadされる
            # ため、高速load/checkpoint semanticsは維持される。
            #
            # STATE-DESTRUCTIVE-LOAD 修正: 記録 path が この process の namespace 外（host から見た
            # /data_runtime、container から見た /Users 等）の場合は判定不能であり、state を作り直さない。
            # atomic publish 対象で versions 内 artifact が見えないだけの場合も作り直さず、
            # dataset_runtime_reconcile（current + manifest）に判定を委ねる。
            if (
                state.deploy_status == DeployStatus.deployed
                and not self._outside_namespace(state.current_runtime_path)
                and not self._defer_to_runtime_reconcile(state, defn)
                and not self._is_current_runtime_path_valid(state, defn)
            ):
                logger.warning(
                    "stale dataset state detected for %s: persisted current_runtime_path=%s "
                    "does not match definition runtime_path=%s (or artifact missing) — "
                    "re-inferring from filesystem",
                    defn.dataset_id, state.current_runtime_path, defn.runtime_path,
                )
                state = self._infer_state_from_filesystem(defn)
                try:
                    self.save(state)
                except OSError as exc:
                    logger.warning("Failed to persist re-inferred state for %s: %s", defn.dataset_id, exc)

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
        OSRM は MLD 実行に必要な主要ファイル群の有無で判定する。
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

        if defn.source_type == "railway_pmtiles":
            runtime_path = (_PROJECT_ROOT / defn.runtime_path).resolve()
            pmtiles_file = runtime_path / "railways_japan.pmtiles"
            if pmtiles_file.exists():
                state.storage_status = StorageStatus.stored
                state.current_file_name = pmtiles_file.name
                state.current_file_size = pmtiles_file.stat().st_size
                state.current_runtime_path = str(pmtiles_file)
                state.current_raw_path = str(raw_file) if raw_file and raw_file.exists() else None
                state.normalize_status = NormalizeStatus.not_required
                state.validation_status = ValidationStatus.not_required
                state.deploy_status = DeployStatus.deployed
                state.updated_at = datetime.utcfromtimestamp(pmtiles_file.stat().st_mtime)
                state.deployed_at = datetime.utcfromtimestamp(pmtiles_file.stat().st_mtime)
                return state

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
            if defn.layer_type in ATOMIC_PUBLISH_LAYER_TYPES:
                # 管理画面反映が atomic publish の dataset は、flat path ではなく
                # current version に当該 artifact があるかで判定する（表示と実 runtime の乖離防止）。
                published = find_artifact_in_current(defn.layer_type, defn.region, validated_file.name)
                if published is not None:
                    state.deploy_status = DeployStatus.deployed
                    state.current_runtime_path = str(published)
                else:
                    state.deploy_status = DeployStatus.deployable
            elif defn.deploy_mode == "copy_file":
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

        # OSRM: プロファイル別に成果物の有無を確認して構築済み判定する
        if defn.requires_osrm_rebuild:
            osrm_ready = self._check_osrm_ready(defn)
            state.osrm_rebuild_status = (
                OsrmRebuildStatus.success if osrm_ready else OsrmRebuildStatus.not_started
            )

        return state

    @staticmethod
    def _defer_to_runtime_reconcile(state: DatasetState, defn: DatasetDefinition) -> bool:
        """atomic publish 対象で記録 path が versions 配下（契約どおり）なら、artifact の有無は
        reconcile が current + manifest から判定する（ここでは作り直さない）。"""
        if defn.layer_type not in ATOMIC_PUBLISH_LAYER_TYPES or not state.current_runtime_path:
            return False
        try:
            versions_dir = (data_runtime_root() / "versions").resolve()
            return versions_dir in Path(state.current_runtime_path).resolve().parents
        except (OSError, ValueError):
            return False

    def _is_current_runtime_path_valid(self, state: DatasetState, defn: DatasetDefinition) -> bool:
        """
        永続化されたstate.current_runtime_pathが、現在のdefinition.runtime_path
        契約と矛盾しない実在artifactかを判定する（DATASET-STATE-INVALIDATION対策）。

        判定基準（文字列prefix比較ではなくPathとして正規化して比較する）:
          1. current_runtime_pathがdefinition.runtime_path配下（またはそれ自身）であること
          2. 実際にfilesystem上に存在すること
        いずれかを満たさなければstale stateとして扱う。
        """
        if not state.current_runtime_path:
            return False
        if defn.layer_type in ATOMIC_PUBLISH_LAYER_TYPES:
            # atomic publish 管理の dataset は、activate された version 内の artifact を指す場合のみ有効。
            # 旧来の flat copy による deployed（backend-public は読まない）は stale として再推定する。
            try:
                actual = Path(state.current_runtime_path).resolve()
            except (OSError, ValueError):
                return False
            versions_dir = (data_runtime_root() / "versions").resolve()
            return versions_dir in actual.parents and actual.exists()
        expected_dir = (_PROJECT_ROOT / defn.runtime_path).resolve()
        try:
            actual_path = Path(state.current_runtime_path).resolve()
        except (OSError, ValueError):
            return False
        if actual_path != expected_dir and expected_dir not in actual_path.parents:
            return False
        return self._exists_or_inaccessible(actual_path)

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
        chmod_quiet(path)

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
