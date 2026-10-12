"""
PUBLIC-RELEASE-DEM-FIXTURE-REQUALIFICATION（2026-10-12）: demo DEM fixture（Phase 2-D、AT-17A demo profile）を
DEM-RUNTIME-REPAIR の座標契約で再資格化する。

  旧 fixture sha256 0641f39c…: 本番 DEM の緯度経度入れ替わり配置を意図的に再現（x = 緯度）
  新 fixture sha256 90edc62a…: 標準 north-up 配置（x = 経度、y = 緯度）、nodata = -9999（南東隅 9 cell）
修正後の backend は入れ替わった DEM を読み込まない（fail closed）ため、旧 fixture では demo profile の DEM が
使えなくなる。release delta manifest（tasks/public-release/evidence/phase2d/phase2d_round5c_*）は 2026-08-22 時点の
round の記録（674 entry 中 213 entry が既に現在と異なる）であり、書き換えない。現在の tree には release delta が
無く（manifest 再生成で entry 0）、release candidate は HEAD の内容そのもの。
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
from elevation_service import ElevationService  # noqa: E402

FIX = ROOT / "tests/fixtures/dem_demo"
TIF = FIX / "elevation_demo.tif"
MANIFEST = json.loads((FIX / "MANIFEST.json").read_text(encoding="utf-8"))
NEW_SHA = "90edc62a5a0a2edc7a95471057deba6bca4436f2e29d7baf18b452edf1ae3ca7"
OLD_SHA = "0641f39ce81d62fb53029596a9d750f9f770089f31567e40d74cd073a4e3d5db"
DEMO_BBOX = (139.760, 35.676, 139.774, 35.686)  # demo OSM bbox（west, south, east, north）


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ── 1-5. fixture の同一性・metadata・配置・nodata・manifest ────────────────────────────

def test_01_05_new_fixture_sha_and_manifest():
    assert _sha(TIF) == NEW_SHA == MANIFEST["file"]["sha256"]
    assert _sha(FIX / "generate_synthetic_dem.py") == MANIFEST["generator_sha256"]
    assert "Standard north-up" in MANIFEST["axis_convention"]


def test_02_03_metadata_and_north_up_layout():
    with rasterio.open(TIF) as src:
        t = src.transform
        assert (src.width, src.height) == (54, 50) == (MANIFEST["grid"]["width"], MANIFEST["grid"]["height"])
        assert src.crs.to_epsg() == 6668 and src.dtypes == ("float32",)
        assert t.a > 0 and t.e < 0 and t.b == 0 and t.d == 0  # x = 経度（東へ増加）、y = 緯度（南へ行が進む）
        b = src.bounds
        assert (b.left, b.bottom, b.right, b.top) == pytest.approx((139.74, 35.656, 139.794, 35.706))


def test_04_nodata_is_minus_9999_in_south_east_corner():
    with rasterio.open(TIF) as src:
        a = src.read(1)
        assert src.nodata == -9999.0
    assert int((a == -9999.0).sum()) == MANIFEST["grid"]["nodata_cell_count"] == 9
    assert (a[-3:, -3:] == -9999.0).all() and not (a[:-3, :] == -9999.0).any()


# ── 7-8. backend（ElevationService）の標高・避難判定 ───────────────────────────────

def _independent_bilinear(src, a, lat, lon):
    c, r = ~src.transform * (lon, lat)
    c, r = c - 0.5, r - 0.5
    r0, c0 = math.floor(r), math.floor(c)
    dr, dc = r - r0, c - c0
    q = a[r0:r0 + 2, c0:c0 + 2].astype(float)
    return (q[0, 0] * (1 - dc) + q[0, 1] * dc) * (1 - dr) + (q[1, 0] * (1 - dc) + q[1, 1] * dc) * dr


def test_07_elevation_matches_independent_reading():
    svc = ElevationService(str(TIF))
    assert svc.is_loaded()
    src = rasterio.open(TIF)
    a = src.read(1)
    w, s, e, n = DEMO_BBOX
    for lat, lon in [((s + n) / 2, (w + e) / 2), (s, w), (n, e), (n, w), (s, e)]:
        assert svc.get_elevation_interpolated(lat, lon) == pytest.approx(_independent_bilinear(src, a, lat, lon), abs=1e-4)
    assert svc.get_elevation(35.656 + 0.0005, 139.794 - 0.0005) is None  # nodata 隅


def test_08_grid_fallback_never_returns_lower_candidates():
    svc = ElevationService(str(TIF))
    here = svc.get_elevation_interpolated(35.681, 139.767)
    got = svc.find_evacuation_destinations(35.681, 139.767, min_elevation_gain=5.0, max_distance=2000.0, grid_size=40)
    assert got
    src = rasterio.open(TIF)
    a = src.read(1)
    for g in got:
        r, c = src.index(g["lon"], g["lat"])
        assert float(a[r, c]) - here >= 5.0  # 候補の標高は fixture の値（x = 経度）で 5 m 以上高い（false-safe なし）


# ── 9. PSEUDO generator が標準配置の fixture をそのまま使う ──────────────────────────────

def test_09_pseudo_generator_accepts_standard_fixture_and_refuses_swapped(tmp_path):
    gen = ROOT / "scripts/derive/generate_pseudo_inland_flood.py"
    ok = subprocess.run([sys.executable, str(gen), "--dem", str(TIF), "--output", str(tmp_path / "p.geojson")],
                        capture_output=True, text=True, timeout=300)
    assert ok.returncode == 0, ok.stderr[-400:]
    assert "緯度経度が入れ替わった旧 DEM" not in ok.stderr
    from rasterio.transform import from_bounds
    swapped = tmp_path / "swapped.tif"
    with rasterio.open(TIF) as src:
        a = src.read(1)
    with rasterio.open(swapped, "w", driver="GTiff", width=50, height=54, count=1, dtype="float32", crs="EPSG:6668",
                       transform=from_bounds(35.656, 139.74, 35.706, 139.794, 50, 54), nodata=-9999.0) as dst:
        dst.write(a.T.copy(), 1)  # 旧 fixture と同じ x = 緯度の配置
    ng = subprocess.run([sys.executable, str(gen), "--dem", str(swapped), "--output", str(tmp_path / "q.geojson")],
                        capture_output=True, text=True, timeout=300)
    assert ng.returncode == 2 and "緯度経度が入れ替わった旧 DEM" in ng.stderr


# ── 10-12. 再構築手順・旧 sha の参照・履歴の保持 ───────────────────────────────────────

def test_10_rebuild_path_regenerates_the_same_fixture(tmp_path):
    out = tmp_path / "e.tif"
    r = subprocess.run([sys.executable, str(FIX / "generate_synthetic_dem.py"), "--output", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _sha(out) == NEW_SHA
    compose = (ROOT / "docker-compose.demo.yml").read_text(encoding="utf-8")
    assert "./tests/fixtures/dem_demo/elevation_demo.tif:/data_runtime/backend/elevation/elevation.tif:ro" in compose


RELEASE_ROOTS = ("backend", "frontend", "scripts", "tools/public_release", "docs", "tests/fixtures", "e2e",
                 "operator", "config", "data_processing")


def test_11_old_fixture_sha_absent_from_active_release_surface():
    hits = []
    for root in RELEASE_ROOTS:
        for p in (ROOT / root).rglob("*"):
            if p.is_file() and p.suffix in (".py", ".md", ".json", ".yml", ".yaml", ".sh", ".js", ".txt", ".html") \
                    and "__pycache__" not in p.parts and "docs/audits" not in str(p.relative_to(ROOT)):
                try:
                    if OLD_SHA in p.read_text(encoding="utf-8"):
                        hits.append(str(p.relative_to(ROOT)))
                except (UnicodeDecodeError, OSError):
                    pass
    assert hits == []


def test_12_historical_release_record_is_preserved():
    """round 5C の release delta manifest は当時の記録として旧 sha を保持する（gitignore の tasks/ がある環境だけ）。"""
    p = ROOT / "tasks/public-release/evidence/phase2d/phase2d_round5c_release_delta_manifest.json"
    if not p.is_file():
        pytest.skip("public-release の作業記録が無い環境")
    m = json.loads(p.read_text(encoding="utf-8"))
    entry = next(e for e in m["entries"] if e["path"] == "tests/fixtures/dem_demo/elevation_demo.tif")
    assert entry["release_sha256"] == OLD_SHA and m["baseline_head"].startswith("d3eeb99")
