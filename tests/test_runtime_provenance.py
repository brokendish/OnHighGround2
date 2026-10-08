"""
runtime provenance（build node → runtime node）。

runtime node（VPS）には raw / acquisition history が無い（同期しない）。current version に同梱された
provenance/<dataset_id>.json（_manifest.json に sha256 が載る）を manifest と照合して、
「runtime は正しいのに UNKNOWN」を解消する。推測で VALID にしない。

  - record が manifest と一致 → RUNTIME VERIFIED、source は record の validity（build node で検証）
  - 取得履歴なし / 旧 raw cache（STALE）でも runtime は VALID
  - routing sha・feature count・tile・canonical 連鎖の不一致 → MISMATCH（ERROR）
  - record の無い旧 version → LEGACY_RUNTIME_PROVENANCE（UNKNOWN）
  - rollback（current 切替）で表示も旧 version の record に戻る
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetState  # noqa: E402
from app.services import acquisition_history as ah  # noqa: E402
from app.services import build_provenance as bp  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from app.services import runtime_provenance as rp  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402
from app.services.flood_routing_contract import BUILDER_NAME, CONTRACT_VERSION  # noqa: E402

PROPS = {"hazard.flood.enabled": "true"}
OFFICIAL = ["A31a-25_14_10_GML.zip", "A31a-25_14_20_GML.zip"] + [
    f"A31b-25_{c}_{m}_GML.zip" for m in ("5238", "5239", "5338", "5339") for c in ("10", "20")]
ROUTING_REL = "backend/hazard/flood/kanagawa/kanagawa-river-001.routing.geojson"
TILE_REL = "frontend/tiles/kanagawa/flood/kanagawa_river_001.mbtiles"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class World:
    """build node（data_lake・取得履歴あり）と runtime node（current のみ）を tmp で再現する。"""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.lake = tmp / "data_lake"
        self.rt = tmp / "runtime"
        self.defn = get_definition_service().get("KANAGAWA-RIVER-001")
        self.canonical = self.lake / "validated/kanagawa/flood/kanagawa-river-001.geojson"
        self.canonical.parent.mkdir(parents=True)
        self.canonical.write_bytes(b"CANONICAL-2025")
        der = self.lake / "derived/kanagawa/flood"
        der.mkdir(parents=True)
        (der / "kanagawa-river-001.routing.geojson").write_bytes(b"ROUTING-2025")
        (der / "kanagawa-river-001.routing.meta.json").write_text(json.dumps({
            "contract": CONTRACT_VERSION, "dataset_id": "KANAGAWA-RIVER-001",
            "source_canonical_path": str(self.canonical), "source_canonical_sha256": _sha(b"CANONICAL-2025"),
            "routing_artifact_sha256": _sha(b"ROUTING-2025"), "builder_name": BUILDER_NAME, "builder_version": "1",
            "tau": 0.85, "min_split_size": 0, "feature_count": 3, "source_feature_count": 4,
            "generated_at": "2026-10-07T00:00:00Z"}))
        tile = self.lake / "tiles/kanagawa/flood/kanagawa_river_001.mbtiles"
        tile.parent.mkdir(parents=True)
        import sqlite3
        conn = sqlite3.connect(tile)
        conn.execute("CREATE TABLE metadata (name text, value text)")
        conn.execute("CREATE TABLE tiles (zoom_level int, tile_column int, tile_row int, tile_data blob)")
        conn.executemany("INSERT INTO metadata VALUES (?, ?)", [("minzoom", "5"), ("maxzoom", "14"),
                         ("json", json.dumps({"vector_layers": [{"id": "flood"}]}))])
        conn.commit()
        conn.close()
        self.tile_bytes = tile.read_bytes()
        self.store = ah.AcquisitionStore(tmp / "acq")
        self.cache = drr.SourceShaCache(tmp / "cache.json")

    def state(self, raw=None):
        return DatasetState(dataset_id="KANAGAWA-RIVER-001", storage_status="stored", normalize_status="success",
                            validation_status="pass", current_validated_path=str(self.canonical),
                            current_raw_path=str(raw) if raw else None)

    def acquire(self, validity="valid"):
        self.store.add(ah.AcquisitionRecord(
            dataset_id="KANAGAWA-RIVER-001", acquisition_method="upload", active=True, status="processed",
            validity=validity, raw_path="/data_lake/raw/kanagawa/flood/KANAGAWA-RIVER-001_bundle_a2d47993.zip",
            bundle=ah.SourceFile(name="KANAGAWA-RIVER-001_bundle_a2d47993.zip"),
            source_files=[ah.SourceFile(name=n, size=1, sha256="0" * 64) for n in OFFICIAL]))

    def build_record(self):
        return bp.generate(self.defn, self.state(), store=self.store, cache=self.cache, data_lake=self.lake)

    def publish(self, vid, routing=b"ROUTING-2025", tile=None, record=None, fc=3, activate=True):
        tile = self.tile_bytes if tile is None else tile
        v = self.rt / "versions" / vid
        files = {ROUTING_REL: routing, TILE_REL: tile}
        if record is not None:
            files[rp.runtime_rel("KANAGAWA-RIVER-001")] = json.dumps(record).encode()
        for rel, data in files.items():
            (v / rel).parent.mkdir(parents=True, exist_ok=True)
            (v / rel).write_bytes(data)
        (self.rt / TILE_REL).parent.mkdir(parents=True, exist_ok=True)  # Martin 配信 mirror
        (self.rt / TILE_REL).write_bytes(tile)
        (v / "_manifest.json").write_text(json.dumps({"files": {r: _sha(d) for r, d in files.items()},
                                                      "feature_counts": {ROUTING_REL: fc}}))
        if activate:
            self.switch(vid)
        return v

    def switch(self, vid):
        link, tmp = self.rt / "current", self.rt / "current.tmp"
        os.symlink(f"versions/{vid}", tmp)
        os.replace(tmp, link)

    def row(self, state=None, store=None):
        drr._view_cache.clear()
        dos._fc_cache.clear()
        view = drr.load_runtime_view(self.rt)
        return dos.build_dataset(self.defn, state or self.state(), view, allow_hash=True, allow_heavy=False,
                                 props=PROPS, store=store or ah.AcquisitionStore(self.tmp / "empty-acq"))


@pytest.fixture
def w(tmp_path, monkeypatch):
    world = World(tmp_path)
    monkeypatch.setattr(drr, "_default_cache", world.cache)
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "tile.json"))
    return world


def _runtime_node_record(w):
    w.acquire()
    return w.build_record()


def test_record_built_from_build_node_facts(w):
    rec = _runtime_node_record(w)
    assert rec["schema"] == rp.SCHEMA and rec["dataset_id"] == "KANAGAWA-RIVER-001"
    assert rec["runtime_artifact"] == {"rel": ROUTING_REL, "sha256": _sha(b"ROUTING-2025"), "feature_count": 3}
    assert rec["canonical"] == {"sha256": _sha(b"CANONICAL-2025"), "feature_count": 4}
    assert rec["tile"]["rel"] == TILE_REL and rec["tile"]["sha256"] == _sha(w.tile_bytes)
    assert rec["source"]["validity"] == "valid" and len(rec["source"]["source_files"]) == 10


def test_01_02_runtime_verified_without_acquisition_history(w):
    """runtime node: 取得履歴なしでも record が manifest と一致すれば RUNTIME VERIFIED / source VALID。"""
    w.publish("V2", record=_runtime_node_record(w))
    r = w.row()  # 空の取得履歴（runtime node）
    assert r["runtime_provenance"]["status"] == rp.VERIFIED
    acq = r["acquisition"]
    assert acq["active"] is None and acq["acquisition_history"] == "NOT PRESENT ON THIS NODE"
    assert acq["validity"] == "valid" and acq["validity_source"] == "runtime_provenance" and acq["status"] == dos.OK
    assert "採用中の取得履歴（acquisition history）" not in acq["provenance_missing"]
    comps = r["integrity"]["components"]
    assert comps["runtime_provenance"]["status"] == dos.OK and comps["source"]["status"] == dos.OK
    assert r["integrity"]["overall"] == dos.OK


def test_03_stale_raw_cache_does_not_make_runtime_mismatch(w):
    stale = w.tmp / "raw" / "KANAGAWA-RIVER-001_bundle_eu2fb8ee.zip"
    stale.parent.mkdir()
    with zipfile.ZipFile(stale, "w") as zf:
        for n in ("A31a-25_13_10_GML.zip", "A31a-25_13_20_GML.zip"):
            zf.writestr(n, n)
    w.publish("V2", record=_runtime_node_record(w))
    r = w.row(state=w.state(raw=stale))
    acq = r["acquisition"]
    assert acq["validity"] == "valid" and acq["status"] == dos.OK
    assert acq["raw_cache"]["status"] == "STALE" and "region code 13" in acq["raw_cache"]["region_check"]
    assert r["integrity"]["overall"] == dos.OK


def test_03b_unreadable_raw_is_reported_not_judged(w):
    raw = w.tmp / "raw" / "x.zip"
    raw.parent.mkdir()
    raw.write_bytes(b"x")
    raw.chmod(0)
    try:
        w.publish("V2", record=_runtime_node_record(w))
        if os.access(raw, os.R_OK):
            pytest.skip("root 権限では chmod 0 でも読める")
        assert w.row(state=w.state(raw=raw))["acquisition"]["raw_cache"]["status"] == "UNREADABLE"
    finally:
        raw.chmod(0o644)


@pytest.mark.parametrize("field,mutate", [
    ("runtime_artifact.sha256", lambda r: r["runtime_artifact"].update(sha256="0" * 64)),
    ("runtime_artifact.feature_count", lambda r: r["runtime_artifact"].update(feature_count=999)),
    ("tile.sha256", lambda r: r["tile"].update(sha256="1" * 64)),
])
def test_04_routing_or_tile_mismatch_is_error(w, field, mutate):
    rec = _runtime_node_record(w)
    mutate(rec)
    w.publish("V2", record=rec)
    r = w.row()
    rpv = r["runtime_provenance"]
    assert rpv["status"] == rp.MISMATCH and any(field in x for x in rpv["reasons"])
    assert r["integrity"]["components"]["runtime_provenance"]["status"] == dos.ERROR
    assert r["integrity"]["overall"] == dos.ERROR
    # 検証できない record の source は採用しない
    assert r["acquisition"]["validity_source"] is None


def test_05_canonical_chain_mismatch_is_error(w):
    rec = _runtime_node_record(w)
    rec["canonical"]["sha256"] = "2" * 64  # routing meta の source_canonical_sha256 と食い違う record
    w.publish("V2", record=rec)
    r = w.row()
    assert r["runtime_provenance"]["status"] == rp.MISMATCH
    assert any("canonical" in x for x in r["runtime_provenance"]["reasons"])


def test_05b_tampered_record_is_invalid(w):
    v = w.publish("V2", record=_runtime_node_record(w))
    (v / rp.runtime_rel("KANAGAWA-RIVER-001")).write_text("{}")  # manifest の sha と食い違う
    r = w.row()
    assert r["runtime_provenance"]["status"] == rp.INVALID and r["integrity"]["overall"] == dos.ERROR


def test_06_09_no_record_is_legacy_unknown_not_valid(w):
    w.publish("V1")  # 旧 version（record なし）
    r = w.row()
    assert r["runtime_provenance"]["status"] == rp.ABSENT
    assert r["integrity"]["components"]["runtime_provenance"]["status"] == dos.UNKNOWN
    acq = r["acquisition"]
    assert acq["validity"] == "unknown" and acq["acquisition_history"] == "ABSENT"
    assert r["integrity"]["overall"] != dos.OK


def test_07_rollback_restores_old_provenance(w):
    w.acquire()
    old = w.build_record()
    old["source"]["validity"], old["source"]["validity_flags"] = "provenance_mismatch", ["REGION_MISMATCH"]
    w.publish("V1", record=old)
    w.publish("V2", record=w.build_record())
    assert w.row()["acquisition"]["validity"] == "valid"
    w.switch("V1")  # rollback（current を旧 version へ）
    r = w.row()
    assert r["runtime_provenance"]["version"] == "V1"
    assert r["acquisition"]["validity"] == "provenance_mismatch" and r["integrity"]["overall"] == dos.ERROR


def test_08_build_node_keeps_acquisition_based_detail(w):
    w.acquire()
    w.publish("V2", record=w.build_record())
    r = w.row(store=w.store)
    acq = r["acquisition"]
    assert acq["acquisition_history"] == "PRESENT" and acq["validity_source"] == "acquisition_history"
    assert len(acq["active"]["source_files"]) == 10 and r["runtime_provenance"]["status"] == rp.VERIFIED


def test_10_kanagawa_current_shape(w):
    """KANAGAWA current（routing c1c67e72… / 1,311,824）と同形の record で VERIFIED。"""
    rec = _runtime_node_record(w)
    assert rec["runtime_artifact"]["rel"] == drr.expected_runtime_rel(w.defn, w.state())
    w.publish("20261008T115503Z-ba2bb34c", record=rec)
    r = w.row()
    assert r["runtime_provenance"]["version"] == "20261008T115503Z-ba2bb34c"
    assert r["runtime"]["runtime_status"] == "published" and r["runtime_provenance"]["status"] == rp.VERIFIED


def test_11_tokyo_river_regression():
    t = get_definition_service().get("TOKYO-RIVER-001")
    assert t.required_source_count == 4 and t.coverage_allow_empty_meshes == []
    assert rp.tile_rel(t.dataset_id, t.region, t.layer_type) == "frontend/tiles/tokyo/flood/tokyo_river_001.mbtiles"


def test_stage_script_places_records_into_staging(w, tmp_path, monkeypatch):
    """publish wrapper の hook: data_lake/provenance → staging/provenance/<id>.json（形式不正は配置しない）。"""
    rec = _runtime_node_record(w)
    rp.write_record(rp.build_path(w.lake, "kanagawa", "flood", "KANAGAWA-RIVER-001"), rec)
    rp.write_record(rp.build_path(w.lake, "tokyo", "flood", "TOKYO-RIVER-001"), {"schema": "bad"})
    staging = tmp_path / "staging"
    staging.mkdir()
    mapping = Mock()
    mapping.list_all.return_value = [
        {"layer_type": "flood", "region": "kanagawa", "dataset_id": "KANAGAWA-RIVER-001"},
        {"layer_type": "flood", "region": "tokyo", "dataset_id": "TOKYO-RIVER-001"},
        {"layer_type": "shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"},
    ]
    import importlib.util
    spec = importlib.util.spec_from_file_location("stage", ROOT / "scripts/publish/stage_runtime_provenance.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["x", "--staging", str(staging), "--region", "kanagawa", "--region", "tokyo",
                                      "--data-lake", str(w.lake)])
    with patch("app.services.active_mapping_service.get_active_mapping_service", return_value=mapping):
        assert mod.main() == 0
    staged = json.loads((staging / "provenance/KANAGAWA-RIVER-001.json").read_text())
    method = staged.pop("publish_verification")
    assert staged == rec and method["method"] in ("canonical_file", "artifact_record")
    assert not (staging / "provenance/TOKYO-RIVER-001.json").exists()


def test_wrapper_hook_before_activation_and_non_fatal():
    sh = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    hook = sh.index("stage_runtime_provenance.py")
    assert sh.index('"${SCRIPT_DIR}/deploy_to_runtime.sh" --region') < hook < sh.index("activate_version.py\" \\")
    block = sh[sh.rindex("\nif ", 0, hook):sh.index("\nfi\n", hook)]
    assert "log_warn" in block and "exit" not in block
    r = subprocess.run(["bash", "-n", str(ROOT / "scripts/publish/deploy_to_runtime_atomic.sh")], capture_output=True)
    assert r.returncode == 0


def test_pipeline_exports_only_on_build_node(w, monkeypatch):
    from app.services import pipeline_service as ps
    from app.models.admin_dataset import Job, JobType
    job, jm = Job(job_id="j", dataset_id="KANAGAWA-RIVER-001", job_type=JobType.deploy), Mock()
    monkeypatch.setattr(ps, "get_acquisition_store", lambda: w.store)
    with patch.object(bp, "export") as export:
        ps._export_build_provenance(job, w.defn, w.state(), jm)  # 取得履歴なし = runtime node
        export.assert_not_called()
        w.acquire()
        ps._export_build_provenance(job, w.defn, w.state(), jm)  # build node
        export.assert_called_once()


def test_provenance_dir_is_gitignored():
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "data_lake/provenance/kanagawa/flood/x.json"])
    assert r.returncode == 0


def test_12_data_ops_is_read_only_for_state(w):
    """Data Ops の provenance 判定は state を保存しない（5 秒ポーリングの書き直し再発防止）。"""
    w.publish("V2", record=_runtime_node_record(w))
    ss = Mock()
    ss.init_from_definition.return_value = w.state()
    ds = Mock()
    ds.list_all.return_value = [w.defn]
    with patch.dict(os.environ, {"OHG2_DATA_RUNTIME_ROOT": str(w.rt)}), \
         patch.object(dos, "martin_catalog_ids", return_value=None), \
         patch.object(dos, "_app_properties", return_value=PROPS):
        drr._view_cache.clear()
        dos.build_console(ds, ss, store=ah.AcquisitionStore(w.tmp / "empty-acq"))
    ss.save.assert_not_called()
