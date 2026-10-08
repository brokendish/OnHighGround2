"""
data_ops_service.py — Data Operations Console（取得 → 変換 → 公開 → 稼働 → 整合性）の集約。

各段の「正」は既存の一次情報から読む。DatasetState だけでは判定しない。
  取得     dataset definition（取得元・取込規約） + acquisition history（取得事実）
  変換     DatasetState の各 path（存在・size・mtime は stat）、canonical sha256 は永続キャッシュ、
           flood derived は routing meta（feature_count / source_feature_count / sha256）
  公開     dataset_runtime_reconcile（current → _manifest.json → artifact sha256）
  稼働     backend-public の startup loader 契約（app_public.py の読込規則・app.properties の有効フラグ）
  tile     current manifest の frontend/tiles + Martin 配信 mirror + MBTiles metadata

性能: 一覧は hash / SQLite 全走査をしない（allow_heavy=False）。詳細は反映元 sha256（永続キャッシュ）と
MBTiles の tile 数・quick_check（(path, size, mtime_ns) キーの永続キャッシュ）を初回だけ計算する。

観測できないものは推測で埋めない:
  - backend-public が実際に読み込んだ file は operator から観測する経路が無い（public route は最小化、
    operator は Docker gateway catalog 外の docker 操作をしない）。loader 契約上の対象かどうかだけを判定し、
    loaded は "unobserved" とする。
  - Martin の catalog は operator の内部 network から到達できない場合 "unobserved"。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import urlopen

from app.models.admin_dataset import DatasetDefinition, DatasetState, ValidationStatus, NormalizeStatus
from app.services import admin_atomic_publish as aap
from app.services import dataset_runtime_reconcile as drr
from app.services.acquisition_history import AcquisitionMethod, AcquisitionStatus, AcquisitionValidity, get_acquisition_store
from app.services.flood_routing_contract import FloodRoutingContractError, load_meta, routing_paths_for_canonical

logger = logging.getLogger(__name__)

# 段ごとの判定値（色だけに依存せず文字で表示する）
OK = "OK"
WARNING = "WARNING"
ERROR = "ERROR"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "N/A"
UNOBSERVED = "UNOBSERVED"  # 観測経路が無い（overall 判定の対象外。UI には必ず明示する）

_SEVERITY = {ERROR: 3, WARNING: 2, UNKNOWN: 1, OK: 0}

PROVENANCE_COMPLETE = "COMPLETE"
PROVENANCE_INCOMPLETE = "PROVENANCE INCOMPLETE"


# ── 共通 ────────────────────────────────────────────────────────────────────────

def _iso(ts: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


def _file_info(path: Optional[str]) -> Dict[str, Any]:
    info: Dict[str, Any] = {"path": path, "exists": False, "size": None, "mtime": None}
    if not path:
        return info
    try:
        st = Path(path).stat()
    except OSError:
        return info
    info.update(exists=True, size=st.st_size if Path(path).is_file() else None, mtime=_iso(st.st_mtime))
    return info


def _overall(components: Dict[str, Dict[str, Any]]) -> str:
    observed = [c["status"] for c in components.values() if c["status"] in _SEVERITY]
    if not observed:
        return UNKNOWN
    return max(observed, key=lambda s: _SEVERITY[s])


# ── backend loader 契約（app_public.py の startup loader と同じ規則）────────────

def _app_properties() -> Dict[str, str]:
    try:
        from app_config_properties import load_properties, resolve_config_path
        return load_properties(resolve_config_path(Path(__file__).resolve().parents[2]))
    except Exception as exc:  # noqa: BLE001 — 設定を読めなければ loader 判定は UNKNOWN
        logger.warning("app.properties を読めません: %s", exc)
        return {}


def _flag(props: Dict[str, str], key: str, default: bool) -> bool:
    from app_config_properties import parse_bool
    return parse_bool(props.get(key), default)


def loader_contract(rel: str, props: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """current 内 rel path が backend-public の起動時 loader の読込対象か。

    app_public.py: flood は hazard.flood.enabled 時に flood/ 配下の *.routing.geojson（rglob）、
    storm_surge / inland_flood / landslide / lowland_poor_drainage は各 dir 配下の *.geojson（rglob、
    有効フラグ時）、tsunami は hazard.tsunami.targets の tsunami_<target>.geojson、
    pseudo_inland_flood は backend では読まない（frontend 表示専用）。"""
    props = _app_properties() if props is None else props
    parts = rel.split("/")
    if len(parts) < 4 or parts[0] != "backend" or parts[1] != "hazard":
        return {"loader_target": False, "reason": "backend/hazard 配下ではない"}
    htype, name = parts[2], parts[-1]
    if not props:
        return {"loader_target": None, "reason": "app.properties を読めないため判定不能"}
    if htype == "flood":
        enabled = _flag(props, "hazard.flood.enabled", False)
        target = enabled and name.endswith(".routing.geojson")
        reason = "flood routing artifact（*.routing.geojson）" if target else (
            "hazard.flood.enabled=false" if not enabled else "routing artifact 以外は読まない（canonical / legacy 誤配置）")
        return {"loader_target": target, "reason": reason}
    if htype == "tsunami":
        from app_config_properties import parse_csv
        targets = parse_csv(props.get("hazard.tsunami.targets"), ["tokyo"])
        target = len(parts) == 4 and name in {f"tsunami_{t}.geojson" for t in targets}
        return {"loader_target": target,
                "reason": f"hazard.tsunami.targets={','.join(targets)}" + ("" if target else " に含まれない")}
    if htype == "pseudo_inland_flood":
        return {"loader_target": False, "reason": "backend では読まない（frontend 表示専用）"}
    flags = {"storm_surge": ("hazard.storm_surge.enabled", True), "inland_flood": ("hazard.inland_flood.enabled", True),
             "landslide": ("hazard.landslide.enabled", True),
             "lowland_poor_drainage": ("hazard.lowland_poor_drainage.enabled", True)}
    if htype in flags:
        key, default = flags[htype]
        enabled = _flag(props, key, default)
        target = enabled and name.endswith(".geojson")
        return {"loader_target": target, "reason": f"{htype}/ 配下の *.geojson を全件ロード" if target else f"{key}=false"}
    return {"loader_target": False, "reason": f"未知の hazard type: {htype}"}


# ── tile ────────────────────────────────────────────────────────────────────────

class TileInfoCache:
    """MBTiles の tile 数・quick_check を (path, size, mtime_ns) キーで永続キャッシュする。"""

    def __init__(self, path: Optional[Path]):
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        if path and path.is_file():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {}

    def get(self, path: Path, allow_heavy: bool) -> Optional[Dict[str, Any]]:
        try:
            st = path.stat()
        except OSError:
            return None
        key = str(path)
        with self._lock:
            rec = self._data.get(key)
            if rec and rec.get("size") == st.st_size and rec.get("mtime_ns") == st.st_mtime_ns:
                return rec
        if not allow_heavy:
            return None
        rec = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "checked_at": datetime.now(timezone.utc).isoformat()}
        try:
            conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
            try:
                rec["quick_check"] = conn.execute("PRAGMA quick_check").fetchone()[0]
                rec["tile_count"] = conn.execute("SELECT count(*) FROM tiles").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error as exc:
            rec["quick_check"] = f"error: {exc}"
            rec["tile_count"] = None
        with self._lock:
            self._data[key] = rec
            if self._path:
                try:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self._path.with_name(f".{self._path.name}.tmp-{os.getpid()}")
                    tmp.write_text(json.dumps(self._data, sort_keys=True), encoding="utf-8")
                    os.replace(tmp, self._path)
                except OSError as exc:
                    logger.warning("tile info cache を保存できません: %s", exc)
        return rec


_tile_cache: Optional[TileInfoCache] = None


def get_tile_cache() -> TileInfoCache:
    global _tile_cache
    if _tile_cache is None:
        from app.services.dataset_state_service import _ADMIN_STATE_DIR
        _tile_cache = TileInfoCache(Path(_ADMIN_STATE_DIR).parent / "cache" / "tile_integrity.json")
    return _tile_cache


def _mbtiles_metadata(path: Path) -> Dict[str, Any]:
    """metadata table だけを読む（軽量）。"""
    out: Dict[str, Any] = {"minzoom": None, "maxzoom": None, "vector_layers": [], "format": None, "error": None}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        finally:
            conn.close()
    except sqlite3.Error as exc:
        out["error"] = str(exc)
        return out
    out["minzoom"], out["maxzoom"], out["format"] = meta.get("minzoom"), meta.get("maxzoom"), meta.get("format")
    try:
        out["vector_layers"] = [v.get("id") for v in json.loads(meta.get("json") or "{}").get("vector_layers", [])]
    except (ValueError, AttributeError):
        pass
    return out


_martin_lock = threading.Lock()
_martin_cache: Dict[str, Any] = {"at": 0.0, "ids": None}


def martin_catalog_ids(ttl: float = 60.0) -> Optional[List[str]]:
    """Martin /catalog の source ID。到達できなければ None（UNOBSERVED）。60 秒キャッシュ。"""
    with _martin_lock:
        if time.monotonic() - _martin_cache["at"] < ttl:
            return _martin_cache["ids"]
    ids = None
    url = os.getenv("MARTIN_INTERNAL_URL", "http://martin:3000").rstrip("/") + "/catalog"
    try:
        with urlopen(url, timeout=1) as resp:
            ids = list(json.loads(resp.read()).get("tiles", {}).keys())
    except (URLError, OSError, ValueError):
        ids = None
    with _martin_lock:
        _martin_cache.update(at=time.monotonic(), ids=ids)
    return ids


def tile_section(defn: DatasetDefinition, view: drr.RuntimeView, allow_heavy: bool,
                 catalog: Optional[List[str]] = None) -> Dict[str, Any]:
    if not defn.requires_tile_build or not defn.layer_type:
        return {"status": NOT_APPLICABLE, "required": False}
    stem = defn.dataset_id.lower().replace("-", "_")
    rel = f"frontend/tiles/{defn.region}/{defn.layer_type}/{stem}.mbtiles"
    sec: Dict[str, Any] = {"required": True, "tileset_id": stem, "rel_path": rel, "in_current": False,
                           "current_sha256": None, "mirror": None, "martin_registered": UNOBSERVED,
                           "metadata": None, "integrity": None}
    if not view.ok:
        sec.update(status=UNKNOWN, reason=view.error)
        return sec
    sec["current_sha256"] = view.files.get(rel)
    sec["in_current"] = sec["current_sha256"] is not None
    mirror = view.root / rel  # Martin が配信する mirror（data_runtime/frontend/tiles → /tiles）
    sec["mirror"] = _file_info(str(mirror))
    version_file = view.version_path(rel)
    if catalog is not None:
        sec["martin_registered"] = OK if stem in catalog else ERROR
    if not sec["in_current"]:
        sec.update(status=ERROR, reason="current version に tile がありません")
        return sec
    sec["metadata"] = _mbtiles_metadata(version_file)
    vsize = version_file.stat().st_size if version_file.is_file() else None
    if not sec["mirror"]["exists"] or sec["mirror"]["size"] != vsize:
        sec.update(status=ERROR, reason="Martin 配信 mirror が current の tile と一致しません（size 不一致または欠落）")
        return sec
    integ = get_tile_cache().get(version_file, allow_heavy)
    sec["integrity"] = integ
    if sec["metadata"].get("error"):
        sec.update(status=ERROR, reason=f"MBTiles metadata を読めません: {sec['metadata']['error']}")
    elif integ is not None and integ.get("quick_check") != "ok":
        sec.update(status=ERROR, reason=f"quick_check: {integ.get('quick_check')}")
    elif sec["martin_registered"] == ERROR:
        sec.update(status=ERROR, reason="Martin catalog に source がありません")
    else:
        sec.update(status=OK, reason=None if integ else "tile 数・quick_check は未計算（詳細表示で計算）")
    return sec


# ── 取得 ────────────────────────────────────────────────────────────────────────

def _raw_cache_status(state: Optional[DatasetState], active, runtime_record) -> Dict[str, Any]:
    """この node の raw（DatasetState.current_raw_path）が現在の source と一致するか（情報表示のみ）。
    runtime node の raw は source of truth ではない（build node で取得・検証済み）。"""
    raw = state.current_raw_path if state else None
    if not raw:
        return {"status": "ABSENT", "path": None}
    name = Path(raw).name
    if not Path(raw).exists():
        return {"status": "ABSENT", "path": raw}
    if not os.access(raw, os.R_OK):
        return {"status": "UNREADABLE", "path": raw, "reason": "この process から読めない（権限）"}
    current_names = set()
    if active is not None:
        current_names = {Path(active.raw_path).name} if active.raw_path else set()
        if active.bundle:
            current_names.add(active.bundle.name)
    elif runtime_record and runtime_record.get("source"):
        src = runtime_record["source"]
        if src.get("bundle"):
            current_names.add(src["bundle"].get("name"))
        current_names |= {f.get("name") for f in src.get("source_files") or []}
    if not current_names:
        return {"status": "UNKNOWN", "path": raw}
    if name in current_names:
        return {"status": "CURRENT", "path": raw}
    return {"status": "STALE", "path": raw, "reason": "現在の source（runtime / 取得履歴）と一致しない raw（NOT CURRENT SOURCE）"}


def acquisition_section(defn: DatasetDefinition, store=None, state: Optional[DatasetState] = None,
                        runtime_prov: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    store = store or get_acquisition_store()
    try:
        records = store.list(defn.dataset_id)
        error = None
    except Exception as exc:  # noqa: BLE001
        records, error = [], f"取得履歴を読めません: {exc}"
    active = next((r for r in records if r.active), None)
    # runtime node: 取得履歴が無くても、current version の provenance record が manifest と照合済み
    # （VERIFIED）なら、build node で検証された source provenance を採用する（推測ではなく記録）。
    from app.services import runtime_provenance as rp
    rt_record = (runtime_prov or {}).get("record") if (runtime_prov or {}).get("status") == rp.VERIFIED else None
    rt_source = (rt_record or {}).get("source")
    missing = []
    if not defn.source_provider:
        missing.append("取得元組織（source_provider）")
    if not defn.source_dataset_name:
        missing.append("取得データ名（source_dataset_name）")
    if active is None and rt_source is None:
        missing.append("採用中の取得履歴（acquisition history）")
    elif active is None:
        pass
    else:
        if active.acquisition_method == AcquisitionMethod.legacy_unknown:
            missing.append("取得方法")
        if not active.source_files:
            missing.append("DL 原本")
    # source component: provenance_mismatch → ERROR、suspect / unknown / 欠落 → WARNING、valid かつ欠落なし → OK
    if active is not None:
        validity, validity_reason = active.validity.value, active.validity_reason
        validity_flags, validity_source = list(active.validity_flags), "acquisition_history"
    elif rt_source is not None:
        validity, validity_reason = rt_source.get("validity") or AcquisitionValidity.unknown.value, rt_source.get("validity_reason")
        validity_flags, validity_source = list(rt_source.get("validity_flags") or []), "runtime_provenance"
    else:
        validity, validity_reason = AcquisitionValidity.unknown.value, "no acquisition history"
        validity_flags, validity_source = [], None
    raw_cache = _raw_cache_status(state, active, rt_record)
    # 現在の raw の地域コード照合: 取得履歴も検証済み runtime record も無い場合だけ source 判定に使う
    # （runtime node の旧 raw cache で、正しい runtime を MISMATCH にしない）。
    from app.services import provenance_validity
    raw_check = provenance_validity.assess_raw_region(defn, state.current_raw_path if state else None)
    if raw_check and raw_check[0] == AcquisitionValidity.provenance_mismatch:
        if raw_cache.get("status") == "STALE":
            # 現在の source（取得履歴 / 検証済み runtime record）と一致しない旧 raw cache の不一致は、
            # runtime の provenance ではない（情報として表示するだけ）
            raw_cache["region_check"] = raw_check[1]
        else:
            # 取得履歴・record が無い、または raw が現在の source そのもの / 判別不能なら安全側で反映する
            validity, validity_reason, validity_flags = raw_check[0].value, raw_check[1], raw_check[2]
            validity_source = "current_raw_check"
    if validity == AcquisitionValidity.provenance_mismatch.value:
        status = ERROR
    elif missing or error or validity != AcquisitionValidity.valid.value:
        status = WARNING
    else:
        status = OK
    return {
        "source_provider": defn.source_provider,
        "source_dataset_name": defn.source_dataset_name,
        "official_source_url": defn.official_source_url,
        "source_url": defn.source_url,
        "source_year": defn.source_year,
        "source_version": defn.source_version,
        "source_group_mode": defn.source_group_mode.value if defn.source_group_mode else None,
        "ingest_mode": defn.ingest_mode.value if defn.ingest_mode else None,
        "required_source_count": defn.required_source_count,
        "source_file_patterns": defn.source_file_patterns,
        "expected_source_files": defn.expected_source_files,
        "ingest_replaces_canonical": defn.ingest_replaces_canonical,
        "single_batch_required": bool(defn.ingest_mode and defn.ingest_mode.value == "single_batch"),
        "ingest_notes": defn.ingest_notes,
        "operator_notes": defn.operator_notes,
        "active": active.model_dump(mode="json") if active else None,
        "history_count": len(records),
        "provenance_status": PROVENANCE_COMPLETE if not missing else PROVENANCE_INCOMPLETE,
        "provenance_missing": missing,
        # active（現在採用中）と validity（健全性）は別軸。履歴が無ければ validity は unknown
        "validity": validity,
        "validity_reason": validity_reason,
        "validity_flags": validity_flags,
        "validity_source": validity_source,
        # この node に取得履歴があるか（runtime node では NOT PRESENT が正常）
        "acquisition_history": "PRESENT" if active is not None else (
            "NOT PRESENT ON THIS NODE" if rt_source is not None else "ABSENT"),
        "source_validated_on": (rt_record or {}).get("build_node") if active is None and rt_source else None,
        "raw_cache": raw_cache,
        "error": error,
        "status": status,
    }


# ── 変換 ────────────────────────────────────────────────────────────────────────

def transform_section(defn: DatasetDefinition, state: DatasetState, view: drr.RuntimeView,
                      res: drr.ReconcileResult, allow_hash: bool,
                      validation_job_ids: Optional[List[Optional[str]]] = None) -> Dict[str, Any]:
    cache = drr.get_source_sha_cache()
    raw = _file_info(state.current_raw_path)
    normalized = _file_info(state.current_normalized_path)
    canonical = _file_info(state.current_validated_path)
    canonical["sha256"] = cache.get(Path(state.current_validated_path), allow_hash) \
        if canonical["exists"] and canonical["size"] is not None else None
    canonical["feature_count"] = None
    canonical["feature_count_source"] = None
    canonical["validation_status"] = state.validation_status.value
    derived: Dict[str, Any] = {"status": NOT_APPLICABLE}

    if defn.layer_type == "flood" and canonical["exists"]:
        try:
            routing, meta_path = routing_paths_for_canonical(Path(state.current_validated_path))
            meta = load_meta(meta_path)
            canonical["feature_count"] = meta.get("source_feature_count")
            canonical["feature_count_source"] = "routing meta（source_feature_count）"
            derived = _file_info(str(routing))
            derived.update(
                meta_path=str(meta_path), feature_count=meta["feature_count"], sha256=meta["routing_artifact_sha256"],
                source_canonical_sha256=meta["source_canonical_sha256"], builder_version=meta.get("builder_version"),
                generated_at=meta.get("generated_at"),
                routing_validation=routing_validation_from_logs(validation_job_ids or [], routing.name,
                                                                meta["feature_count"]) if validation_job_ids else None,
            )
            if canonical["sha256"] is None:
                derived.update(status=UNKNOWN, reason="canonical sha256 未計算（詳細表示で計算）")
            elif canonical["sha256"] != meta["source_canonical_sha256"]:
                derived.update(status=ERROR, reason="canonical 更新後に routing が再生成されていません（stale derived）")
            elif not derived["exists"]:
                derived.update(status=ERROR, reason="routing artifact がありません")
            else:
                derived.update(status=OK, reason=None)
        except FloodRoutingContractError as exc:
            derived = {"status": ERROR, "reason": f"routing meta 不正: {exc}"}
    elif res.runtime_rel and res.matches_source and view.ok:
        # 反映元 = runtime artifact（sha256 一致）なら manifest の feature_count がそのまま canonical 件数
        fc = view_feature_counts(view).get(res.runtime_rel)
        if fc is not None:
            canonical["feature_count"] = fc
            canonical["feature_count_source"] = "current manifest（sha256 一致）"

    canonical["metadata"] = _canonical_metadata(defn, state.current_validated_path) if canonical["exists"] else None
    artifact_mode = getattr(defn, "publish_verification_mode", None) == "artifact_record"
    if not canonical["exists"] and artifact_mode and defn.layer_type == "flood":
        # runtime node（artifact_record 方式）: canonical 本体は置かない。build node で検証済みの record と
        # routing meta の連鎖で derived を判定する
        canonical.update(status=NOT_APPLICABLE, reason="artifact_record 方式: canonical 本体はこの node に置かない（build node で検証済み）")
        derived = _artifact_record_derived(defn, state)
        return {"raw": raw, "normalized": normalized, "canonical": canonical, "derived": derived,
                "normalize_status": state.normalize_status.value, "coverage_policy": _coverage_policy(defn),
                "verification": "artifact_record"}
    if not canonical["exists"]:
        cstatus = WARNING if defn.requires_validation or defn.requires_normalize else NOT_APPLICABLE
        creason = "canonical（validated）がありません"
    elif canonical["metadata"] and canonical["metadata"]["consistent"] is False:
        cstatus = WARNING
        creason = "canonical の provenance metadata が dataset 定義と不一致: " + "; ".join(canonical["metadata"]["mismatches"])
    elif state.validation_status == ValidationStatus.failed or state.normalize_status == NormalizeStatus.failed:
        cstatus, creason = ERROR, "変換または検証が失敗しています"
    else:
        cstatus, creason = OK, None
    canonical.update(status=cstatus, reason=creason)
    coverage_policy = _coverage_policy(defn)
    return {"raw": raw, "normalized": normalized, "canonical": canonical, "derived": derived,
            "normalize_status": state.normalize_status.value, "coverage_policy": coverage_policy,
            "verification": "artifact_record" if artifact_mode else "canonical_file"}


def _coverage_policy(defn: DatasetDefinition) -> Optional[Dict[str, Any]]:
    coverage_policy = None
    if defn.coverage_required_meshes:
        coverage_policy = {
            "required_meshes": list(defn.coverage_required_meshes),
            "allow_empty_meshes": list(defn.coverage_allow_empty_meshes),
            "notes": list(defn.coverage_notes),
            # 例外は単純 PASS と区別して表示する
            "exceptions": [f"{m}: OFFICIAL SOURCE CONTAINS NO {defn.region.upper()} FEATURES"
                           for m in defn.coverage_allow_empty_meshes],
        }
    return coverage_policy


def _artifact_record_derived(defn: DatasetDefinition, state: DatasetState) -> Dict[str, Any]:
    from app.services import build_provenance, runtime_provenance as rp
    if not state.current_validated_path:
        return {"status": UNKNOWN, "reason": "canonical の参照 path が無い"}
    try:
        routing, meta_path = routing_paths_for_canonical(Path(state.current_validated_path))
        meta = load_meta(meta_path)
    except FloodRoutingContractError as exc:
        return {"status": ERROR, "reason": f"routing meta 不正: {exc}"}
    out = _file_info(str(routing))
    out.update(meta_path=str(meta_path), feature_count=meta["feature_count"], sha256=meta["routing_artifact_sha256"],
               source_canonical_sha256=meta["source_canonical_sha256"], builder_version=meta.get("builder_version"),
               generated_at=meta.get("generated_at"), routing_validation=None)
    try:
        record = json.loads(rp.build_path(build_provenance._data_lake_root(), defn.region, "flood",
                                          defn.dataset_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out.update(status=ERROR, reason="artifact_record 方式だが build provenance record が無い")
        return out
    ok = ((record.get("runtime_artifact") or {}).get("sha256") == meta["routing_artifact_sha256"]
          and (record.get("canonical") or {}).get("sha256") == meta["source_canonical_sha256"])
    fn = (record.get("validation") or {}).get("routing_coverage_false_negatives")
    out["routing_validation"] = {"coverage_false_negatives": fn,
                                 "source": (record.get("validation") or {}).get("routing_validation_source")} \
        if fn is not None else None
    if not out["exists"]:
        out.update(status=ERROR, reason="routing artifact がありません")
    elif not ok:
        out.update(status=ERROR, reason="routing meta と build provenance record の連鎖が不一致")
    else:
        out.update(status=OK, reason=None)
    return out


_ROUTING_RESULT_KEYS = ("routing", "feature_count", "coverage_false_negatives")


def routing_validation_from_logs(job_ids: List[Optional[str]], routing_name: str,
                                 feature_count: Optional[int]) -> Optional[Dict[str, Any]]:
    """validate_flood_routing_artifact.py が job log に出力した結果 JSON 行（事実）を探す。
    routing file 名と feature_count が現行 routing meta と一致する行だけを採用する（別世代の結果を使わない）。"""
    from app.services.dataset_state_service import _ADMIN_STATE_DIR
    logs = Path(_ADMIN_STATE_DIR).parent / "logs"
    for job_id in [j for j in job_ids if j]:
        path = logs / f"{Path(job_id).name}.log"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            start = line.find('{"routing"')
            if start < 0:
                continue
            try:
                obj = json.loads(line[start:])
            except ValueError:
                continue
            if not all(k in obj for k in _ROUTING_RESULT_KEYS):
                continue
            if Path(str(obj["routing"])).name == routing_name and obj["feature_count"] == feature_count:
                return {"coverage_false_negatives": obj["coverage_false_negatives"], "feature_count": obj["feature_count"],
                        "source": f"job log {job_id}"}
    return None


def _canonical_metadata(defn: DatasetDefinition, path: Optional[str]) -> Optional[Dict[str, Any]]:
    """normalizer が付与した provenance metadata（source_dataset / normalized_region_code）を先頭 feature
    から読み、dataset 定義と照合する（先頭 1 件だけを stream で読む。metadata を持たない dataset は None）。"""
    if not path:
        return None
    try:
        import ijson
        with open(path, "rb") as f:
            first = next(ijson.items(f, "features.item"), None)
    except Exception:  # noqa: BLE001 — 読めなければ照合しない
        return None
    props = (first or {}).get("properties") or {}
    if "source_dataset" not in props and "normalized_region_code" not in props:
        return None
    mismatches = []
    if props.get("source_dataset") not in (None, defn.dataset_id):
        mismatches.append(f"source_dataset={props.get('source_dataset')}（期待 {defn.dataset_id}）")
    if defn.expected_source_region_code and props.get("normalized_region_code") not in (
            None, defn.expected_source_region_code):
        mismatches.append(f"normalized_region_code={props.get('normalized_region_code')}"
                          f"（期待 {defn.expected_source_region_code}）")
    return {"source_dataset": props.get("source_dataset"), "region_code": props.get("normalized_region_code"),
            "expected_region_code": defn.expected_source_region_code, "consistent": not mismatches,
            "mismatches": mismatches, "checked": "first feature"}


_fc_cache: Dict[str, Any] = {}


def view_feature_counts(view: drr.RuntimeView) -> Dict[str, int]:
    """current manifest の feature_counts（manifest 単位でキャッシュ）。"""
    if not view.ok:
        return {}
    path = view.root / "versions" / str(view.version_id) / "_manifest.json"
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_mtime_ns, st.st_size)
    if _fc_cache.get("key") != key:
        try:
            fc = json.loads(path.read_text(encoding="utf-8")).get("feature_counts") or {}
        except (OSError, ValueError):
            fc = {}
        _fc_cache.update(key=key, value=fc if isinstance(fc, dict) else {})
    return _fc_cache["value"]


# ── 稼働 ────────────────────────────────────────────────────────────────────────

_RUNTIME_COMPONENT = {
    drr.PUBLISHED: OK, drr.MISMATCH: WARNING, drr.NOT_PUBLISHED: WARNING, drr.STALE: ERROR,
    drr.UNSUPPORTED: WARNING, drr.UNKNOWN: UNKNOWN, drr.LEGACY: NOT_APPLICABLE,
}


def runtime_section(res: drr.ReconcileResult, view: drr.RuntimeView, props: Dict[str, str]) -> Dict[str, Any]:
    fc = view_feature_counts(view).get(res.runtime_rel) if res.runtime_rel else None
    sec = res.as_dict()
    sec.pop("provenance", None)
    sec.update(feature_count=fc, manifest_match=res.matches_source,
               status=_RUNTIME_COMPONENT.get(res.runtime_status, UNKNOWN))
    if res.artifact_present and res.runtime_rel:
        lc = loader_contract(res.runtime_rel, props)
        backend = {"loader_target": lc["loader_target"], "loader_reason": lc["reason"], "loaded": UNOBSERVED,
                   "loaded_reason": "backend-public の読込状態は operator から観測できません（起動時に current を読込）"}
        if lc["loader_target"] is False:
            backend["status"] = NOT_APPLICABLE if res.layer_type == "pseudo_inland_flood" else WARNING
        else:
            backend["status"] = UNOBSERVED if lc["loader_target"] else UNKNOWN
    else:
        backend = {"loader_target": None, "loaded": UNOBSERVED, "status": NOT_APPLICABLE if res.publish_mode == "legacy"
                   else UNKNOWN if res.runtime_status == drr.UNKNOWN else NOT_APPLICABLE,
                   "loader_reason": "current に artifact がありません" if res.publish_mode != "legacy" else None}
    sec["backend"] = backend
    return sec


# ── runtime provenance ─────────────────────────────────────────────────────────

def runtime_provenance_section(defn: DatasetDefinition, res: drr.ReconcileResult,
                               view: drr.RuntimeView) -> Dict[str, Any]:
    """current → _manifest.json → provenance/<dataset_id>.json を manifest と照合する。"""
    from app.services import runtime_provenance as rp
    if res.publish_mode != "atomic" or not res.artifact_present or not view.ok:
        return {"status": "N/A", "component_status": NOT_APPLICABLE, "reasons": [], "record": None}
    out = rp.verify_runtime(view, defn.dataset_id, res.runtime_rel, view_feature_counts(view))
    rec = out.get("record")
    if out["status"] == rp.VERIFIED and rec and defn.layer_type == "flood" and res.provenance.get("canonical_path"):
        # この node の routing meta が runtime と同じ routing を記述しているなら、その生成元 canonical は
        # record の canonical と一致しなければならない（record 内部の連鎖の整合）。
        try:
            from app.services.flood_routing_contract import load_meta, routing_paths_for_canonical
            _r, meta_path = routing_paths_for_canonical(Path(res.provenance["canonical_path"]))
            meta = load_meta(meta_path)
            if meta["routing_artifact_sha256"] == rec["runtime_artifact"]["sha256"]:
                ok = meta["source_canonical_sha256"] == (rec.get("canonical") or {}).get("sha256")
                out["checks"].append({"check": "canonical.sha256 (routing meta)", "ok": ok,
                                      "meta": meta["source_canonical_sha256"], "record": (rec.get("canonical") or {}).get("sha256")})
                if not ok:
                    out["status"] = rp.MISMATCH
                    out["reasons"].append("routing meta の source_canonical_sha256 が record の canonical と不一致")
        except Exception:  # noqa: BLE001 — meta が無い / 読めない node では照合しない
            pass
    out["component_status"] = {rp.VERIFIED: OK, rp.MISMATCH: ERROR, rp.INVALID: ERROR}.get(out["status"], UNKNOWN)
    return out


# ── 組み立て ────────────────────────────────────────────────────────────────────

def build_dataset(defn: DatasetDefinition, state: DatasetState, view: drr.RuntimeView, *, allow_hash: bool,
                  allow_heavy: bool, props: Dict[str, str], catalog: Optional[List[str]] = None,
                  store=None) -> Dict[str, Any]:
    res = drr.reconcile_dataset(defn, state, view, None, allow_hash)
    rt_prov = runtime_provenance_section(defn, res, view)
    acq = acquisition_section(defn, store, state, rt_prov)
    job_ids = [(acq["active"] or {}).get("ingest_job_id"), state.last_job_id] if allow_heavy else None
    tr = transform_section(defn, state, view, res, allow_hash, job_ids)
    rt = runtime_section(res, view, props)
    tile = tile_section(defn, view, allow_heavy, catalog)
    components = {
        "source": {"status": acq["status"], "reason": "; ".join(
            x for x in [acq["validity"] if acq["validity"] != "valid" else None, acq["validity_reason"]
                        if acq["validity"] != "valid" else None, ", ".join(acq["provenance_missing"]) or None, acq["error"]] if x)
                   or None},
        "canonical": {"status": tr["canonical"]["status"], "reason": tr["canonical"].get("reason")},
        "derived": {"status": tr["derived"]["status"], "reason": tr["derived"].get("reason")},
        "runtime": {"status": rt["status"], "reason": rt.get("reason") or rt["runtime_status"]},
        "backend": {"status": rt["backend"]["status"], "reason": rt["backend"].get("loader_reason")},
        "tile": {"status": tile["status"], "reason": tile.get("reason")},
        "runtime_provenance": {"status": rt_prov["component_status"], "reason": "; ".join(rt_prov.get("reasons") or [])
                               or rt_prov["status"]},
    }
    return {
        "dataset_id": defn.dataset_id,
        "display_name": defn.display_name,
        "category": defn.category,
        "layer_type": defn.layer_type,
        "region": defn.region,
        "acquisition": acq,
        "transform": tr,
        "runtime": rt,
        "tile": tile,
        "runtime_provenance": rt_prov,
        "integrity": {
            "overall": _overall(components),
            "components": components,
            "unobserved": [k for k, c in components.items() if c["status"] == UNOBSERVED],
        },
    }


def unregistered_section(view: drr.RuntimeView, expected: "set[str]", props: Dict[str, str]) -> List[Dict[str, Any]]:
    fcs = view_feature_counts(view)
    out = []
    for u in drr.unregistered_runtime_artifacts(view, expected):
        lc = loader_contract(u["rel_path"], props)
        out.append({**u, "feature_count": fcs.get(u["rel_path"]), "loader_target": lc["loader_target"],
                    "loader_reason": lc["reason"], "in_use": lc["loader_target"],
                    "provenance": UNKNOWN, "label": "UNREGISTERED RUNTIME SOURCE"})
    return out


def build_console(ds=None, ss=None, *, dataset_id: Optional[str] = None, allow_hash: bool = False,
                  allow_heavy: bool = False, root: Optional[Path] = None, store=None) -> Dict[str, Any]:
    if ds is None:
        from app.services.dataset_definition_service import get_definition_service
        ds = get_definition_service()
    if ss is None:
        from app.services.dataset_state_service import get_state_service
        ss = get_state_service()
    view = drr.load_runtime_view(root)
    props = _app_properties()
    catalog = martin_catalog_ids()
    rows, errors, expected = [], [], set()
    for defn in ds.list_all():
        state = ss.init_from_definition(defn)
        rel = drr.expected_runtime_rel(defn, state)
        if rel:
            expected.add(rel)
        if dataset_id and defn.dataset_id != dataset_id:
            continue
        try:
            rows.append(build_dataset(defn, state, view, allow_hash=allow_hash, allow_heavy=allow_heavy,
                                      props=props, catalog=catalog, store=store))
        except Exception as exc:  # noqa: BLE001 — 1 dataset の失敗で一覧全体を止めない
            logger.warning("data-ops build failed: %s: %s", defn.dataset_id, exc)
            errors.append({"dataset_id": defn.dataset_id, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "current_version": view.version_id,
        "runtime_error": view.error,
        "published_at": view.published_at.isoformat() if view.published_at else None,
        "martin_catalog": "observed" if catalog is not None else UNOBSERVED,
        "datasets": rows,
        "errors": errors,
        "unregistered_runtime_artifacts": unregistered_section(view, expected, props),
    }
