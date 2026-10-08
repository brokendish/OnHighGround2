"""
Acquisition backfill safety / provenance validity。

active（現在採用中）と validity（provenance の健全性: valid / provenance_mismatch /
provenance_suspect / unknown）を別軸で記録・表示し、不明・不整合を正常扱いしない。
世界は実データの構成を縮約したもの（tmp 上）:
  TOKYO-RIVER-001     A31a-25_13_* + A31b-25_*（東京 13）                  → valid
  KANAGAWA-RIVER-001  A31a-25_13_*（東京原本と同一 bytes、定義は 14）       → provenance_mismatch
  KANAGAWA-SHELTER/EVAC 同一原本 14000_2.zip                                 → provenance_suspect
  TOKYO-DEM-001       raw のみ（job 記録なし = legacy_unknown）              → unknown
  ROAD-DRIVING-KANTO-001 raw なし                                           → no_facts（履歴を作らない）
"""
from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetDefinition, DatasetState  # noqa: E402
from app.services import acquisition_history as ah  # noqa: E402
from app.services import acquisition_migration as am  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from app.services import provenance_validity as pv  # noqa: E402

A31 = ["A31a-25_13_10_GML.zip", "A31a-25_13_20_GML.zip", "A31b-25_10_5339_GML.zip", "A31b-25_20_5339_GML.zip"]
PATTERNS = ["A31a-*_13_10_GML.zip", "A31a-*_13_20_GML.zip", "A31b-*_10_5339_GML.zip", "A31b-*_20_5339_GML.zip"]
REGION_RX = r"^A31a-\d+_(\d{2})_"


def _defn(dataset_id, layer_type, region, **kw):
    base = dict(dataset_id=dataset_id, region=region, category=layer_type or "x", display_name="t", description="t",
                hint_text="t", impact_scope="t", accepted_input_modes=["upload"], accepted_extensions=[".zip"],
                max_browser_upload_mb=200, requires_normalize=False, requires_validation=False, requires_deploy=True,
                requires_osrm_rebuild=False, raw_storage_path=f"data_lake/raw/{region}/{layer_type}",
                runtime_path=f"data_runtime/backend/hazard/{layer_type}", layer_type=layer_type)
    base.update(kw)
    return DatasetDefinition(**base)


DEFNS = [
    _defn("TOKYO-RIVER-001", "flood", "tokyo", source_group_mode="all_required", required_source_count=4,
          source_file_patterns=PATTERNS, expected_source_region_code="13", source_region_code_regex=REGION_RX,
          source_provider="国土交通省 国土数値情報", source_dataset_name="洪水浸水想定区域 A31a/A31b"),
    _defn("KANAGAWA-RIVER-001", "flood", "kanagawa", expected_source_region_code="14", source_region_code_regex=REGION_RX),
    _defn("KANAGAWA-SHELTER-001", "shelter", "kanagawa"),
    _defn("KANAGAWA-EVAC-001", "shelter", "kanagawa"),
    _defn("TOKYO-DEM-001", None, "tokyo"),
    _defn("ROAD-DRIVING-KANTO-001", None, "kanto"),
]


def _zip(path: Path, members: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


@pytest.fixture
def world(tmp_path):
    admin = tmp_path / "admin"
    (admin / "history").mkdir(parents=True)
    (admin / "jobs").mkdir()
    (admin / "state").mkdir()
    raw = tmp_path / "raw"
    a31 = {n: f"bytes-{n}".encode() for n in A31}  # 東京原本（KANAGAWA bundle と同一 bytes）
    files = {
        # zip 内の格納順は昇順でない（保存時に辞書順へ安定化されることを確認する）
        "TOKYO-RIVER-001": _zip(raw / "TOKYO-RIVER-001_bundle_stmxod68.zip", {n: a31[n] for n in reversed(A31)}),
        "KANAGAWA-RIVER-001": _zip(raw / "KANAGAWA-RIVER-001_bundle_t61diorv.zip",
                                   {"A31a-25_13_20_GML.zip": a31["A31a-25_13_20_GML.zip"],
                                    "A31a-25_13_10_GML.zip": a31["A31a-25_13_10_GML.zip"]}),
        "KANAGAWA-SHELTER-001": _zip(raw / "shelter" / "14000_2.zip", {"a.csv": b"shelter"}),
        "KANAGAWA-EVAC-001": _zip(raw / "evac" / "14000_2.zip", {"a.csv": b"shelter"}),
        "TOKYO-DEM-001": _zip(raw / "dem" / "elevation.zip", {"e.tif": b"dem"}),
    }
    for i, (did, path) in enumerate(files.items()):
        (admin / "state" / f"{did}.json").write_text(json.dumps({
            "dataset_id": did, "current_raw_path": str(path), "normalize_status": "success", "validation_status": "pass"}))
        if did == "TOKYO-DEM-001":
            continue  # job / history 記録なし → legacy_unknown
        job = f"job-{i}"
        (admin / "history" / f"{did}.jsonl").write_text(json.dumps({
            "operation_type": "ingest", "result": "success", "source_file_name": path.name, "job_id": job,
            "executed_at": f"2026-10-05T15:{10 + i}:00"}) + "\n")
        (admin / "jobs" / f"{job}.json").write_text(json.dumps({"job_type": "ingest_upload", "created_at": "2026-10-05T15:00:00"}))
    (admin / "state" / "ROAD-DRIVING-KANTO-001.json").write_text(json.dumps({"dataset_id": "ROAD-DRIVING-KANTO-001"}))
    ds = Mock()
    ds.list_all.return_value = DEFNS
    store = ah.AcquisitionStore(tmp_path / "acquisitions")
    return {"admin": admin, "ds": ds, "store": store, "tmp": tmp_path}


def _run(world, ids=None, dry_run=False):
    return {r["dataset_id"]: r for r in am.migrate_all(world["ds"], store=world["store"], dry_run=dry_run,
                                                       dataset_ids=ids, admin_dir=world["admin"])}


# ── 1-3, 9, 11. --dataset 選択・dry-run・no_facts ─────────────────────────────

def test_01_single_dataset_writes_only_that_dataset(world):
    out = _run(world, ["TOKYO-RIVER-001"])
    assert list(out) == ["TOKYO-RIVER-001"] and out["TOKYO-RIVER-001"]["action"] == "migrated"
    store = world["store"]
    assert len(store.list("TOKYO-RIVER-001")) == 1
    for other in ("KANAGAWA-RIVER-001", "KANAGAWA-EVAC-001", "TOKYO-DEM-001"):
        assert store.list(other) == []  # 3. 指定以外を書かない
    assert sorted(p.name for p in store.root.glob("*.json")) == ["TOKYO-RIVER-001.json"]


def test_02_multiple_datasets(world):
    out = _run(world, ["TOKYO-RIVER-001", "KANAGAWA-EVAC-001"])
    assert sorted(out) == ["KANAGAWA-EVAC-001", "TOKYO-RIVER-001"]
    assert sorted(p.name for p in world["store"].root.glob("*.json")) == ["KANAGAWA-EVAC-001.json", "TOKYO-RIVER-001.json"]


def test_11_dry_run_shows_validity_and_writes_nothing(world):
    out = _run(world, dry_run=True)
    assert not world["store"].root.exists() or not list(world["store"].root.glob("*.json"))
    assert out["TOKYO-RIVER-001"]["validity"] == "valid"
    assert out["KANAGAWA-RIVER-001"]["validity"] == "provenance_mismatch"
    assert out["KANAGAWA-RIVER-001"]["validity_reason"]
    assert out["KANAGAWA-EVAC-001"]["validity"] == "provenance_suspect"
    assert out["TOKYO-DEM-001"]["validity"] == "unknown"
    assert out["ROAD-DRIVING-KANTO-001"] == {"dataset_id": "ROAD-DRIVING-KANTO-001", "action": "no_facts"}


def test_09_no_facts_creates_no_history(world):
    out = _run(world)
    assert out["ROAD-DRIVING-KANTO-001"]["action"] == "no_facts"
    assert world["store"].list("ROAD-DRIVING-KANTO-001") == []
    assert not (world["store"].root / "ROAD-DRIVING-KANTO-001.json").exists()


def test_unknown_dataset_id_is_error_and_writes_nothing(world):
    out = am.migrate_all(world["ds"], store=world["store"], dataset_ids=["NOPE-001"], admin_dir=world["admin"])
    assert out == [{"dataset_id": "NOPE-001", "action": "error", "error": "dataset definition がありません"}]
    assert not list(world["store"].root.glob("*.json")) if world["store"].root.exists() else True


# ── 4-8, 10, 16, 17. 判定 ────────────────────────────────────────────────────────

def test_04_17_tokyo_river_valid_and_sorted(world):
    _run(world, ["TOKYO-RIVER-001"])
    rec = world["store"].active("TOKYO-RIVER-001")
    assert rec.validity == ah.AcquisitionValidity.valid and rec.validity_reason is None and rec.validity_flags == []
    assert [f.name for f in rec.source_files] == sorted(A31)  # 17. 辞書順で決定的
    assert rec.bundle.name == "TOKYO-RIVER-001_bundle_stmxod68.zip"


def test_05_06_10_kanagawa_river_mismatch_while_active(world):
    _run(world, ["KANAGAWA-RIVER-001"])
    rec = world["store"].active("KANAGAWA-RIVER-001")
    assert rec.active is True  # 6. active=false へ勝手に変えない
    assert rec.validity == ah.AcquisitionValidity.provenance_mismatch
    assert rec.validity_flags == [pv.REGION_MISMATCH]
    assert "region code 13" in rec.validity_reason and "expects region code 14" in rec.validity_reason
    assert "A31a-25_13_10_GML.zip" in rec.validity_reason  # 10. 確認できた事実（原本名）を保存
    persisted = json.loads((world["store"].root / "KANAGAWA-RIVER-001.json").read_text())["acquisitions"][0]
    assert persisted["validity"] == "provenance_mismatch" and persisted["validity_reason"] == rec.validity_reason


def test_07_kanagawa_evac_suspect_not_rewritten(world):
    _run(world, ["KANAGAWA-EVAC-001"])
    rec = world["store"].active("KANAGAWA-EVAC-001")
    assert rec.validity == ah.AcquisitionValidity.provenance_suspect and rec.validity_flags == [pv.SHARED_SOURCE]
    assert rec.validity_reason == ("KANAGAWA-EVAC-001 and KANAGAWA-SHELTER-001 reference the same source file "
                                   "14000_2.zip; requires verification")
    assert [f.name for f in rec.source_files] == ["14000_2.zip"]  # 推測で 14000_1.zip に書き換えない


def test_07b_suspect_applies_even_when_method_unknown(world):
    """実データの KANAGAWA-EVAC-001 は job 記録が無く legacy_unknown。共有原本の事実は取得方法に依らず suspect。"""
    (world["admin"] / "history" / "KANAGAWA-EVAC-001.jsonl").unlink()
    out = _run(world, ["KANAGAWA-EVAC-001", "KANAGAWA-SHELTER-001"], dry_run=True)
    assert out["KANAGAWA-EVAC-001"]["method"] == "legacy_unknown"
    assert out["KANAGAWA-EVAC-001"]["validity"] == "provenance_suspect"
    # 同じ事実は SHELTER 側にも対称に当てはまる（どちらが誤りかは推測しない）
    assert out["KANAGAWA-SHELTER-001"]["validity"] == "provenance_suspect"


def test_region_mismatch_applies_even_when_method_unknown():
    rec = ah.AcquisitionRecord(dataset_id="KANAGAWA-RIVER-001", acquisition_method="legacy_unknown",
                               source_files=[ah.SourceFile(name="A31a-25_13_10_GML.zip", sha256="a")])
    assert pv.assess(DEFNS[1], rec)[0] == ah.AcquisitionValidity.provenance_mismatch


def test_tokyo_river_not_suspect_despite_sharing_with_kanagawa(world):
    """東京原本を KANAGAWA-RIVER と共有していても、TOKYO 側は地域コード一致が確認できるので valid。"""
    _run(world, ["KANAGAWA-RIVER-001"])
    _run(world, ["TOKYO-RIVER-001"])
    assert world["store"].active("TOKYO-RIVER-001").validity == ah.AcquisitionValidity.valid


def test_08_16_legacy_unknown_never_valid(world):
    _run(world, ["TOKYO-DEM-001"])
    rec = world["store"].active("TOKYO-DEM-001")
    assert rec.acquisition_method == ah.AcquisitionMethod.legacy_unknown and rec.active is True
    assert rec.validity == ah.AcquisitionValidity.unknown
    # 原本名・sha256 が揃っていても legacy_unknown は valid にしない
    assert rec.source_files[0].sha256
    assert pv.assess(DEFNS[4], rec)[0] == ah.AcquisitionValidity.unknown


def test_16_no_auto_promotion_on_rerun(world):
    _run(world, ["KANAGAWA-RIVER-001"])
    out = _run(world, ["KANAGAWA-RIVER-001"])
    assert out["KANAGAWA-RIVER-001"]["action"] == "skip_existing"
    assert world["store"].active("KANAGAWA-RIVER-001").validity == ah.AcquisitionValidity.provenance_mismatch


def test_15_backfill_warns_for_non_valid(world, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        _run(world, ["KANAGAWA-RIVER-001", "TOKYO-RIVER-001"])
    msgs = [r.getMessage() for r in caplog.records]
    assert any("validity=provenance_mismatch: KANAGAWA-RIVER-001" in m for m in msgs)
    assert not any("TOKYO-RIVER-001" in m for m in msgs)


# ── 18, 19. 互換・atomic ────────────────────────────────────────────────────────

def test_18_existing_history_without_validity_reads_unknown(tmp_path):
    root = tmp_path / "acq"
    root.mkdir()
    legacy = {"schema_version": 1, "dataset_id": "X-001", "acquisitions": [{
        "acquisition_id": "a1", "dataset_id": "X-001", "acquisition_method": "upload", "active": True,
        "source_files": [{"name": "x.zip"}]}]}
    (root / "X-001.json").write_text(json.dumps(legacy))
    before = (root / "X-001.json").read_bytes()
    rec = ah.AcquisitionStore(root).active("X-001")
    assert rec.validity == ah.AcquisitionValidity.unknown and rec.validity_reason is None
    assert (root / "X-001.json").read_bytes() == before  # 読むだけで既存 file を書き換えない


def test_19_atomic_write_with_validity(tmp_path):
    s = ah.AcquisitionStore(tmp_path / "acq")
    s.add(ah.AcquisitionRecord(dataset_id="X-001", acquisition_method="upload", active=True,
                               validity="provenance_mismatch", validity_reason="r", validity_flags=["REGION_MISMATCH"]))
    before = (tmp_path / "acq" / "X-001.json").read_bytes()
    with patch.object(ah.json, "dump", side_effect=OSError("disk full")), pytest.raises(OSError):
        s.add(ah.AcquisitionRecord(dataset_id="X-001", acquisition_method="upload"))
    assert (tmp_path / "acq" / "X-001.json").read_bytes() == before
    assert not [p for p in (tmp_path / "acq").iterdir() if ".tmp-" in p.name]
    assert s.active("X-001").validity_flags == ["REGION_MISMATCH"]


# ── 12-15. Data Ops 表示・overall ───────────────────────────────────────────────

@pytest.fixture
def ops(world, tmp_path, monkeypatch):
    monkeypatch.setattr(drr, "_default_cache", drr.SourceShaCache(tmp_path / "cache" / "src.json"))
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "cache" / "tile.json"))
    monkeypatch.setattr(dos, "martin_catalog_ids", lambda ttl=60.0: None)
    monkeypatch.setattr(dos, "_app_properties", lambda: {"hazard.flood.enabled": "true"})
    monkeypatch.setenv("OHG2_DATA_RUNTIME_ROOT", str(tmp_path / "no-runtime"))
    drr._view_cache.clear()
    _run(world)
    ss = Mock()
    ss.init_from_definition.side_effect = lambda d: DatasetState(dataset_id=d.dataset_id)
    console = dos.build_console(world["ds"], ss, store=world["store"])
    return {r["dataset_id"]: r for r in console["datasets"]}


def test_12_14_list_shows_active_and_validity_separately(ops):
    tr = ops["TOKYO-RIVER-001"]["acquisition"]
    assert tr["active"]["active"] is True and tr["validity"] == "valid"
    assert ops["TOKYO-RIVER-001"]["integrity"]["components"]["source"]["status"] == dos.OK
    kr = ops["KANAGAWA-RIVER-001"]
    assert kr["acquisition"]["active"]["active"] is True and kr["acquisition"]["validity"] == "provenance_mismatch"
    assert kr["acquisition"]["validity_flags"] == ["REGION_MISMATCH"]
    assert kr["integrity"]["components"]["source"]["status"] == dos.ERROR
    assert kr["integrity"]["overall"] == dos.ERROR  # 14. mismatch は overall OK にしない
    assert "provenance_mismatch" in kr["integrity"]["components"]["source"]["reason"]
    road = ops["ROAD-DRIVING-KANTO-001"]["acquisition"]
    assert road["active"] is None and road["validity"] == "unknown"
    assert road["validity_reason"] == "no acquisition history" and road["status"] == dos.WARNING


def test_15_suspect_and_unknown_are_warning(ops):
    assert ops["KANAGAWA-EVAC-001"]["acquisition"]["validity"] == "provenance_suspect"
    assert ops["KANAGAWA-EVAC-001"]["integrity"]["components"]["source"]["status"] == dos.WARNING
    assert ops["TOKYO-DEM-001"]["acquisition"]["validity"] == "unknown"
    assert ops["TOKYO-DEM-001"]["integrity"]["components"]["source"]["status"] == dos.WARNING


def test_14_published_runtime_does_not_mask_mismatch():
    comps = {"source": {"status": dos.ERROR}, "runtime": {"status": dos.OK}, "tile": {"status": dos.OK},
             "backend": {"status": dos.UNOBSERVED}}
    assert dos._overall(comps) == dos.ERROR


def test_13_ui_detail_and_list_render_validity_as_text():
    js = (ROOT / "operator/frontend-admin/data-ops.js").read_text(encoding="utf-8")
    for label in ("PROVENANCE MISMATCH", "PROVENANCE SUSPECT", "NO ACQUISITION HISTORY", "REGION MISMATCH",
                  '"ACTIVE"', '["Provenance"', '["Reason"'):
        assert label in js, label
    assert "innerHTML" not in js


# ── CLI / registry ──────────────────────────────────────────────────────────────

def test_cli_accepts_repeated_dataset(monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bf", ROOT / "scripts/publish/backfill_acquisition_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return [{"dataset_id": d, "action": "dry_run", "validity": "valid"} for d in kw["dataset_ids"]]
    monkeypatch.setattr(am, "migrate_all", fake)
    monkeypatch.setattr(sys, "argv", ["x", "--dataset", "TOKYO-RIVER-001", "--dataset", "TOKYO-TSUNAMI-001", "--dry-run"])
    assert mod.main() == 0
    assert seen == {"dry_run": True, "dataset_ids": ["TOKYO-RIVER-001", "TOKYO-TSUNAMI-001"]}
    assert [r["dataset_id"] for r in json.loads(capsys.readouterr().out)] == ["TOKYO-RIVER-001", "TOKYO-TSUNAMI-001"]


def test_registry_region_codes_for_flood_only():
    from app.services.dataset_definition_service import get_definition_service
    ds = get_definition_service()
    assert ds.get("TOKYO-RIVER-001").expected_source_region_code == "13"
    assert ds.get("KANAGAWA-RIVER-001").expected_source_region_code == "14"
    assert {d.dataset_id for d in ds.list_all() if d.expected_source_region_code} == {"TOKYO-RIVER-001", "KANAGAWA-RIVER-001"}
    tr = ds.get("TOKYO-RIVER-001")
    files = [ah.SourceFile(name=n) for n in A31]
    assert pv.extract_region_codes(tr, files) == [("A31a-25_13_10_GML.zip", "13"), ("A31a-25_13_20_GML.zip", "13")]


def test_pipeline_records_validity(tmp_path, monkeypatch):
    """取込時の記録も同じ判定（他 dataset の active と照合）を付ける。"""
    from app.models.admin_dataset import Job, JobType
    from app.services import pipeline_service as ps
    store = ah.AcquisitionStore(tmp_path / "acq")
    monkeypatch.setattr(ps, "get_acquisition_store", lambda: store)
    # 利用者が自分で zip にまとめた bundle を単一 upload（外側名に地域コードなし）
    raw = _zip(tmp_path / "my_bundle.zip", {"A31a-25_13_10_GML.zip": b"x", "readme.txt": b"r"})
    job = Job(job_id="j", dataset_id="KANAGAWA-RIVER-001", job_type=JobType.ingest_upload)
    acq_id = ps._record_acquisition(job, DEFNS[1], raw, {"method": "upload", "original_files": [raw.name]})
    rec = store.list("KANAGAWA-RIVER-001")[0]
    assert rec.acquisition_id == acq_id and rec.validity == ah.AcquisitionValidity.provenance_mismatch
    assert [f.name for f in rec.source_files] == ["A31a-25_13_10_GML.zip"] and rec.bundle.name == "my_bundle.zip"
