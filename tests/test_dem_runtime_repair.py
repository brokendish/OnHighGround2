"""
DEM-RUNTIME-REPAIR（2026-10-12）: 修正版 DEM（標準配置）と backend・PSEUDO・Data Ops・配備手順の回帰。

fixture（tests/fixtures/dem_audit/dem_audit_fixture.json）:
  samples = 監査の 300 点と地理院 DEM5A 標高タイル（z15）の値（補助基準）
  pairs   = 旧 backend と正しい読み方で避難の 10 m 判定が逆になった（現在地, 避難所）62 組
実 DEM を使う test は build node（data_lake がある環境）だけで動く。
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_bounds  # noqa: E402

from elevation_service import ElevationService  # noqa: E402

FIXTURE = json.loads((ROOT / "tests/fixtures/dem_audit/dem_audit_fixture.json").read_text(encoding="utf-8"))
DEM = ROOT / "data_lake/validated/tokyo/dem/elevation.tif"
NEW_SHA = "837bb7042c15c9b5ccefebaaaae55d269616fc0ae8acc850f190b246a18d31d7"
OLD_SHA = "fdd8e3b37b53cec7587e863ee37c4f7bf4aeaf41a4f1c279cead88356226a77f"


@pytest.fixture(scope="module")
def svc():
    if not DEM.is_file():
        pytest.skip("DEM が無い環境")
    s = ElevationService(str(DEM))
    assert s.is_loaded()
    return s


# ── 8. 300 点の統計（監査の正しい読み方と同等）──────────────────────────────────────

def test_08_300_sample_statistics_match_audit(svc):
    diffs = np.array([svc.get_elevation(p["lat"], p["lon"]) - p["dem5a"] for p in FIXTURE["samples"]
                      if svc.get_elevation(p["lat"], p["lon"]) is not None])
    ad = np.abs(diffs)
    assert len(diffs) >= 295
    assert np.median(ad) <= 0.15 and np.percentile(ad, 95) <= 2.5 and ad.max() <= 6.0  # 監査: 0.09 / 1.95 / 5.65
    assert abs(diffs.mean()) <= 0.1


def test_08b_interpolated_statistics(svc):
    ad = np.abs([svc.get_elevation_interpolated(p["lat"], p["lon"]) - p["dem5a"] for p in FIXTURE["samples"]
                 if svc.get_elevation_interpolated(p["lat"], p["lon"]) is not None])
    assert np.median(ad) <= 0.15 and np.percentile(ad, 95) <= 2.5


# ── 10-11. false-safe = 0（旧 backend で 10 m 判定が逆だった組）─────────────────────────

def test_10_11_threshold_pairs_now_agree_with_correct_reading(svc):
    pairs = FIXTURE["pairs"]
    assert {p["kind"] for p in pairs} == {"false_include", "false_exclude"} and len(pairs) >= 50
    wrong = []
    for p in pairs:
        here = svc.get_elevation_interpolated(p["lat"], p["lon"])
        there = svc.get_elevation_interpolated(p["shelter_lat"], p["shelter_lon"])
        if (there - here >= 10.0) != (p["correct_gain"] >= 10.0):
            wrong.append((p["from"], p["kind"], round(there - here, 2), p["correct_gain"]))
    assert wrong == []
    false_include = [p for p in pairs if p["kind"] == "false_include"]
    assert all(p["old_backend_gain"] >= 10 > p["correct_gain"] for p in false_include)


# ── 12-14. score・grid fallback・profile（合成の標準配置 DEM）─────────────────────────

def _synthetic(tmp_path, arr, west=139.0, north=35.02, cell=0.001):
    p = tmp_path / "dem.tif"
    h, w = arr.shape
    with rasterio.open(p, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32", crs="EPSG:6668",
                       transform=from_bounds(west, north - h * cell, west + w * cell, north, w, h), nodata=-9999.0) as d:
        d.write(arr.astype(np.float32), 1)
    return ElevationService(str(p))


def test_12_score_saturates_at_30m(tmp_path):
    s = _synthetic(tmp_path, np.zeros((20, 20)))
    assert s._calculate_safety_score(30.0, 0) == s._calculate_safety_score(60.0, 0)
    assert s._calculate_safety_score(15.0, 0) < s._calculate_safety_score(30.0, 0)
    src = (ROOT / "backend/app_public.py").read_text(encoding="utf-8")
    assert "elevation_score = min(elevation_gain / 30.0 * 50, 50)" in src
    assert "if elevation_gain < min_elevation_gain:" in src


def test_13_grid_fallback_finds_hill_in_the_right_place(tmp_path):
    arr = np.zeros((40, 40))
    arr[5:10, 30:35] = 20.0  # 北東寄りの丘（行 5–9 = 緯度 35.010–35.015、列 30–34 = 経度 139.030–139.035）
    s = _synthetic(tmp_path, arr, north=35.04)
    got = s.find_evacuation_destinations(35.02, 139.02, min_elevation_gain=10.0, max_distance=3000.0, grid_size=60)
    assert got, "丘が見つからない"
    for g in got:
        assert 35.030 <= g["lat"] <= 35.0351 and 139.030 <= g["lon"] <= 139.0351, g  # 丘の位置（x = 経度）
        assert g["elevation_gain"] == pytest.approx(20.0)


def test_14_profile_uses_standard_axes(tmp_path):
    arr = np.tile(np.arange(30, dtype=float), (30, 1))  # 値 = 列番号（経度方向に増える）
    s = _synthetic(tmp_path, arr, north=35.03)
    prof = s.get_elevation_profile(35.015, 139.0055, 35.015, 139.0255, num_points=3)
    assert [round(p["elevation"], 1) for p in prof] == [5.0, 15.0, 25.0]


# ── 16-17. PSEUDO の派生元・tile ────────────────────────────────────────────────

def test_16_17_pseudo_dependency_canonical_and_tile():
    from app.services.dataset_definition_service import get_definition_service
    d = get_definition_service().get("TOKYO-PSEUDO-INLAND-FLOOD-001")
    assert [i.sha256 for i in d.derived_from] == [NEW_SHA]
    rec_path = ROOT / "data_lake/provenance/tokyo/pseudo_inland_flood/TOKYO-PSEUDO-INLAND-FLOOD-001.json"
    tile = ROOT / "data_lake/tiles/tokyo/pseudo_inland_flood/tokyo_pseudo_inland_flood_001.mbtiles"
    if not (rec_path.is_file() and tile.is_file()):
        pytest.skip("build node の provenance / tile が無い環境")
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    assert rec["canonical"]["sha256"] == d.generator["output_sha256"]
    assert rec["tile"]["sha256"] == hashlib.sha256(tile.read_bytes()).hexdigest() and rec.get("tile_note") is None
    import sqlite3
    con = sqlite3.connect(f"file:{tile}?mode=ro", uri=True)
    meta = dict(con.execute("select name, value from metadata"))
    assert (meta["minzoom"], meta["maxzoom"], meta["format"]) == ("5", "16", "pbf")
    assert json.loads(meta["json"])["vector_layers"][0]["id"] == "pseudo_inland_flood"


# ── 18. Data Ops: atomic version 外の artifact ──────────────────────────────────────

@pytest.mark.parametrize("content,expected", [("NEW", "ARTIFACT_VERIFIED"), ("OLD", "ARTIFACT_SUPERSEDED_IN_USE"),
                                              ("OTHER", "ARTIFACT_MISMATCH")])
def test_18_data_ops_artifact_section(tmp_path, monkeypatch, content, expected):
    from app.models.admin_dataset import DatasetDefinition, DatasetState
    from app.services import data_ops_service as dos
    from app.services import dataset_runtime_reconcile as drr
    monkeypatch.setattr(drr, "get_source_sha_cache", lambda: drr.SourceShaCache(tmp_path / "c.json"))
    f = tmp_path / "elevation.tif"
    f.write_bytes(content.encode())
    sha = {k: hashlib.sha256(k.encode()).hexdigest() for k in ("NEW", "OLD")}
    defn = DatasetDefinition(dataset_id="DEM-T", region="tokyo", category="dem", display_name="t", description="t",
                             hint_text="t", impact_scope="t", accepted_input_modes=["upload"], accepted_extensions=[".tif"],
                             max_browser_upload_mb=1, requires_normalize=False, requires_validation=False,
                             requires_deploy=True, requires_osrm_rebuild=False, raw_storage_path="x",
                             runtime_path="none/x", artifact_sha256=sha["NEW"],
                             superseded_artifacts=[{"sha256": sha["OLD"], "reason": "旧配置"}])
    s = dos.artifact_section(defn, DatasetState(dataset_id="DEM-T", current_validated_path=str(f)), allow_hash=True)
    assert s["label"] == expected
    assert s["component_status"] == {"ARTIFACT_VERIFIED": dos.OK}.get(expected, dos.ERROR)


def test_18b_runtime_node_artifact_ignores_superseded_copy(tmp_path, monkeypatch):
    """runtime node（validated が無い）では flat runtime の file を照合する。置き換えで残した
    elevation.tif.superseded-<sha12> があっても現在の file を選ぶ。"""
    from app.models.admin_dataset import DatasetDefinition, DatasetState
    from app.services import data_ops_service as dos
    from app.services import dataset_runtime_reconcile as drr
    from app.services import runtime_version_access as rva
    rt = tmp_path / "rt"
    (rt / "backend/elevation").mkdir(parents=True)
    (rt / "backend/elevation/elevation.tif").write_bytes(b"NEW")
    (rt / "backend/elevation/elevation.tif.superseded-0123456789ab").write_bytes(b"OLD")
    (rt / "backend/elevation/.gitkeep").write_bytes(b"")
    monkeypatch.setattr(rva, "DATA_RUNTIME_ROOT", rt)
    monkeypatch.setattr(drr, "get_source_sha_cache", lambda: drr.SourceShaCache(tmp_path / "c.json"))
    defn = DatasetDefinition(dataset_id="DEM-T", region="tokyo", category="dem", display_name="t", description="t",
                             hint_text="t", impact_scope="t", accepted_input_modes=["upload"], accepted_extensions=[".tif"],
                             max_browser_upload_mb=1, requires_normalize=False, requires_validation=False,
                             requires_deploy=True, requires_osrm_rebuild=False, raw_storage_path="x",
                             runtime_path="data_runtime/backend/elevation", artifact_sha256=hashlib.sha256(b"NEW").hexdigest())
    s = dos.artifact_section(defn, DatasetState(dataset_id="DEM-T"), allow_hash=True)
    assert s["label"] == "ARTIFACT_VERIFIED" and s["path"].endswith("backend/elevation/elevation.tif")


# ── 19. 配備と rollback（flat runtime の DEM）────────────────────────────────────────

def _sh(*a):
    return subprocess.run(["bash", str(ROOT / "scripts/publish/deploy_dem_runtime.sh"), *a], capture_output=True, text=True)


def test_19_install_and_rollback_keep_both_artifacts(tmp_path):
    rt = tmp_path / "elevation"
    rt.mkdir()
    (rt / "elevation.tif").write_bytes(b"OLD-DEM")
    new = tmp_path / "new.tif"
    new.write_bytes(b"NEW-DEM")
    old_sha, new_sha = hashlib.sha256(b"OLD-DEM").hexdigest(), hashlib.sha256(b"NEW-DEM").hexdigest()
    bad = _sh("install", str(new), old_sha, str(rt))  # sha 不一致は何も変えない
    assert bad.returncode == 2 and (rt / "elevation.tif").read_bytes() == b"OLD-DEM"
    r = _sh("install", str(new), new_sha, str(rt))
    assert r.returncode == 0, r.stderr
    assert (rt / "elevation.tif").read_bytes() == b"NEW-DEM"
    assert (rt / f"elevation.tif.superseded-{old_sha[:12]}").read_bytes() == b"OLD-DEM"  # 旧 DEM は削除しない
    assert not list(rt.glob(".elevation.tif.staging-*"))
    r = _sh("rollback", str(rt), old_sha)
    assert r.returncode == 0, r.stderr
    assert (rt / "elevation.tif").read_bytes() == b"OLD-DEM"
    assert (rt / f"elevation.tif.superseded-{new_sha[:12]}").read_bytes() == b"NEW-DEM"


def test_19b_registry_keeps_rollback_target():
    from app.services.dataset_definition_service import get_definition_service
    d = get_definition_service().get("TOKYO-DEM-001")
    assert d.artifact_sha256 == NEW_SHA and d.superseded_artifacts[0]["sha256"] == OLD_SHA
    backup = ROOT / "data_lake/_backup/dem_superseded_20261012/elevation.tif"
    if backup.is_file():
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == OLD_SHA


# ── 20. 隔離 ───────────────────────────────────────────────────────────────────

def test_20_no_real_runtime_or_admin_writes(tmp_path):
    real = [DEM, ROOT / "data_lake/admin/cache/source_sha256.json"]
    before = [p.stat().st_mtime_ns if p.exists() else None for p in real]
    test_19_install_and_rollback_keep_both_artifacts(tmp_path)
    assert [p.stat().st_mtime_ns if p.exists() else None for p in real] == before
