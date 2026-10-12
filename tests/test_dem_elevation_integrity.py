"""
DEM-ELEVATION-INTEGRITY（監査 2026-10-12）と DEM-RUNTIME-REPAIR（同日修正）の契約。

監査の結論: DEM の画素値は正しいが、旧 convert_dem.py が 3 次メッシュ tile の配置だけを転置していたため、
geotransform どおりに読む backend は tile 内で最大約 1 km ずれた画素を読んでいた（避難の 10 m 判定で false-safe）。
修正:
  - convert_dem.py: lowerCorner/upperCorner を緯度経度として解釈し、標準配置（x = 経度、north-up）で結合する。
    nodata = -9999（原本 tile の無い範囲を 0 で埋めない）、入力は path 昇順、同じ範囲の XML が複数あれば中止
  - relayout_fgd_dem.py: 原本 GML が無いので、旧 artifact を画素値を変えずに標準配置へ並べ替える
    （修正版 convert_dem.py の出力と一致することをここで確認する）
  - ElevationService: geotransform どおりに読む。入れ替わった旧 DEM は読み込まない（fail closed）。
    補間は画素中心を標本点とする双線形補間
  - PSEUDO generator: 配列全体を転置する補正を廃止（旧 DEM は中止）
"""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_bounds  # noqa: E402


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass は定義中に自 module を参照する
    spec.loader.exec_module(mod)
    return mod


audit = _load("audit_dem_elevation", "scripts/validate/audit_dem_elevation.py")
relayout = _load("relayout_fgd_dem", "scripts/derive/relayout_fgd_dem.py")
from elevation_service import ElevationService  # noqa: E402

# 合成 1 次メッシュ: 2 × 2 tile、tile 内 緯度 3 × 経度 4 格子（緯度 0.01°・経度 0.016° の tile）
M = audit.FgdMosaic(lat0=35.0, lon0=139.0, tile_dlat=0.01, tile_dlon=0.016, n_tiles_lat=2, n_tiles_lon=2,
                    tile_rows=3, tile_cols=4)
ALL_TILES = ((0, 0), (0, 1), (1, 0), (1, 1))


def _value(tile_lat, tile_lon, r, c):
    """格子ごとに一意な値: 緯度 tile・経度 tile・tile 内の行（北→南）・列（西→東）。"""
    return 1000 * tile_lat + 100 * tile_lon + 10 * r + c + 1


def _fgd_xml(path: Path, tile_lat: int, tile_lon: int, values=None):
    lat_s, lon_w = M.lat0 + tile_lat * M.tile_dlat, M.lon0 + tile_lon * M.tile_dlon
    vals = values if values is not None else [_value(tile_lat, tile_lon, r, c)
                                               for r in range(M.tile_rows) for c in range(M.tile_cols)]  # +x-y
    tuples = "\n".join(f"地表面,{v}" for v in vals)
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Dataset xmlns="http://fgd.gsi.go.jp/spec/2008/FGD_GMLSchema" xmlns:gml="http://www.opengis.net/gml/3.2">
<DEM><coverage><gml:boundedBy><gml:Envelope>
<gml:lowerCorner>{lat_s} {lon_w}</gml:lowerCorner><gml:upperCorner>{lat_s + M.tile_dlat} {lon_w + M.tile_dlon}</gml:upperCorner>
</gml:Envelope></gml:boundedBy>
<gml:gridDomain><gml:Grid><gml:limits><gml:GridEnvelope><gml:low>0 0</gml:low><gml:high>{M.tile_cols - 1} {M.tile_rows - 1}</gml:high></gml:GridEnvelope></gml:limits></gml:Grid></gml:gridDomain>
<gml:rangeSet><gml:DataBlock><gml:tupleList>
{tuples}
</gml:tupleList></gml:DataBlock></gml:rangeSet>
<gml:coverageFunction><gml:GridFunction><gml:sequenceRule order="+x-y">Linear</gml:sequenceRule><gml:startPoint>0 0</gml:startPoint></gml:GridFunction></gml:coverageFunction>
</coverage></DEM></Dataset>""", encoding="utf-8")
    return path


def _convert_dir(tmp_path, tiles=ALL_TILES, extra=()):
    """修正版 convert_dem.py の CLI（directory 入力 = 結合）で変換する。"""
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir(parents=True)
    for i, (a, b) in enumerate(tiles):
        _fgd_xml(xml_dir / f"FG-{i:02d}.xml", a, b)
    for i, ((a, b), vals) in enumerate(extra):
        _fgd_xml(xml_dir / f"FG-x{i:02d}.xml", a, b, values=vals)
    out = tmp_path / "out" / "dem.tif"
    out.parent.mkdir()
    r = subprocess.run([sys.executable, str(ROOT / "data_processing/convert_dem.py"), str(xml_dir), str(out)],
                       capture_output=True, text=True)
    return out, r


def _cell_center(tile_lat, tile_lon, r, c):
    lat = M.lat0 + tile_lat * M.tile_dlat + M.tile_dlat - (r + 0.5) * M.tile_dlat / M.tile_rows
    lon = M.lon0 + tile_lon * M.tile_dlon + (c + 0.5) * M.tile_dlon / M.tile_cols
    return lat, lon


CELLS = [(a, b, r, c) for a in range(2) for b in range(2) for r in range(3) for c in range(4)]


def _standard_to_legacy(std: np.ndarray, m) -> np.ndarray:
    """標準配置 → 旧 convert_dem の配置（relayout の逆変換、合成の旧 DEM を作るため）。"""
    s4 = std.reshape(m.n_tiles_lat, m.tile_rows, m.n_tiles_lon, m.tile_cols)
    old4 = s4.transpose(2, 1, 0, 3)[::-1, :, ::-1, :]
    return np.ascontiguousarray(old4).reshape(m.n_tiles_lon * m.tile_rows, m.n_tiles_lat * m.tile_cols)


# ── 1-2. convert_dem の配置・標準の軸 ─────────────────────────────────────────────

def test_01_02_convert_dem_writes_standard_north_up_layout(tmp_path):
    out, r = _convert_dir(tmp_path)
    assert r.returncode == 0, r.stderr
    with rasterio.open(out) as src:
        arr = src.read(1)
        assert arr.shape == (2 * 3, 2 * 4)  # 行 = 緯度、列 = 経度
        assert (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top) == pytest.approx(
            (139.0, 35.0, 139.032, 35.02))
        assert src.nodata == -9999.0
        for a, b, rr, cc in CELLS:
            lat, lon = _cell_center(a, b, rr, cc)
            row, col = src.index(lon, lat)  # 標準: x = 経度、y = 緯度
            assert arr[row, col] == _value(a, b, rr, cc)


def test_09_elevation_service_reads_every_cell(tmp_path):
    out, _ = _convert_dir(tmp_path)
    svc = ElevationService(str(out))
    assert svc.is_loaded()
    for a, b, rr, cc in CELLS:
        lat, lon = _cell_center(a, b, rr, cc)
        assert svc.get_elevation(lat, lon) == _value(a, b, rr, cc)
        assert svc.get_elevation_interpolated(lat, lon) == pytest.approx(_value(a, b, rr, cc))  # 画素中心 = 値


def test_04_interpolation_uses_pixel_centers(tmp_path):
    out, _ = _convert_dir(tmp_path)
    svc = ElevationService(str(out))
    lat0, lon0 = _cell_center(0, 0, 1, 1)
    _, lon1 = _cell_center(0, 0, 1, 2)  # 東隣の cell
    mid = svc.get_elevation_interpolated(lat0, (lon0 + lon1) / 2)
    assert mid == pytest.approx((_value(0, 0, 1, 1) + _value(0, 0, 1, 2)) / 2)


# ── 3-6. 決定的な順序・重複・nodata ────────────────────────────────────────────────

def test_03_input_order_is_sorted(tmp_path):
    src = (ROOT / "data_processing/convert_dem.py").read_text(encoding="utf-8")
    assert "xml_files = sorted(input_path.glob('*.xml'))" in src
    a, _ = _convert_dir(tmp_path / "a")
    b, _ = _convert_dir(tmp_path / "b", tiles=tuple(reversed(ALL_TILES)))
    assert rasterio.open(a).read(1).tolist() == rasterio.open(b).read(1).tolist()


def test_04b_duplicate_mesh_fails_closed(tmp_path):
    other = [v + 0.5 for v in [_value(0, 0, r, c) for r in range(3) for c in range(4)]]
    out, r = _convert_dir(tmp_path, extra=[((0, 0), other)])
    assert r.returncode == 2 and "同じ範囲の XML が複数" in r.stderr
    assert not out.exists() and not list(out.parent.glob("temp_*.tif"))


def test_05_06_missing_mesh_is_nodata_not_zero(tmp_path):
    out, r = _convert_dir(tmp_path, tiles=((0, 0), (1, 1)))
    assert r.returncode == 0, r.stderr
    lat, lon = _cell_center(0, 1, 0, 0)
    with rasterio.open(out) as src:
        arr = src.read(1)
        row, col = src.index(lon, lat)
    assert arr[row, col] == -9999.0
    assert ElevationService(str(out)).get_elevation(lat, lon) is None  # 海・未収録 ≠ 標高 0 m


# ── relayout = 修正版 convert_dem ─────────────────────────────────────────────────

def test_relayout_of_legacy_equals_fixed_converter(tmp_path):
    out, _ = _convert_dir(tmp_path)
    std = rasterio.open(out).read(1)
    legacy = _standard_to_legacy(std, M)
    got, missing = relayout.legacy_to_standard(legacy.copy(), 2, 2, 3, 4)
    assert missing == 0 and np.array_equal(got, std)
    # 旧 merge の 0 埋め tile と NaN は nodata になる
    legacy2 = legacy.copy()
    legacy2[0:3, 0:4] = 0.0  # 旧配置で 1 tile 分が 0（原本 tile 無し）
    legacy2[3, 5] = np.nan
    got2, missing2 = relayout.legacy_to_standard(legacy2, 2, 2, 3, 4)
    assert missing2 == 1 and int((got2 == -9999.0).sum()) == 12 + 1


def test_legacy_layout_dem_is_refused(tmp_path):
    out, _ = _convert_dir(tmp_path)
    std = rasterio.open(out).read(1)
    legacy_path = tmp_path / "legacy.tif"
    with rasterio.open(legacy_path, "w", driver="GTiff", width=8, height=6, count=1, dtype="float32", crs="EPSG:6668",
                       transform=from_bounds(35.0, 139.0, 35.02, 139.032, 8, 6)) as dst:  # 旧: x = 緯度
        dst.write(_standard_to_legacy(std, M), 1)
    svc = ElevationService(str(legacy_path))
    assert not svc.is_loaded() and svc.get_elevation(35.01, 139.01) is None  # fail closed


# ── 7-8, 11-12. 実 DEM（build node にある環境だけ）──────────────────────────────────

DEM = ROOT / "data_lake/validated/tokyo/dem/elevation.tif"
LEGACY = ROOT / "data_lake/_backup/dem_superseded_20261012/elevation.tif"
NEW_SHA = "837bb7042c15c9b5ccefebaaaae55d269616fc0ae8acc850f190b246a18d31d7"
# name: (lat, lon, 地理院 DEM5A（z15）, 修正前の backend の値)
KNOWN = {
    "新宿駅": (35.6896, 139.7006, 37.38, 30.69), "東京駅": (35.6812, 139.7671, 3.60, 3.66),
    "羽田空港": (35.5494, 139.7798, 3.69, 5.98), "高尾山山頂": (35.6251, 139.2436, 598.03, 423.95),
    "奥多摩駅": (35.8094, 139.0965, 339.37, 552.29), "八王子駅": (35.6556, 139.3389, 110.61, 102.89),
    "立川駅": (35.6980, 139.4138, 83.29, 78.93), "葛西臨海公園": (35.6413, 139.8612, 10.01, 9.15),
    "板橋区役所": (35.7512, 139.7093, 28.99, 19.01), "大田区役所": (35.5613, 139.7160, 3.58, 2.70),
    "青梅駅": (35.7903, 139.2588, 197.45, 195.60), "横浜駅": (35.4657, 139.6223, 3.58, 1.58),
    "川崎駅": (35.5308, 139.6970, 2.57, 3.24), "相模湖": (35.6150, 139.1880, 192.58, 276.84),
    "飯能駅": (35.8558, 139.3275, 108.17, 102.54), "二子玉川": (35.6115, 139.6266, 12.90, 12.01),
    "江戸川区役所": (35.7066, 139.8683, -1.43, -1.43), "足立区役所": (35.7750, 139.8040, 1.37, 2.01),
    "皇居": (35.6852, 139.7528, 23.27, 21.71), "雲取山付近": (35.8553, 139.0012, 1067.41, 800.31),
}


@pytest.fixture(scope="module")
def svc():
    if not DEM.is_file():
        pytest.skip("DEM が無い環境")
    s = ElevationService(str(DEM))
    if not s.is_loaded():
        pytest.fail("修正版 DEM が読み込めない")
    return s


def test_07_new_dem_is_standard_layout(svc):
    ds = svc.dataset
    assert (ds.width, ds.height) == (18000, 12000) and ds.crs.to_epsg() == 6668 and ds.nodata == -9999.0
    assert ds.res == pytest.approx((1 / 18000, 1 / 18000))
    assert tuple(ds.bounds) == pytest.approx((139.0, 35 + 1 / 3, 140.0, 36.0))


@pytest.mark.parametrize("name", sorted(KNOWN))
def test_08_known_points_match_dem5a(svc, name):
    lat, lon, ref, before = KNOWN[name]
    v = svc.get_elevation_interpolated(lat, lon)
    assert abs(v - ref) <= (3.0 if ref > 300 else 0.5), (name, v, ref, before)


def test_08b_known_defect_is_fixed(svc):
    """修正前は新宿 -6.69 m・板橋 -9.98 m・高尾山 -174 m・奥多摩 +213 m ずれていた。"""
    for name in ("新宿駅", "板橋区役所", "高尾山山頂", "奥多摩駅"):
        lat, lon, ref, before = KNOWN[name]
        now = svc.get_elevation_interpolated(lat, lon)
        assert abs(now - ref) < abs(before - ref) / 10, name


def test_11_legacy_and_new_dem_hold_the_same_values():
    """旧 artifact を正しい読み方で読んだ値 = 修正版 DEM を geotransform どおりに読んだ値（並べ替えだけ）。"""
    if not (DEM.is_file() and LEGACY.is_file()):
        pytest.skip("DEM / 旧 DEM が無い環境")
    old = rasterio.open(LEGACY).read(1)
    with rasterio.open(DEM) as new:
        arr = new.read(1)
        for name, (lat, lon, _, _) in KNOWN.items():
            lat, lon = lat + 1e-7, lon + 1e-7  # cell 境界ちょうど（例: 経度 139.0965 = 1737.0 cell）の丸め差を避ける
            o = float(old[audit.fgd_mosaic_rowcol(audit.MESH_5339, lat, lon)])
            r, c = new.index(lon, lat)
            assert arr[r, c] == pytest.approx(o) or (o == 0.0 and arr[r, c] == -9999.0), name


def test_12_registry_records_new_artifact_and_superseded_old():
    from app.services.dataset_definition_service import get_definition_service
    d = get_definition_service().get("TOKYO-DEM-001")
    assert d.artifact_sha256 == NEW_SHA and "north-up" in d.artifact_layout
    assert [s["sha256"][:8] for s in d.superseded_artifacts] == ["fdd8e3b3"]
    if DEM.is_file():
        h = hashlib.sha256()
        with DEM.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == NEW_SHA


# ── 15. PSEUDO generator ─────────────────────────────────────────────────────────

def test_15_pseudo_generator_has_no_transpose_workaround():
    src = (ROOT / "scripts/derive/generate_pseudo_inland_flood.py").read_text(encoding="utf-8")
    assert "np.flip(arr.T" not in src and "_canonicalize_swapped_geographic" not in src
    assert "緯度経度が入れ替わった旧 DEM は使えない" in src and "return 2" in src


def test_gsi_png_decode_and_tile_pixel():
    assert audit.decode_gsi_png_height(0, 0, 100) == 1.0
    assert audit.decode_gsi_png_height(128, 0, 0) is None
    assert audit.decode_gsi_png_height(255, 255, 156) == pytest.approx(-1.0)
    assert audit.gsi_tile_pixel(35.6896, 139.7006)[:2] == (29099, 12902)  # x = 319.7006/360*2^15 = 29099.86


def test_20_tests_are_read_only(tmp_path):
    before = DEM.stat().st_mtime_ns if DEM.is_file() else None
    _convert_dir(tmp_path)
    assert (DEM.stat().st_mtime_ns if DEM.is_file() else None) == before
