"""
test_phase2d_dem_fixture_selfcheck.py — synthetic DEM fixture (tests/fixtures/
dem_demo/) のself-test（Phase 2-D Round 9、指示書第5節、15項目）。

AT-17AのCODEX独立検証は「唯一の実機FAIL」として`GET /api/stats`の503
（`標高データが読み込まれていません`）だけを報告した。原因はdemo Composeに
DEMが無いことであり、application自体の503契約（`backend/app_public.py`の
`/api/stats`がDEM未読込時に必ず503を返す設計）は正しいため変更しない。本file
は、demo専用に追加したsynthetic DEM fixtureが「単にfile存在checkを通るだけ」
ではなく、実際の`backend.elevation_service.ElevationService`（本番と同一の
loader実装、変更なし）で正しく読め、demo OSM fixtureのbbox全域をcoverし、
NoData契約・欠落/破損時のfail-closedも維持されることを検証する。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_dem_fixture_selfcheck.py -v
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "dem_demo"
FIXTURE_TIF = FIXTURE_DIR / "elevation_demo.tif"
GENERATOR = FIXTURE_DIR / "generate_synthetic_dem.py"
MANIFEST_PATH = FIXTURE_DIR / "MANIFEST.json"

sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEMO_OSM_BBOX = (139.760, 35.676, 139.774, 35.686)  # west, south, east, north


def _load_elevation_service(path: Path):
    from elevation_service import ElevationService  # noqa: PLC0415

    return ElevationService(str(path))


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. generator 2回のSHA-256一致（決定性）
# ---------------------------------------------------------------------------

def test_01_generator_deterministic(tmp_path):
    out1 = tmp_path / "run1.tif"
    out2 = tmp_path / "run2.tif"
    for out in (out1, out2):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--output", str(out)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    sha1 = hashlib.sha256(out1.read_bytes()).hexdigest()
    sha2 = hashlib.sha256(out2.read_bytes()).hexdigest()
    assert sha1 == sha2
    assert out1.read_bytes() == out2.read_bytes()


# ---------------------------------------------------------------------------
# 2. manifest記載のfile/generator hashが実bytesと一致
# ---------------------------------------------------------------------------

def test_02_manifest_hash_matches_actual_bytes():
    manifest = _manifest()
    actual_file_sha256 = hashlib.sha256(FIXTURE_TIF.read_bytes()).hexdigest()
    actual_generator_sha256 = hashlib.sha256(GENERATOR.read_bytes()).hexdigest()
    assert manifest["file"]["sha256"] == actual_file_sha256
    assert manifest["generator_sha256"] == actual_generator_sha256


# ---------------------------------------------------------------------------
# 3. 正式loader（ElevationService、変更なし）で読込成功
# ---------------------------------------------------------------------------

def test_03_loads_via_real_elevation_service():
    svc = _load_elevation_service(FIXTURE_TIF)
    assert svc.is_loaded()


# ---------------------------------------------------------------------------
# 4. CRS一致
# ---------------------------------------------------------------------------

def test_04_crs_matches_manifest():
    manifest = _manifest()
    svc = _load_elevation_service(FIXTURE_TIF)
    assert str(svc.dataset.crs) == manifest["crs"]


# ---------------------------------------------------------------------------
# 5. demo OSM bboxの全範囲をcover（corner + center、contains=Trueかつ
#    補間標高がNoneでない）
# ---------------------------------------------------------------------------

def test_05_covers_demo_osm_bbox():
    west, south, east, north = DEMO_OSM_BBOX
    svc = _load_elevation_service(FIXTURE_TIF)
    points = [
        ((south + north) / 2, (west + east) / 2),
        (south, west), (north, east), (north, west), (south, east),
    ]
    for lat, lon in points:
        assert svc.contains(lat, lon), (lat, lon)
        elev = svc.get_elevation_interpolated(lat, lon)
        assert elev is not None, (lat, lon)


# ---------------------------------------------------------------------------
# 6. point/cell count一致
# ---------------------------------------------------------------------------

def test_06_grid_dimensions_match_manifest():
    manifest = _manifest()
    svc = _load_elevation_service(FIXTURE_TIF)
    assert svc.dataset.width == manifest["grid"]["width"]
    assert svc.dataset.height == manifest["grid"]["height"]
    assert svc.dataset.width * svc.dataset.height == manifest["grid"]["point_count"]


# ---------------------------------------------------------------------------
# 7. min/max一致
# ---------------------------------------------------------------------------

def test_07_min_max_match_manifest():
    import numpy as np  # noqa: PLC0415

    manifest = _manifest()
    svc = _load_elevation_service(FIXTURE_TIF)
    arr = svc.elevation_data
    sentinel = manifest["nodata"]["sentinel"]
    valid = arr[arr != sentinel]
    assert valid.size == manifest["grid"]["valid_cell_count"]
    assert float(valid.min()) == pytest.approx(manifest["expected_statistics"]["min_elevation"])
    assert float(valid.max()) == pytest.approx(manifest["expected_statistics"]["max_elevation"])
    assert float(valid.mean()) == pytest.approx(manifest["expected_statistics"]["mean_elevation_valid_cells_only"])


# ---------------------------------------------------------------------------
# 8. nodata契約一致
# ---------------------------------------------------------------------------

def test_08_nodata_contract():
    manifest = _manifest()
    svc = _load_elevation_service(FIXTURE_TIF)
    assert svc.dataset.nodata == manifest["nodata"]["sentinel"]

    # NoData corner（row/col原点付近、fixture bbox内だがdemo OSM bboxの外）
    nodata_lat = manifest["fixture_bbox"]["south"] + 0.0005
    nodata_lon = manifest["fixture_bbox"]["east"] - 0.0005
    assert svc.get_elevation(nodata_lat, nodata_lon) is None


# ---------------------------------------------------------------------------
# 9. /api/stats が返す値の元データ（dataset.bounds/width/height/crs）が
#    manifestの期待値と一致することを確認する（HTTP経由の実測200はfocused
#    Docker verificationで別途行う——本testはbackend/app_public.pyの
#    get_statistics()と同一の値を、application起動を伴わずに検証する）。
# ---------------------------------------------------------------------------

def test_09_api_stats_source_values_match_manifest():
    manifest = _manifest()
    svc = _load_elevation_service(FIXTURE_TIF)
    bounds = svc.dataset.bounds
    expected = manifest["api_stats_expected_response"]
    assert bounds.left == pytest.approx(expected["coverage_area"]["west"])
    assert bounds.bottom == pytest.approx(expected["coverage_area"]["south"])
    assert bounds.right == pytest.approx(expected["coverage_area"]["east"])
    assert bounds.top == pytest.approx(expected["coverage_area"]["north"])
    assert svc.dataset.width == expected["resolution"]["width"]
    assert svc.dataset.height == expected["resolution"]["height"]
    assert str(svc.dataset.crs) == expected["crs"]


# ---------------------------------------------------------------------------
# 10. missing fixtureで503相当（dataset=None、is_loaded=False）
# ---------------------------------------------------------------------------

def test_10_missing_fixture_fails_closed(tmp_path):
    missing = tmp_path / "does_not_exist.tif"
    svc = _load_elevation_service(missing)
    assert svc.dataset is None
    assert not svc.is_loaded()


# ---------------------------------------------------------------------------
# 11. corrupt fixtureでfail-closed
# ---------------------------------------------------------------------------

def test_11_corrupt_fixture_fails_closed(tmp_path):
    corrupt = tmp_path / "corrupt.tif"
    corrupt.write_bytes(b"NOT A VALID GEOTIFF" * 100)
    svc = _load_elevation_service(corrupt)
    assert svc.dataset is None
    assert not svc.is_loaded()


# ---------------------------------------------------------------------------
# 12. empty fixtureでfail-closed
# ---------------------------------------------------------------------------

def test_12_empty_fixture_fails_closed(tmp_path):
    empty = tmp_path / "empty.tif"
    empty.write_bytes(b"")
    svc = _load_elevation_service(empty)
    assert svc.dataset is None
    assert not svc.is_loaded()


# ---------------------------------------------------------------------------
# 13. real production DEM pathを参照しない（generatorはsource引数を取らず、
#     production data_runtime/data_lake配下を一切読まない）
# ---------------------------------------------------------------------------

def test_13_generator_does_not_reference_production_dem_paths():
    """docstring内で本番DEMのpath文字列を設計根拠として説明することは許容する
    （実際に`rasterio.open()`等で読み込んでいなければ問題ない）。実際に
    file読込みが発生し得るのは`rasterio.open(...)`呼び出しだけなので、
    その呼び出しが`output_path`以外の引数を取っていないことを直接確認する。"""
    text = GENERATOR.read_text(encoding="utf-8")

    import re

    # docstring中の`rasterio.open()`（空括弧、説明目的の言及）は除外し、
    # 実際に引数を持つ呼び出しだけを対象にする。
    rasterio_open_calls = [c for c in re.findall(r"rasterio\.open\(([^)]*)\)", text) if c.strip()]
    assert rasterio_open_calls, "no rasterio.open(...) call with arguments found"
    for call_args in rasterio_open_calls:
        assert "output_path" in call_args, f"unexpected rasterio.open() argument: {call_args!r}"
        assert "data_lake" not in call_args
        assert "data_runtime" not in call_args

    # data_lake（production hazard/DEM raw data root）はdocstringにも一切
    # 登場しない前提（data_runtimeはaxis-swap契約の説明で言及するため許容）。
    assert "data_lake" not in text


# ---------------------------------------------------------------------------
# 14. source repository外へ書き出さない（generatorはargparseの--outputへの
#     単一file書込みのみ、他のPath書込みを持たない）
# ---------------------------------------------------------------------------

def test_14_generator_writes_only_to_output_argument():
    text = GENERATOR.read_text(encoding="utf-8")
    # rasterio.open(..., "w", ...) と output_path.unlink() 以外に書込み系呼び出しが
    # ないことを確認する（open(..., "w")やPath.write_*の別経路が無いことの静的確認）。
    write_call_markers = ["rasterio.open(output_path", "output_path.unlink()"]
    for marker in write_call_markers:
        assert marker in text
    assert ".write_text(" not in text
    assert ".write_bytes(" not in text
    forbidden_open_write = ["open(REPO_ROOT", "open('/", 'open("/']
    for marker in forbidden_open_write:
        assert marker not in text


# ---------------------------------------------------------------------------
# 15. secret / absolute user path 0（typed boundary scannerをfixture 3
#     fileへ明示適用）
# ---------------------------------------------------------------------------

def test_15_no_secret_or_absolute_path_in_fixture_files():
    import phase2d_typed_boundary_scan as scan_mod  # noqa: PLC0415

    explicit_paths = [
        "tests/fixtures/dem_demo/generate_synthetic_dem.py",
        "tests/fixtures/dem_demo/MANIFEST.json",
        "tests/fixtures/dem_demo/README.md",
    ]
    findings = scan_mod.scan_typed(REPO_ROOT, explicit_paths=explicit_paths)
    for finding_type in (
        "SECRET_VALUE", "PRIVATE_KEY", "AUTHORIZATION_VALUE", "COOKIE_VALUE",
        "ABSOLUTE_USER_PATH",
    ):
        assert findings[finding_type] == [], f"{finding_type}: {findings[finding_type]}"
