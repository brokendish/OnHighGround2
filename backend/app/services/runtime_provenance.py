"""
runtime_provenance.py — runtime version に同梱する provenance record（build node → runtime node）。

背景: runtime node（VPS）は build（取込・canonical・routing 生成）を行わず、build node（Local）で
検証済みの成果物を受け取って publish するだけ。runtime node には raw / acquisition history が無い
（同期もしない）ため、取得履歴だけで provenance を判定すると「runtime は正しいのに UNKNOWN」になる。

record の流れ:
  1. build node: export_build_provenance.py / 取込 pipeline 完了時に
     data_lake/provenance/<region>/<layer_type>/<dataset_id>.json を書く（取得履歴・canonical・
     runtime artifact・tile の sha256 を記録）
  2. 成果物と一緒に runtime node へ転送（数 KB）
  3. publish（deploy_to_runtime_atomic.sh → stage_runtime_provenance.py）が staging の
     provenance/<dataset_id>.json へ配置 → activate で _manifest.json に sha256 が載る
  4. Data Ops は current → _manifest.json → provenance/<dataset_id>.json の連鎖で読み、
     record の値を manifest（runtime の正）と照合する（rollback すれば旧 version の record に戻る）

record が無い旧 version は LEGACY（UNKNOWN）。推測で VALID にしない。
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "ohg2.runtime_provenance/v1"
RUNTIME_DIR = "provenance"

VERIFIED = "VERIFIED"
MISMATCH = "MISMATCH"
ABSENT = "LEGACY_RUNTIME_PROVENANCE"   # record の無い version（新形式導入前）
INVALID = "INVALID"                    # record が壊れている・manifest に無い


def runtime_rel(dataset_id: str) -> str:
    return f"{RUNTIME_DIR}/{dataset_id}.json"


def build_path(data_lake: Path, region: str, layer_type: str, dataset_id: str) -> Path:
    return Path(data_lake) / "provenance" / region / layer_type / f"{dataset_id}.json"


def tile_rel(dataset_id: str, region: str, layer_type: str) -> str:
    return f"frontend/tiles/{region}/{layer_type}/{dataset_id.lower().replace('-', '_')}.mbtiles"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ── build node ─────────────────────────────────────────────────────────────────

def build_record(defn, state, *, acquisition=None, canonical_sha256: Optional[str],
                 runtime_rel_path: str, runtime_sha256: Optional[str], runtime_feature_count: Optional[int],
                 canonical_feature_count: Optional[int] = None, tile_path: Optional[Path] = None,
                 tile_rel_path: Optional[str] = None) -> Dict[str, Any]:
    """build node で record を組み立てる。取得履歴が無ければ source は None（推測で埋めない）。"""
    source = None
    if acquisition is not None:
        source = {
            "acquisition_id": acquisition.acquisition_id,
            "acquisition_method": acquisition.acquisition_method.value,
            "acquired_at": acquisition.acquired_at.isoformat() if acquisition.acquired_at else None,
            "validity": acquisition.validity.value,
            "validity_reason": acquisition.validity_reason,
            "validity_flags": list(acquisition.validity_flags),
            "source_files": [f.model_dump() for f in acquisition.source_files],
            "bundle": acquisition.bundle.model_dump() if acquisition.bundle else None,
        }
    tile = None
    if tile_path is not None and Path(tile_path).is_file():
        tile = {"rel": tile_rel_path, "sha256": _sha256(Path(tile_path)), "size": Path(tile_path).stat().st_size}
    return {
        "schema": SCHEMA,
        "dataset_id": defn.dataset_id,
        "layer_type": defn.layer_type,
        "region": defn.region,
        "source": source,
        "canonical": {"sha256": canonical_sha256, "feature_count": canonical_feature_count},
        "runtime_artifact": {"rel": runtime_rel_path, "sha256": runtime_sha256, "feature_count": runtime_feature_count},
        "tile": tile,
        "built_at": datetime.now(timezone.utc).isoformat(),
        # container 内では hostname が container ID になるため、OHG2_NODE_NAME があれば優先する
        "build_node": os.environ.get("OHG2_NODE_NAME") or socket.gethostname(),
    }


def write_record(path: Path, record: Dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def validate_record_shape(record: Any, dataset_id: Optional[str] = None) -> List[str]:
    errs = []
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return [f"schema が {SCHEMA} ではない"]
    if dataset_id and record.get("dataset_id") != dataset_id:
        errs.append(f"dataset_id 不一致: {record.get('dataset_id')} != {dataset_id}")
    ra = record.get("runtime_artifact") or {}
    if not ra.get("rel") or not ra.get("sha256"):
        errs.append("runtime_artifact.rel / sha256 が無い")
    return errs


# ── runtime node（Data Ops）──────────────────────────────────────────────────────

def verify_runtime(view, dataset_id: str, expected_rel: Optional[str],
                   feature_counts: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """current version の provenance record を manifest（runtime の正）と照合する。
    view: dataset_runtime_reconcile.RuntimeView（current + manifest files）。"""
    rel = runtime_rel(dataset_id)
    out: Dict[str, Any] = {"status": ABSENT, "rel": rel, "version": view.version_id, "record": None,
                           "checks": [], "reasons": []}
    manifest_sha = view.files.get(rel)
    if manifest_sha is None:
        out["reasons"].append("current version に provenance record が無い（record 導入前の version）")
        return out
    path = view.version_path(rel)
    try:
        raw = path.read_bytes()
        record = json.loads(raw)
    except (OSError, ValueError) as exc:
        out.update(status=INVALID)
        out["reasons"].append(f"record を読めない: {exc}")
        return out
    if hashlib.sha256(raw).hexdigest() != manifest_sha:
        out.update(status=INVALID)
        out["reasons"].append("record の sha256 が manifest と一致しない（改ざん・破損の疑い）")
        return out
    shape = validate_record_shape(record, dataset_id)
    if shape:
        out.update(status=INVALID, record=record)
        out["reasons"].extend(shape)
        return out
    out["record"] = record
    checks = out["checks"]
    ra = record["runtime_artifact"]
    if expected_rel and ra["rel"] != expected_rel:
        checks.append({"check": "runtime_artifact.rel", "ok": False, "expected": expected_rel, "record": ra["rel"]})
    actual = view.files.get(ra["rel"])
    checks.append({"check": "runtime_artifact.sha256", "ok": actual == ra["sha256"], "manifest": actual,
                   "record": ra["sha256"]})
    fc = (feature_counts or {}).get(ra["rel"])
    if ra.get("feature_count") is not None:
        checks.append({"check": "runtime_artifact.feature_count", "ok": fc == ra["feature_count"],
                       "manifest": fc, "record": ra["feature_count"]})
    tile = record.get("tile")
    if tile and tile.get("rel"):
        checks.append({"check": "tile.sha256", "ok": view.files.get(tile["rel"]) == tile.get("sha256"),
                       "manifest": view.files.get(tile["rel"]), "record": tile.get("sha256")})
    failed = [c for c in checks if not c["ok"]]
    if failed:
        out["status"] = MISMATCH
        out["reasons"].extend(f"{c['check']} が runtime と不一致" for c in failed)
    else:
        out["status"] = VERIFIED
    return out
