"""
dataset_runtime_reconcile.py — 実 runtime（current + manifest + artifact）を正として DatasetState を同期する。

正の優先順位:
  1. data_runtime/current（symlink → versions/<id>）
  2. current の _manifest.json（version 内全 file の sha256 を記録済み。artifact を再ハッシュしない）
  3. version 内の実 artifact
  4. artifact の sha256（manifest 記録値）と反映元（validated / derived）の sha256
  5. DatasetState（runtime の事実を UI へ出すためのキャッシュ・管理情報）

CLI（deploy_to_runtime_atomic.sh）で publish すると DatasetState は更新されない。本モジュールは
current を読み、dataset ごとの runtime_status を判定して、必要な範囲だけ DatasetState を補正する。

runtime_status:
  published            current に期待 artifact があり、反映元と sha256 が一致
  not_published        登録 dataset だが current に artifact が無い
  stale                DatasetState は deployed だが current に artifact が無い
  mismatch             artifact はあるが反映元（validated / derived）と sha256 が異なる
  unsupported          管理画面 publish 非対応（tsunami）。runtime 存在だけは判定する
  legacy               atomic publish 管理外の dataset（OSM / tide / shelter 等）
  unknown              判定不能（current / manifest 欠落・破損、反映元未確定、hash 未計算）
  unregistered_runtime current に artifact があるが registry 上のどの dataset にも対応しない
                       （unregistered_runtime_artifacts として列挙）

性能: artifact の sha256 は manifest 記録値を使う。反映元の sha256 は (path, size, mtime_ns) を
キーに永続キャッシュし、`allow_hash=False`（一覧 API 等）ではキャッシュに無ければ計算せず unknown。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.admin_dataset import DatasetDefinition, DatasetState, DeployStatus, NormalizeStatus, \
    StorageStatus, ValidationStatus
from app.services import admin_atomic_publish as aap
from app.services.flood_routing_contract import (
    FloodRoutingContractError,
    load_meta,
    routing_paths_for_canonical,
    sha256_file,
)

logger = logging.getLogger(__name__)

PUBLISHED = "published"
NOT_PUBLISHED = "not_published"
STALE = "stale"
MISMATCH = "mismatch"
UNSUPPORTED = "unsupported"
LEGACY = "legacy"
UNKNOWN = "unknown"
UNREGISTERED_RUNTIME = "unregistered_runtime"

HAZARD_RUNTIME_TYPES = aap.ATOMIC_PUBLISH_LAYER_TYPES | aap.ATOMIC_PUBLISH_UNSUPPORTED_LAYER_TYPES


# ── current / manifest ──────────────────────────────────────────────────────────

@dataclass
class RuntimeView:
    root: Path
    version_id: Optional[str] = None
    files: Dict[str, str] = field(default_factory=dict)  # rel path → sha256（manifest 記録値）
    published_at: Optional[datetime] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.version_id is not None

    def version_path(self, rel: str) -> Path:
        return self.root / "versions" / str(self.version_id) / rel


_view_lock = threading.Lock()
_view_cache: Dict[str, Any] = {}


def load_runtime_view(root: Optional[Path] = None) -> RuntimeView:
    """current と manifest を読む。(version_id, manifest mtime_ns) 単位でキャッシュする。
    current / manifest が無い・壊れている場合は error を設定して返す（呼び出し側は unknown 扱い）。"""
    root = Path(root or aap.data_runtime_root())
    try:
        version_id = aap.current_version_id(root)
    except OSError as exc:
        return RuntimeView(root=root, error=f"current を解決できません: {exc}")
    if version_id is None:
        return RuntimeView(root=root, error="current が未設定です")
    manifest_path = root / "versions" / version_id / "_manifest.json"
    try:
        st = manifest_path.stat()
    except OSError as exc:
        return RuntimeView(root=root, version_id=version_id, error=f"manifest がありません: {exc}")
    key = (str(root), version_id, st.st_mtime_ns, st.st_size)
    with _view_lock:
        cached = _view_cache.get("view")
        if cached and cached[0] == key:
            return cached[1]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict) or not all(isinstance(v, str) for v in files.values()):
            raise ValueError("files が rel→sha256 の object ではありません")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return RuntimeView(root=root, version_id=version_id, error=f"manifest を読めません: {exc}")
    view = RuntimeView(
        root=root, version_id=version_id, files=dict(files),
        published_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).replace(tzinfo=None),
    )
    with _view_lock:
        _view_cache["view"] = (key, view)
    return view


# ── 反映元 sha256 キャッシュ ────────────────────────────────────────────────────

class SourceShaCache:
    """(path, size, mtime_ns) → sha256 の永続キャッシュ。大容量 file を表示のたびにハッシュしない。"""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        if self._path and self._path.is_file():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {}

    def get(self, path: Path, allow_hash: bool) -> Optional[str]:
        try:
            st = Path(path).stat()
        except OSError:
            return None
        key = str(path)
        with self._lock:
            rec = self._data.get(key)
            if rec and rec.get("size") == st.st_size and rec.get("mtime_ns") == st.st_mtime_ns:
                return rec.get("sha256")
        if not allow_hash:
            return None
        digest = sha256_file(path)
        with self._lock:
            self._data[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
            self._save()
        return digest

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(f".{self._path.name}.tmp-{os.getpid()}")
            tmp.write_text(json.dumps(self._data, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("source sha cache を保存できません: %s", exc)


_default_cache: Optional[SourceShaCache] = None


def get_source_sha_cache() -> SourceShaCache:
    global _default_cache
    if _default_cache is None:
        from app.services.dataset_state_service import _ADMIN_STATE_DIR
        _default_cache = SourceShaCache(Path(_ADMIN_STATE_DIR).parent / "cache" / "source_sha256.json")
    return _default_cache


# ── dataset ↔ runtime artifact ────────────────────────────────────────────────

def _validated_path(defn: DatasetDefinition, state: DatasetState) -> Optional[Path]:
    if state.current_validated_path and Path(state.current_validated_path).is_file():
        return Path(state.current_validated_path)
    return None


def expected_runtime_rel(defn: DatasetDefinition, state: DatasetState) -> Optional[str]:
    """current version 内で当該 dataset に対応する artifact の rel path。対応規約が無ければ None。"""
    if defn.layer_type == "tsunami":
        # runtime 契約: backend/hazard/tsunami/tsunami_<target>.geojson（flat・固定名）
        return f"backend/hazard/tsunami/tsunami_{defn.region}.geojson"
    if defn.layer_type not in aap.ATOMIC_PUBLISH_LAYER_TYPES:
        return None
    validated = _validated_path(defn, state)
    name = validated.name if validated else f"{defn.dataset_id.lower()}.geojson"
    return f"backend/hazard/{defn.layer_type}/{defn.region}/{aap.runtime_artifact_name(defn.layer_type, name)}"


def _source_sha(defn: DatasetDefinition, state: DatasetState, cache: SourceShaCache,
                allow_hash: bool) -> "tuple[Optional[str], Dict[str, Any]]":
    """反映元（flood は derived routing、他は validated）の sha256 と provenance 断片。"""
    validated = _validated_path(defn, state)
    prov: Dict[str, Any] = {"canonical_path": str(validated) if validated else None, "derived_path": None}
    if validated is None:
        return None, prov
    if defn.layer_type == "flood":
        try:
            routing, meta_path = routing_paths_for_canonical(validated)
            meta = load_meta(meta_path)
        except FloodRoutingContractError:
            return None, prov
        prov["derived_path"] = str(routing)
        canonical_sha = cache.get(validated, allow_hash)
        if canonical_sha is None:
            return None, prov
        if canonical_sha != meta["source_canonical_sha256"]:
            # canonical が更新され routing が未再生成: runtime がどうであれ反映元と一致しない
            return f"stale-derived:{canonical_sha}", prov
        return meta["routing_artifact_sha256"], prov
    return cache.get(validated, allow_hash), prov


@dataclass
class ReconcileResult:
    dataset_id: str
    layer_type: Optional[str]
    region: str
    publish_mode: str
    runtime_status: str
    current_version: Optional[str]
    artifact_present: bool = False
    runtime_rel: Optional[str] = None
    runtime_path: Optional[str] = None
    runtime_sha256: Optional[str] = None
    source_sha256: Optional[str] = None
    matches_source: Optional[bool] = None
    reason: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _provenance(defn: DatasetDefinition, prov: Dict[str, Any], runtime_path: Optional[str],
                state: DatasetState) -> Dict[str, Any]:
    """整合性ダッシュボード向け。存在しない情報は推測せず空 / None のままにする。"""
    return {
        "source_files": [],
        "source_url": defn.source_url,
        "acquisition_date": None,
        "source_sha256": None,
        "canonical_path": prov.get("canonical_path"),
        "derived_path": prov.get("derived_path"),
        "runtime_path": runtime_path,
        "tile_path": state.current_tile_path,
    }


def reconcile_dataset(defn: DatasetDefinition, state: DatasetState, view: RuntimeView,
                      cache: Optional[SourceShaCache] = None, allow_hash: bool = True) -> ReconcileResult:
    cache = cache or get_source_sha_cache()
    if defn.layer_type in aap.ATOMIC_PUBLISH_UNSUPPORTED_LAYER_TYPES:
        mode = "unsupported"
    elif defn.layer_type in aap.ATOMIC_PUBLISH_LAYER_TYPES:
        mode = "atomic"
    else:
        mode = "legacy"
    res = ReconcileResult(dataset_id=defn.dataset_id, layer_type=defn.layer_type, region=defn.region,
                          publish_mode=mode, runtime_status=UNKNOWN, current_version=view.version_id)
    if mode == "legacy":
        res.runtime_status = LEGACY
        res.provenance = _provenance(defn, {}, state.current_runtime_path, state)
        return res
    if not view.ok:
        res.reason = view.error
        res.provenance = _provenance(defn, {}, None, state)
        return res

    rel = expected_runtime_rel(defn, state)
    res.runtime_rel = rel
    runtime_sha = view.files.get(rel) if rel else None
    res.artifact_present = runtime_sha is not None
    if res.artifact_present:
        res.runtime_path = str(view.version_path(rel))
        res.runtime_sha256 = runtime_sha
    source_sha, prov = _source_sha(defn, state, cache, allow_hash) if mode == "atomic" else (None, {})
    res.provenance = _provenance(defn, prov, res.runtime_path, state)

    if mode == "unsupported":
        res.runtime_status = UNSUPPORTED  # runtime 存在（artifact_present）だけ報告する
        return res
    if not res.artifact_present:
        res.runtime_status = STALE if state.deploy_status == DeployStatus.deployed else NOT_PUBLISHED
        return res
    if source_sha is None:
        res.reason = "反映元の sha256 が未確定（validated 不在、または hash 未計算）"
        return res
    res.source_sha256 = source_sha
    res.matches_source = source_sha == runtime_sha
    res.runtime_status = PUBLISHED if res.matches_source else MISMATCH
    return res


# ── DatasetState 更新 ───────────────────────────────────────────────────────────

def _pipeline_ready(defn: DatasetDefinition, state: DatasetState) -> bool:
    ok = state.storage_status == StorageStatus.stored
    if defn.requires_normalize:
        ok = ok and state.normalize_status == NormalizeStatus.success
    if defn.requires_validation:
        ok = ok and state.validation_status == ValidationStatus.passed
    return ok


def apply_to_state(defn: DatasetDefinition, state: DatasetState, res: ReconcileResult,
                   view: RuntimeView) -> bool:
    """runtime の事実を DatasetState へ反映する。変更したら True。

    更新するのは deploy_status / current_runtime_path / deployed_at / is_deployable だけ。
    last_job_id / backup_path / validated 等の管理情報は変更しない。
    判定不能（unknown）・管理画面非対応（unsupported）・legacy・反映中（deploying）は変更しない。
    """
    if res.runtime_status not in (PUBLISHED, MISMATCH, NOT_PUBLISHED, STALE):
        return False
    if state.deploy_status == DeployStatus.deploying:
        return False
    before = (state.deploy_status, state.current_runtime_path, state.deployed_at, state.is_deployable)
    ready = _pipeline_ready(defn, state)
    if res.runtime_status == PUBLISHED:
        if state.deploy_status != DeployStatus.deployed or state.current_runtime_path != res.runtime_path:
            state.deployed_at = view.published_at or state.deployed_at
        state.deploy_status = DeployStatus.deployed
        state.current_runtime_path = res.runtime_path
        state.is_deployable = False
    elif res.runtime_status == MISMATCH:
        # 実行中の artifact は current にあるが反映元と異なる（再取り込み後・未反映、または差し替え）
        state.current_runtime_path = res.runtime_path
        state.deploy_status = DeployStatus.deployable if ready else DeployStatus.not_deployed
        state.is_deployable = ready
    else:  # NOT_PUBLISHED / STALE
        state.current_runtime_path = None
        if state.deploy_status in (DeployStatus.deployed, DeployStatus.deployable) or ready:
            state.deploy_status = DeployStatus.deployable if ready else DeployStatus.not_deployed
        state.is_deployable = ready
    return before != (state.deploy_status, state.current_runtime_path, state.deployed_at, state.is_deployable)


# ── 一括 / 単体 ──────────────────────────────────────────────────────────────────

def unregistered_runtime_artifacts(view: RuntimeView, expected_rels: "set[str]") -> List[Dict[str, Any]]:
    """current の backend/hazard 配下で、registry 上のどの dataset の期待 artifact にも当たらない file。
    削除はしない（後続の整合性ダッシュボード用の情報）。"""
    out = []
    if not view.ok:
        return out
    for rel, sha in sorted(view.files.items()):
        parts = rel.split("/")
        if len(parts) < 4 or parts[0] != "backend" or parts[1] != "hazard":
            continue
        if parts[2] not in HAZARD_RUNTIME_TYPES or rel in expected_rels:
            continue
        out.append({
            "hazard_type": parts[2],
            "region": parts[3] if len(parts) >= 5 else None,
            "rel_path": rel,
            "path": str(view.version_path(rel)),
            "sha256": sha,
            "runtime_status": UNREGISTERED_RUNTIME,
        })
    return out


def _same_as_persisted(ss, state: DatasetState) -> bool:
    load = getattr(ss, "load", None)
    if not callable(load):
        return False
    try:
        persisted = load(state.dataset_id)
        return isinstance(persisted, DatasetState) and persisted.model_dump() == state.model_dump()
    except Exception:  # noqa: BLE001 — 比較できなければ従来どおり保存する
        return False


def reconcile_one(defn: DatasetDefinition, state: DatasetState, ss=None, *, allow_hash: bool = True,
                  persist: bool = True, view: Optional[RuntimeView] = None,
                  cache: Optional[SourceShaCache] = None) -> ReconcileResult:
    view = view or load_runtime_view()
    res = reconcile_dataset(defn, state, view, cache, allow_hash)
    if apply_to_state(defn, state, res, view) and persist and ss is not None:
        # 呼び出し側が保存前に in-memory で変更した値（例: 一覧 API の update_deployable が
        # is_deployable=True にした後、reconcile が published として False に戻す）を「変更」と
        # 誤認して 5 秒周期の一覧ポーリングのたびに同一内容を書き直さないよう、永続値と比較する。
        if _same_as_persisted(ss, state):
            return res
        try:
            ss.save(state)
        except OSError as exc:
            logger.warning("DatasetState を保存できません（runtime は変更していません）: %s: %s", defn.dataset_id, exc)
    return res


def reconcile_all(ds=None, ss=None, *, allow_hash: bool = True, persist: bool = True,
                  root: Optional[Path] = None) -> Dict[str, Any]:
    """全 dataset を current と照合し、必要なら DatasetState を補正する。
    個別 dataset の失敗は記録して続行する（publish の成否には影響させない）。"""
    if ds is None:
        from app.services.dataset_definition_service import get_definition_service
        ds = get_definition_service()
    if ss is None:
        from app.services.dataset_state_service import get_state_service
        ss = get_state_service()
    view = load_runtime_view(root)
    results, errors, expected = [], [], set()
    for defn in ds.list_all():
        try:
            state = ss.init_from_definition(defn)
            res = reconcile_one(defn, state, ss, allow_hash=allow_hash, persist=persist, view=view)
            if res.runtime_rel:
                expected.add(res.runtime_rel)
            results.append(res.as_dict())
        except Exception as exc:  # 1 dataset の失敗で全体を止めない
            logger.warning("reconcile failed: %s: %s", defn.dataset_id, exc)
            errors.append({"dataset_id": defn.dataset_id, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "current_version": view.version_id,
        "runtime_error": view.error,
        "results": results,
        "errors": errors,
        "unregistered_runtime_artifacts": unregistered_runtime_artifacts(view, expected),
    }
