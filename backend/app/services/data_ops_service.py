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


# 表示 tile の状態（UI の表示名と対応）。DatasetDefinition.tile_requirement の契約で判定する。
TILE_STATES = {
    "TILE_OK": "TILE OK",
    "TILE_NOT_APPLICABLE": "TILE N/A",
    "REQUIRED_TILE_MISSING": "REQUIRED TILE MISSING",
    "REQUIRED_TILE_UNMANAGED": "REQUIRED TILE UNMANAGED",
    "OPTIONAL_TILE_MISSING": "OPTIONAL TILE MISSING",
    "LEGACY_UNMANAGED_TILE": "LEGACY UNMANAGED TILE",
    "UNKNOWN_TILE_CONTRACT": "UNKNOWN TILE CONTRACT",
    "TILE_BROKEN": "TILE ERROR",
}


def tile_rel(defn: DatasetDefinition) -> str:
    """dataset の管理 tile の current 内相対 path。tile_rel_path があればそれ（既存 tile の明示登録）。"""
    if defn.tile_rel_path:
        return defn.tile_rel_path
    return f"frontend/tiles/{defn.region}/{defn.layer_type}/{defn.dataset_id.lower().replace('-', '_')}.mbtiles"


def tile_tileset_id(defn: DatasetDefinition) -> str:
    return Path(tile_rel(defn)).stem


def tile_rel_candidates(defn: DatasetDefinition) -> List[str]:
    """dataset の tile として扱う path。現行の tile_rel と、TILE-PATH-MIGRATION で移動する前の旧 path
    （tile_dispositions.json の disposition=MIGRATED、migrated_to が現行 path）。rollback 先が移動前の
    version でも同じ tile として判定する。"""
    rel = tile_rel(defn)
    return [rel] + [r for r, d in sorted(load_tile_dispositions().items())
                    if d.get("disposition") == "MIGRATED" and d.get("migrated_to") == rel]


def tile_requirement(defn: DatasetDefinition) -> str:
    """required / optional / not_applicable / unknown（未設定で requires_tile_build=true）。"""
    if defn.tile_requirement:
        return defn.tile_requirement
    if not defn.requires_tile_build or not defn.layer_type:
        return "not_applicable"
    return "unknown"


def _tile_set(sec: Dict[str, Any], status: str, state: str, reason: Optional[str]) -> Dict[str, Any]:
    sec.update(status=status, state=state, label=TILE_STATES[state], reason=reason)
    return sec


def tile_section(defn: DatasetDefinition, view: drr.RuntimeView, allow_heavy: bool,
                 catalog: Optional[List[str]] = None) -> Dict[str, Any]:
    req = tile_requirement(defn)
    if req == "not_applicable" or not defn.layer_type:
        return {"status": NOT_APPLICABLE, "required": False, "requirement": "not_applicable",
                "state": "TILE_NOT_APPLICABLE", "label": TILE_STATES["TILE_NOT_APPLICABLE"],
                "notes": list(defn.tile_notes)}
    stem = tile_tileset_id(defn)
    rel = tile_rel(defn)
    if view.ok and rel not in view.files:
        # 移動前の version（rollback 中など）では旧 path にある tile を同じ tile として扱う
        rel = next((c for c in tile_rel_candidates(defn) if c in view.files), rel)
    sec: Dict[str, Any] = {"required": req == "required", "requirement": req, "notes": list(defn.tile_notes),
                           "tileset_id": stem, "rel_path": rel, "in_current": False,
                           "current_sha256": None, "mirror": None, "martin_registered": UNOBSERVED,
                           "metadata": None, "integrity": None, "managed": False}
    if not view.ok:
        return _tile_set(sec, UNKNOWN, "UNKNOWN_TILE_CONTRACT", view.error)
    sec["current_sha256"] = view.files.get(rel)
    sec["in_current"] = sec["managed"] = sec["current_sha256"] is not None
    mirror = view.root / rel  # Martin が配信する mirror（data_runtime/frontend/tiles → /tiles）
    sec["mirror"] = _file_info(str(mirror))
    version_file = view.version_path(rel)
    if catalog is not None:
        sec["martin_registered"] = OK if stem in catalog else ERROR
    if not sec["in_current"]:
        # current（publish / rollback の管理下）に tile が無い。mirror に残る tile は管理外（legacy）。
        legacy = bool(sec["mirror"] and sec["mirror"]["exists"])
        served = " Martin が配信中" if legacy and sec["martin_registered"] == OK else ""
        if req == "required":
            if legacy:
                return _tile_set(sec, ERROR, "REQUIRED_TILE_UNMANAGED",
                                 "表示に必須の tile が current に無い（mirror の管理外 tile だけで表示中。"
                                 f"publish・rollback で管理されない）。{served}".strip())
            return _tile_set(sec, ERROR, "REQUIRED_TILE_MISSING", "表示に必須の tile が current にも mirror にも無い")
        if req == "optional":
            if legacy:
                return _tile_set(sec, WARNING, "LEGACY_UNMANAGED_TILE",
                                 "current に tile が無く、mirror の管理外 tile が表示に使われている"
                                 f"（無ければ API GeoJSON で表示される）。{served}".strip())
            return _tile_set(sec, WARNING, "OPTIONAL_TILE_MISSING", "tile 未生成（API GeoJSON で表示される）")
        return _tile_set(sec, UNKNOWN, "UNKNOWN_TILE_CONTRACT",
                         "tile_requirement が未定義のため、tile 欠落の重大度を判定できない")
    sec["metadata"] = _mbtiles_metadata(version_file)
    vsize = version_file.stat().st_size if version_file.is_file() else None
    if not sec["mirror"]["exists"] or sec["mirror"]["size"] != vsize:
        return _tile_set(sec, ERROR, "TILE_BROKEN",
                         "Martin 配信 mirror が current の tile と一致しません（size 不一致または欠落）")
    integ = get_tile_cache().get(version_file, allow_heavy)
    sec["integrity"] = integ
    if sec["metadata"].get("error"):
        return _tile_set(sec, ERROR, "TILE_BROKEN", f"MBTiles metadata を読めません: {sec['metadata']['error']}")
    if integ is not None and integ.get("quick_check") != "ok":
        return _tile_set(sec, ERROR, "TILE_BROKEN", f"quick_check: {integ.get('quick_check')}")
    if sec["martin_registered"] == ERROR:
        return _tile_set(sec, ERROR, "TILE_BROKEN", "Martin catalog に source がありません")
    return _tile_set(sec, OK, "TILE_OK", None if integ else "tile 数・quick_check は未計算（詳細表示で計算）")


def legacy_tile_section(view: drr.RuntimeView, defs: List[DatasetDefinition],
                        catalog: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """dataset の管理 tile（current 内の frontend/tiles/<region>/<type>/<dataset>.mbtiles）以外の tile。
    current 内の未登録 tile と、current に無く mirror だけにある tile（publish・rollback の管理外）。削除はしない。"""
    if not view.ok:
        return []
    managed = {c: d.dataset_id for d in defs if d.layer_type and tile_requirement(d) != "not_applicable"
               for c in tile_rel_candidates(d)}
    dispositions = load_tile_dispositions()
    current_tiles = {r for r in view.files if r.startswith("frontend/tiles/") and r.endswith(".mbtiles")}
    mirror_root = view.root / "frontend" / "tiles"
    mirror_tiles = set()
    if mirror_root.is_dir():
        mirror_tiles = {f"frontend/tiles/{p.relative_to(mirror_root)}" for p in mirror_root.rglob("*.mbtiles")}
    out = []
    for rel in sorted(current_tiles | mirror_tiles):
        in_current, in_mirror = rel in current_tiles, rel in mirror_tiles
        owner = managed.get(rel)
        if owner and in_current:
            continue  # 管理下（tile_section が判定する）
        stem = Path(rel).stem
        disp = dispositions.get(rel) if not owner else None
        if owner:
            label = "LEGACY TILE（dataset の tile、current 管理外）"
        elif disp:
            label = TILE_DISPOSITION_LABELS[disp["disposition"]]
        else:
            label = ("UNREGISTERED CURRENT TILE（分類未定）" if in_current else "UNREGISTERED TILE（mirror のみ・分類未定）")
        out.append({
            "rel_path": rel, "tileset_id": stem, "in_current": in_current, "in_mirror": in_mirror,
            "dataset_id": owner,  # dataset の tile 名と一致するが current に無い（mirror だけ）
            "martin_registered": UNOBSERVED if catalog is None else (OK if stem in catalog else ERROR),
            "disposition": disp["disposition"] if disp else None,
            "consumer": disp.get("consumer") if disp else None,
            "superseded_by": disp.get("superseded_by") if disp else None,
            "notes": list(disp.get("notes", [])) if disp else [],
            "label": label,
        })
    return out


# 契約を持たない tile の棚卸し結果（data_lake/registry/tile_dispositions.json）。削除・登録の判断材料として表示するだけで、
# 自動削除はしない。dataset の tile 契約より優先しない（契約がある tile は tile_section が判定する）。
TILE_DISPOSITIONS = ("RETIRE_CANDIDATE", "KEEP_LEGACY", "UNKNOWN_CONTRACT", "RETIRED", "MIGRATED")
TILE_DISPOSITION_LABELS = {
    "RETIRED": "RETIRED（退役済みのはずが current / mirror に残存）",
    "MIGRATED": "MIGRATED（移動前の旧 path）",
    "RETIRE_CANDIDATE": "RETIRE CANDIDATE（未使用・後継 tile あり。削除は別 Phase）",
    "KEEP_LEGACY": "KEEP LEGACY（frontend が参照中。dataset 契約なし）",
    "UNKNOWN_CONTRACT": "UNKNOWN CONTRACT（使用中だが対応 dataset なし）",
}


def retired_tile_section(view: drr.RuntimeView, catalog: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """退役済み tile（disposition=RETIRED）。現役一覧とは分けて表示する。current / mirror に残っていれば WARNING。"""
    out = []
    for rel, d in sorted(load_tile_dispositions().items()):
        if d["disposition"] != "RETIRED":
            continue
        stem = Path(rel).stem
        in_current = bool(view.ok and rel in view.files)
        in_mirror = (view.root / rel).is_file() if view.ok else False
        served = None if catalog is None else stem in catalog
        clean = not in_current and not in_mirror and served is not True
        out.append({"rel_path": rel, "tileset_id": stem, "replacement": d.get("replacement"), "reason": d.get("reason"),
                    "retired_at": d.get("retired_at"), "backup": d.get("backup"),
                    "node_backups": d.get("node_backups") or [], "in_current": in_current,
                    "in_mirror": in_mirror, "martin_registered": UNOBSERVED if catalog is None else (OK if served else "N/A"),
                    "status": OK if clean else WARNING,
                    "label": "RETIRED" if clean else "RETIRED（current / mirror / Martin に残存）"})
    return out


def _tile_dispositions_path() -> Path:
    from app.services.dataset_definition_service import _DEFINITIONS_PATH
    return Path(_DEFINITIONS_PATH).parent / "tile_dispositions.json"


def load_tile_dispositions() -> Dict[str, Dict[str, Any]]:
    try:
        items = json.loads(_tile_dispositions_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {i["rel_path"]: i for i in items if i.get("disposition") in TILE_DISPOSITIONS}


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


def _raw_identity(defn: DatasetDefinition, state: Optional[DatasetState]) -> Optional[Dict[str, Any]]:
    """この node の raw を原本名だけで registry の source identity と照合する（hash しない・情報表示）。
    bundle（<dataset_id>_bundle_*.zip）は zip 内の原本名、それ以外は raw の file 名を原本名とみなす。
    sha256 を見ないので一致しても SOURCE_READABLE 止まり（EXPECTED_SOURCE_MATCH にはしない）。"""
    from app.services import source_group
    from app.services import source_identity as si
    raw = state.current_raw_path if state else None
    if not raw or not Path(raw).is_file() or not os.access(raw, os.R_OK):
        return None
    path = Path(raw)
    names = [path.name]
    if path.name.startswith(f"{defn.dataset_id}_bundle_"):
        try:
            names = [Path(n).name for n in source_group.list_zip_members(path)]
        except Exception:  # noqa: BLE001 — 読めない bundle は照合しない
            return None
    res = si.verify(defn, [{"name": n, "sha256": None} for n in names])
    return {"status": res.status, "reasons": res.reasons, "names": names, "hashed": False}


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
    # ACQUISITION-SOURCE-CONTRACT（2026-10-12）: 記録に保存された validity をそのまま信用せず、記録の原本
    # （原本名・sha256 の事実）を registry の source identity とその場で照合する。runtime node でも build node の
    # record が持つ原本の事実で照合する（上位の runtime VERIFIED で source の未確認を隠さない）。
    from app.services import source_identity as si
    from app.services import provenance_validity as pv
    if active is not None:
        identity = si.verify(defn, active.source_files)
    elif rt_source is not None:
        identity = si.verify(defn, rt_source.get("source_files") or [])
    else:
        identity = None
    if identity is not None and validity != AcquisitionValidity.provenance_mismatch.value:
        if identity.status == si.SOURCE_MISMATCH:
            validity = AcquisitionValidity.provenance_mismatch.value
            validity_reason = "source files do not match the expected source: " + "; ".join(identity.reasons)
            validity_flags = validity_flags + [pv.SOURCE_MISMATCH]
        elif identity.status != si.EXPECTED_SOURCE_MATCH and validity == AcquisitionValidity.valid.value:
            validity = AcquisitionValidity.unknown.value
            validity_reason = "source identity is not verified: " + "; ".join(identity.reasons)
            validity_flags = validity_flags + [pv.IDENTITY_UNVERIFIED if identity.status == si.SOURCE_READABLE
                                               else pv.SOURCE_UNKNOWN]
    raw_cache = _raw_cache_status(state, active, rt_record)
    raw_cache["identity"] = _raw_identity(defn, state)
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
        "superseded_canonicals": list(getattr(defn, "superseded_canonicals", None) or []),
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
        # 採用中の source（取得履歴 / 検証済み runtime record）の原本と registry の source identity の照合結果
        "source_identity": identity.to_dict() if identity is not None else {
            "status": si.SOURCE_UNKNOWN, "reasons": ["採用中の取得履歴・runtime record が無い"],
            "basis": defn.expected_source_sha256_basis, "validator_version": si.VALIDATOR_VERSION},
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
    if (res.reason or "").startswith(drr.SUPERSEDED_REASON):
        sec["status"] = ERROR  # 置き換え済みの旧 canonical を runtime / 反映元として扱わない
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
    if res.publish_mode not in ("atomic", "registry") or not res.artifact_present or not view.ok:
        return {"status": "N/A", "component_status": NOT_APPLICABLE, "reasons": [], "record": None}
    out = rp.verify_runtime(view, defn.dataset_id, res.runtime_rel, view_feature_counts(view))
    rec = out.get("record")
    if out["status"] == rp.VERIFIED and rec and res.publish_mode == "registry":
        # registry 型（tsunami）は validated canonical をそのまま runtime に置く契約: record の canonical と
        # runtime artifact は同一 sha256 でなければならず、置き換え済みの旧 canonical であってはならない。
        canon = (rec.get("canonical") or {}).get("sha256")
        ok = canon is not None and canon == rec["runtime_artifact"]["sha256"]
        out["checks"].append({"check": "canonical.sha256 == runtime_artifact.sha256 (validated copy)", "ok": ok,
                              "canonical": canon, "runtime": rec["runtime_artifact"]["sha256"]})
        old = drr.superseded_shas(defn)
        out["checks"].append({"check": "canonical not superseded", "ok": canon not in old, "record": canon})
        if not ok or canon in old:
            out["status"] = rp.MISMATCH
            out["reasons"].append("record の canonical と runtime artifact の関係が契約（validated copy・現行 canonical）と一致しない")
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
        "tile": {"status": tile["status"], "reason": tile.get("reason"), "label": tile.get("label")},
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
            "labels": integrity_labels(acq, rt_prov, components, defn),
        },
    }


# 判定（overall / component status）とは別に、WARNING の中身を区別して示すラベル（DATA-OPS-WARNING-INVENTORY、
# 2026-10-12）。「情報が無い」（node 差・観測経路）と「異常」（不一致）を分けて表示する。判定は変えない。
LABEL_SEVERITY = {
    "SOURCE_PROVENANCE_MISSING": WARNING, "ACQUISITION_HISTORY_MISSING": WARNING,
    "PROVENANCE_SUSPECT": WARNING, "PROVENANCE_UNKNOWN": WARNING, "PROVENANCE_MISMATCH": ERROR,
    "RUNTIME_PROVENANCE_UNKNOWN": WARNING, "RUNTIME_PROVENANCE_MISMATCH": ERROR,
    "ACQUISITION_NOT_PRESENT_ON_THIS_NODE": "INFO", "OBSERVABILITY_LIMITED": "INFO",
    "LEGACY_HISTORY": "INFO", "TILE_NOT_IN_RUNTIME_RECORD": "INFO",
    # ACQUISITION-SOURCE-CONTRACT: registry の source identity との照合（判定は acquisition_section の validity）
    "SOURCE_IDENTITY_MISMATCH": ERROR, "SOURCE_IDENTITY_UNVERIFIED": WARNING,
    # この node に現在の source ではない旧 raw が在る（runtime の provenance ではない・情報表示）
    "LEGACY_SOURCE_PRESENT": "INFO",
    # 派生 dataset の照合（derived_section）
    "DERIVED_INPUT_MISMATCH": ERROR, "DERIVED_OUTPUT_MISMATCH": ERROR,
    "DERIVED_INPUT_UNVERIFIED": WARNING, "DERIVED_OUTPUT_UNVERIFIED": WARNING, "UPSTREAM_SOURCE_UNVERIFIED": WARNING,
    "DERIVED_FROM_VERIFIED": "INFO",
    # atomic version 外の artifact（artifact_section）
    "ARTIFACT_VERIFIED": "INFO", "ARTIFACT_UNVERIFIED": WARNING, "ARTIFACT_MISMATCH": ERROR,
    "ARTIFACT_SUPERSEDED_IN_USE": ERROR,
}


def integrity_labels(acq: Dict[str, Any], rt_prov: Dict[str, Any], components: Dict[str, Any],
                     defn: DatasetDefinition) -> List[Dict[str, str]]:
    from app.services import runtime_provenance as rp
    labels = []
    missing = " ".join(acq.get("provenance_missing") or [])
    if "source_provider" in missing or "source_dataset_name" in missing:
        labels.append("SOURCE_PROVENANCE_MISSING")
    if "acquisition history" in missing:
        labels.append("ACQUISITION_HISTORY_MISSING")
    if acq.get("acquisition_history") == "NOT PRESENT ON THIS NODE":
        labels.append("ACQUISITION_NOT_PRESENT_ON_THIS_NODE")
    validity = acq.get("validity")
    flags = acq.get("validity_flags") or []
    if validity == "provenance_mismatch":
        labels.append("SOURCE_IDENTITY_MISMATCH" if "SOURCE_MISMATCH" in flags else "PROVENANCE_MISMATCH")
    elif validity == "provenance_suspect":
        labels.append("PROVENANCE_SUSPECT")
    elif validity == "unknown" and "IDENTITY_UNVERIFIED" in flags:
        labels.append("SOURCE_IDENTITY_UNVERIFIED")
    elif validity == "unknown" and "acquisition history" not in missing:
        labels.append("PROVENANCE_UNKNOWN")
    if (acq.get("raw_cache") or {}).get("status") == "STALE":
        labels.append("LEGACY_SOURCE_PRESENT")
    if rt_prov.get("status") in (rp.MISMATCH, rp.INVALID):
        labels.append("RUNTIME_PROVENANCE_MISMATCH")
    elif rt_prov.get("status") == rp.ABSENT:
        labels.append("RUNTIME_PROVENANCE_UNKNOWN")
    if (rt_prov.get("record") or {}).get("tile_note"):
        labels.append("TILE_NOT_IN_RUNTIME_RECORD")
    if any(c["status"] == UNOBSERVED for c in components.values()):
        labels.append("OBSERVABILITY_LIMITED")
    if getattr(defn, "superseded_canonicals", None):
        labels.append("LEGACY_HISTORY")
    return [{"label": l, "severity": LABEL_SEVERITY[l]} for l in labels]


def unregistered_section(view: drr.RuntimeView, expected: "set[str]", props: Dict[str, str]) -> List[Dict[str, Any]]:
    fcs = view_feature_counts(view)
    out = []
    for u in drr.unregistered_runtime_artifacts(view, expected):
        lc = loader_contract(u["rel_path"], props)
        out.append({**u, "feature_count": fcs.get(u["rel_path"]), "loader_target": lc["loader_target"],
                    "loader_reason": lc["reason"], "in_use": lc["loader_target"],
                    "provenance": UNKNOWN, "label": "UNREGISTERED RUNTIME SOURCE"})
    return out


# ── 派生 dataset（DERIVED-DATASET-CONTRACT、2026-10-12）─────────────────────────────
# 外部の原本ではなく registry の他 dataset の artifact から生成した dataset（definition.derived_from）は、
# 「取得元組織・取得履歴」の代わりに次を照合する: 入力 artifact の sha256 が宣言どおりか / 上流 dataset の source が
# OK か / 生成器の出力 sha256 が現在の canonical と一致するか。上流が未確認なら派生側も WARNING のまま（隠さない）。
DERIVED_VERIFIED, DERIVED_MISMATCH, DERIVED_UNVERIFIED = "VERIFIED", "MISMATCH", "UNVERIFIED"


def _artifact_path(defn: DatasetDefinition, state: Optional[DatasetState], artifact: str) -> Optional[Path]:
    """上流 dataset の artifact（validated / raw / runtime）の file。runtime node（validated を置かない）では
    flat runtime（definition.runtime_path、version 外）の同名 file を使う（同一性は sha256 で照合する）。"""
    from app.services import runtime_version_access as rva
    cands: List[Path] = []
    if state and artifact == "validated" and state.current_validated_path:
        cands.append(Path(state.current_validated_path))
    if state and artifact == "raw" and state.current_raw_path:
        cands.append(Path(state.current_raw_path))
    name = cands[0].name if cands else (state.current_file_name if state else None)
    if defn.runtime_path and defn.runtime_path.startswith("data_runtime/"):
        rdir = rva.DATA_RUNTIME_ROOT / defn.runtime_path[len("data_runtime/"):]
        if name:
            cands.append(rdir / name)
        elif rdir.is_dir():
            # 置き換えで残した旧 artifact（*.superseded-<sha12>、deploy_dem_runtime.sh）と staging は対象外
            files = [f for f in rdir.iterdir() if f.is_file() and not f.name.startswith(".")
                     and ".superseded-" not in f.name and ".staging-" not in f.name]
            if len(files) == 1:
                cands.append(files[0])
    return next((c for c in cands if c.is_file()), None)


def derived_section(defn: DatasetDefinition, state: Optional[DatasetState], rows_by_id: Dict[str, Dict[str, Any]],
                    defs_by_id: Dict[str, DatasetDefinition], ss, allow_hash: bool) -> Dict[str, Any]:
    cache = drr.get_source_sha_cache()
    inputs = []
    for inp in defn.derived_from:
        up = defs_by_id.get(inp.dataset_id)
        up_state = ss.init_from_definition(up) if up is not None else None
        path = _artifact_path(up, up_state, inp.artifact) if up is not None else None
        actual = cache.get(path, allow_hash) if path else None
        dep = DERIVED_VERIFIED if actual == inp.sha256 else DERIVED_MISMATCH if actual else DERIVED_UNVERIFIED
        up_row = rows_by_id.get(inp.dataset_id)
        up_source = ((up_row or {}).get("integrity", {}).get("components", {}).get("source", {}) or {}).get("status", UNKNOWN)
        inputs.append({"dataset_id": inp.dataset_id, "artifact": inp.artifact, "path": str(path) if path else None,
                       "expected_sha256": inp.sha256, "actual_sha256": actual, "dependency": dep,
                       "upstream_source_status": up_source if up is not None else UNKNOWN,
                       "upstream_defined": up is not None})
    gen = dict(defn.generator or {})
    out_expected = gen.get("output_sha256")
    out_path = Path(state.current_validated_path) if state and state.current_validated_path else None
    out_actual = cache.get(out_path, allow_hash) if out_path and out_path.is_file() else None
    output = (DERIVED_VERIFIED if out_expected and out_actual == out_expected else
              DERIVED_MISMATCH if out_expected and out_actual else DERIVED_UNVERIFIED)
    labels, reasons = [], []
    if any(i["dependency"] == DERIVED_MISMATCH for i in inputs):
        labels.append("DERIVED_INPUT_MISMATCH")
        reasons.append("派生元 artifact の sha256 が宣言と異なる")
    if any(i["dependency"] == DERIVED_UNVERIFIED for i in inputs):
        labels.append("DERIVED_INPUT_UNVERIFIED")
        reasons.append("派生元 artifact の sha256 を確認できない")
    if any(i["upstream_source_status"] != OK for i in inputs):
        labels.append("UPSTREAM_SOURCE_UNVERIFIED")
        reasons.append("派生元 dataset の source が未確認: " + ", ".join(
            f"{i['dataset_id']}={i['upstream_source_status']}" for i in inputs if i["upstream_source_status"] != OK))
    if output == DERIVED_MISMATCH:
        labels.append("DERIVED_OUTPUT_MISMATCH")
        reasons.append("生成器の出力 sha256 が現在の canonical と異なる")
    elif output == DERIVED_UNVERIFIED:
        labels.append("DERIVED_OUTPUT_UNVERIFIED")
        reasons.append("生成器の出力 sha256 を確認できない")
    if not labels:
        labels.append("DERIVED_FROM_VERIFIED")
    status = ERROR if any(LABEL_SEVERITY[l] == ERROR for l in labels) else (
        WARNING if any(LABEL_SEVERITY[l] == WARNING for l in labels) else OK)
    return {"inputs": inputs, "generator": gen, "output": {"expected_sha256": out_expected, "actual_sha256": out_actual,
            "status": output}, "labels": labels, "reasons": reasons, "status": status}


def artifact_section(defn: DatasetDefinition, state: Optional[DatasetState], allow_hash: bool) -> Dict[str, Any]:
    """atomic version 外の artifact（definition.artifact_sha256）を照合する。使っている file（build node は validated、
    runtime node は flat runtime）の sha256 が登録値なら VERIFIED、置き換え済みの旧 artifact なら SUPERSEDED（ERROR）。"""
    path = _artifact_path(defn, state, "validated")
    actual = drr.get_source_sha_cache().get(path, allow_hash) if path else None
    superseded = {s.get("sha256"): s.get("reason") for s in defn.superseded_artifacts or []}
    if actual and actual == defn.artifact_sha256:
        status, label, comp = DERIVED_VERIFIED, "ARTIFACT_VERIFIED", OK
    elif actual and actual in superseded:
        status, label, comp = "SUPERSEDED", "ARTIFACT_SUPERSEDED_IN_USE", ERROR
    elif actual:
        status, label, comp = DERIVED_MISMATCH, "ARTIFACT_MISMATCH", ERROR
    else:
        status, label, comp = DERIVED_UNVERIFIED, "ARTIFACT_UNVERIFIED", WARNING
    return {"path": str(path) if path else None, "expected_sha256": defn.artifact_sha256, "actual_sha256": actual,
            "layout": defn.artifact_layout, "status": status, "label": label, "component_status": comp,
            "superseded_reason": superseded.get(actual) if actual in superseded else None}


def _apply_artifact(row: Dict[str, Any], section: Dict[str, Any]) -> None:
    row["artifact"] = section
    row["integrity"]["components"]["artifact"] = {"status": section["component_status"], "reason": (
        f"{section['status']}: {section['superseded_reason']}" if section["superseded_reason"] else section["status"])}
    row["integrity"]["labels"].append({"label": section["label"], "severity": LABEL_SEVERITY[section["label"]]})
    row["integrity"]["overall"] = _overall(row["integrity"]["components"])


def _apply_derived(row: Dict[str, Any], defn: DatasetDefinition, section: Dict[str, Any]) -> None:
    """派生 dataset の source 判定を、外部 source の要件（取得元組織・取得履歴）から派生契約の照合へ置き換える。"""
    acq = row["acquisition"]
    acq["derived"] = section
    acq["status"] = section["status"]
    acq["provenance_missing"] = [m for m in acq.get("provenance_missing") or []
                                 if "source_provider" not in m and "source_dataset_name" not in m
                                 and "acquisition history" not in m]
    comps = row["integrity"]["components"]
    comps["source"] = {"status": section["status"], "reason": "; ".join(section["reasons"]) or None}
    external = {"SOURCE_PROVENANCE_MISSING", "ACQUISITION_HISTORY_MISSING", "PROVENANCE_UNKNOWN",
                "SOURCE_IDENTITY_UNVERIFIED"}
    labels = [l for l in row["integrity"]["labels"] if l["label"] not in external]
    labels += [{"label": l, "severity": LABEL_SEVERITY[l]} for l in section["labels"]]
    row["integrity"]["labels"] = labels
    row["integrity"]["overall"] = _overall(comps)


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
    # 派生 dataset は上流 dataset の判定を使う（単一 dataset 表示でも上流の行を作って照合する）
    rows_by_id = {r["dataset_id"]: r for r in rows}
    defs_by_id = {d.dataset_id: d for d in ds.list_all()}
    for row in rows:
        defn = defs_by_id.get(row["dataset_id"])
        if defn is not None and defn.artifact_sha256:
            _apply_artifact(row, artifact_section(defn, ss.init_from_definition(defn), allow_hash))
    for row in rows:
        defn = defs_by_id.get(row["dataset_id"])
        if defn is None or not defn.derived_from:
            continue
        for inp in defn.derived_from:
            up = defs_by_id.get(inp.dataset_id)
            if inp.dataset_id not in rows_by_id and up is not None:
                try:
                    rows_by_id[inp.dataset_id] = build_dataset(up, ss.init_from_definition(up), view, allow_hash=allow_hash,
                                                               allow_heavy=False, props=props, catalog=catalog, store=store)
                except Exception as exc:  # noqa: BLE001 — 上流を評価できなければ UNKNOWN（未確認）として扱う
                    logger.warning("data-ops upstream build failed: %s: %s", inp.dataset_id, exc)
        _apply_derived(row, defn, derived_section(defn, ss.init_from_definition(defn), rows_by_id, defs_by_id, ss, allow_hash))
    return {
        "current_version": view.version_id,
        "runtime_error": view.error,
        "published_at": view.published_at.isoformat() if view.published_at else None,
        "martin_catalog": "observed" if catalog is not None else UNOBSERVED,
        "datasets": rows,
        "errors": errors,
        "unregistered_runtime_artifacts": unregistered_section(view, expected, props),
        "legacy_tiles": legacy_tile_section(view, ds.list_all(), catalog),
        "retired_tiles": retired_tile_section(view, catalog),
    }
