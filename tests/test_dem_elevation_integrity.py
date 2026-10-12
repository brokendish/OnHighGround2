"""
DEM-ELEVATION-INTEGRITY-AUDIT（2026-10-12）: DEM の座標契約と backend の読み取り位置の監査。

結論（地理院 DEM5A タイル 300 点比較）:
  - DEM の値そのものは DEM5A と一致（正しい読み方で差の中央値 0.09 m、平地の最大 0.25 m）
  - backend の読み方（geotransform のまま x=緯度・y=経度）は 3 次メッシュ内で別の画素を読む
    （差の中央値 4.40 m、p95 169 m、最大 459 m）。原因は convert_dem.py が tile の配置だけを転置したこと。
このテストは原因を実際の convert_dem.py で再現し、正しい読み方（fgd_mosaic_rowcol）を固定する。
backend の読み取りはこの phase では変えていない（次 phase で修正）。現状の誤りは known defect として固定する。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
rasterio = pytest.importorskip("rasterio")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass は定義中に自 module を参照する
    spec.loader.exec_module(mod)
    return mod


audit = _load("audit_dem_elevation", "scripts/validate/audit_dem_elevation.py")
convert_dem = _load("convert_dem", "data_processing/convert_dem.py")
from elevation_service import ElevationService  # noqa: E402

# 合成 1 次メッシュ: 2 × 2 tile、tile 内 緯度 3 × 経度 4 格子（緯度 0.01°・経度 0.016° の tile）
M = audit.FgdMosaic(lat0=35.0, lon0=139.0, tile_dlat=0.01, tile_dlon=0.016, n_tiles_lat=2, n_tiles_lon=2,
                    tile_rows=3, tile_cols=4)


def _value(tile_lat, tile_lon, r, c):
    """格子ごとに一意な値: 緯度 tile・経度 tile・tile 内の行（北→南）・列（西→東）。"""
    return 1000 * tile_lat + 100 * tile_lon + 10 * r + c + 1


def _fgd_xml(path: Path, tile_lat: int, tile_lon: int, start=(0, 0), values=None):
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
<gml:coverageFunction><gml:GridFunction><gml:sequenceRule order="+x-y">Linear</gml:sequenceRule><gml:startPoint>{start[0]} {start[1]}</gml:startPoint></gml:GridFunction></gml:coverageFunction>
</coverage></DEM></Dataset>""", encoding="utf-8")
    return path


def _mosaic(tmp_path, tiles=((0, 0), (0, 1), (1, 0), (1, 1)), extra=None):
    tifs = []
    for i, (tla, tlo) in enumerate(tiles):
        xml = _fgd_xml(tmp_path / f"t{i}.xml", tla, tlo)
        tif = tmp_path / f"t{i}.tif"
        convert_dem.DEMConverter().convert(str(xml), str(tif))
        tifs.append(str(tif))
    for i, (xml_args, kw) in enumerate(extra or []):
        xml = _fgd_xml(tmp_path / f"x{i}.xml", *xml_args, **kw)
        tif = tmp_path / f"x{i}.tif"
        convert_dem.DEMConverter().convert(str(xml), str(tif))
        tifs.append(str(tif))
    out = tmp_path / "mosaic.tif"
    convert_dem.merge_geotiffs(tifs, str(out))
    return out


def _cell_center(tile_lat, tile_lon, r, c):
    lat = M.lat0 + tile_lat * M.tile_dlat + M.tile_dlat - (r + 0.5) * M.tile_dlat / M.tile_rows
    lon = M.lon0 + tile_lon * M.tile_dlon + (c + 0.5) * M.tile_dlon / M.tile_cols
    return lat, lon


CELLS = [(a, b, r, c) for a in range(2) for b in range(2) for r in range(3) for c in range(4)]


# ── 1-4. 座標契約（実際の convert_dem.py で再現）─────────────────────────────────

def test_01_03_convert_dem_transposes_tile_placement_only(tmp_path):
    out = _mosaic(tmp_path)
    with rasterio.open(out) as src:
        arr = src.read(1)
        assert arr.shape == M.shape == (6, 8)
        # geotransform は x=緯度・y=経度（convert_dem の署名）
        assert src.bounds.left == pytest.approx(35.0) and src.bounds.bottom == pytest.approx(139.0)
    for a, b, r, c in CELLS:
        rc = audit.fgd_mosaic_rowcol(M, *_cell_center(a, b, r, c))
        assert arr[rc] == _value(a, b, r, c)  # 正しい読み方は全 cell で一致


def test_02_backend_lookup_reads_wrong_cell_inside_tile(tmp_path):
    """backend（geotransform のまま）は正しい tile を引くが tile 内では別の cell を読む（known defect）。"""
    svc = ElevationService(str(_mosaic(tmp_path)))
    wrong = 0
    for a, b, r, c in CELLS:
        got = svc.get_elevation(*_cell_center(a, b, r, c))
        assert got is not None and (got - 1) // 100 == _value(a, b, r, c) // 100  # 同じ tile（千・百の位）
        wrong += got != _value(a, b, r, c)
    assert wrong >= len(CELLS) // 2


def test_04_pixel_contract_is_cell_with_northwest_origin(tmp_path):
    out = _mosaic(tmp_path)
    with rasterio.open(out) as src:
        arr = src.read(1)
    lat, lon = _cell_center(0, 0, 0, 0)
    eps = 1e-9
    # cell の北西角は自 cell、南東角のわずか外は隣の cell（floor）
    nw = (M.lat0 + M.tile_dlat - eps, M.lon0 + eps)
    assert arr[audit.fgd_mosaic_rowcol(M, *nw)] == _value(0, 0, 0, 0)
    se_out = (M.lat0 + M.tile_dlat - M.tile_dlat / 3 - eps, M.lon0 + M.tile_dlon / 4 + eps)
    assert arr[audit.fgd_mosaic_rowcol(M, *se_out)] == _value(0, 0, 1, 1)
    assert audit.fgd_mosaic_rowcol(M, 34.99, 139.0) is None


# ── 7-8. nodata / overlap ───────────────────────────────────────────────────────

def test_07_uncovered_tile_is_zero_filled_not_nodata(tmp_path):
    """merge は nodata 未設定のため、原本 tile が無い範囲を 0 で埋める（backend は 0 m を返す）。"""
    out = _mosaic(tmp_path, tiles=((0, 0), (1, 1)))
    with rasterio.open(out) as src:
        assert src.nodata is None
        arr = src.read(1)
    assert arr[audit.fgd_mosaic_rowcol(M, *_cell_center(0, 1, 0, 0))] == 0.0
    assert ElevationService(str(out)).get_elevation(*_cell_center(0, 1, 0, 0)) == 0.0


def test_07b_void_minus_9999_is_none_in_backend(tmp_path):
    vals = [-9999.0] * (M.tile_rows * M.tile_cols)
    out = _mosaic(tmp_path, tiles=((0, 0),), extra=[((1, 1), {"values": vals})])
    svc = ElevationService(str(out))
    assert svc.get_elevation(*_cell_center(1, 1, 0, 0)) is None


def test_08_overlap_first_file_wins(tmp_path):
    """同じ tile の XML が 2 つあると先に結合した方が残る（ファイル順に依存する）。"""
    other = [v + 0.5 for v in [_value(0, 0, r, c) for r in range(3) for c in range(4)]]
    out = _mosaic(tmp_path, extra=[((0, 0), {"values": other})])  # 4 tile の後に同じ (0, 0) tile をもう 1 つ
    with rasterio.open(out) as src:
        arr = src.read(1)
    assert arr[audit.fgd_mosaic_rowcol(M, *_cell_center(0, 0, 0, 0))] == _value(0, 0, 0, 0)


# ── 5, 6, 9, 12. 実 DEM の既知地点（DEM がある環境だけ）────────────────────────────

DEM = ROOT / "data_lake/validated/tokyo/dem/elevation.tif"
# 地理院 DEM5A タイル（z15）の値と、2026-10-12 時点の backend の値
KNOWN = {  # name: (lat, lon, DEM5A, backend_now)
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
def dem():
    if not DEM.is_file():
        pytest.skip("DEM が無い環境")
    with rasterio.open(DEM) as src:
        yield src.read(1)


@pytest.mark.parametrize("name", sorted(KNOWN))
def test_05_known_points_corrected_reading_matches_dem5a(dem, name):
    lat, lon, ref, _ = KNOWN[name]
    v = float(dem[audit.fgd_mosaic_rowcol(audit.MESH_5339, lat, lon)])
    assert abs(v - ref) <= (3.0 if ref > 300 else 0.5), (name, v, ref)


def test_06_12_backend_lookup_defect_is_pinned(dem):
    """現状の backend は既知地点で数 m〜数百 m ずれる（false-safe の原因。修正は次 phase）。"""
    svc = ElevationService(str(DEM))
    errs = {n: svc.get_elevation_interpolated(lat, lon) - ref for n, (lat, lon, ref, _) in KNOWN.items()}
    assert abs(errs["新宿駅"]) > 5 and abs(errs["板橋区役所"]) > 9 and abs(errs["高尾山山頂"]) > 100
    for n, (lat, lon, _, now) in KNOWN.items():
        assert svc.get_elevation_interpolated(lat, lon) == pytest.approx(now, abs=0.01), n


def test_09_mesh_5339_grid_alignment(dem):
    m = audit.MESH_5339
    assert dem.shape == m.shape == (12000, 18000)
    assert m.tile_dlat / m.tile_rows == pytest.approx(1 / 18000) and m.tile_dlon / m.tile_cols == pytest.approx(1 / 18000)
    with rasterio.open(DEM) as src:
        assert (src.bounds.left, src.bounds.bottom) == pytest.approx((m.lat0, m.lon0), abs=1e-9)


def test_11_pseudo_generator_uses_the_same_transposed_contract():
    """PSEUDO generator も geotransform（x=緯度）を前提に全体転置するため、backend と同じ誤りを継承する。"""
    src = (ROOT / "scripts/derive/generate_pseudo_inland_flood.py").read_text(encoding="utf-8")
    assert "np.flip(arr.T, axis=(0, 1))" in src and "元データは x=lat, y=lon として保存されている" in src


def test_gsi_png_decode_and_tile_pixel():
    assert audit.decode_gsi_png_height(0, 0, 100) == 1.0
    assert audit.decode_gsi_png_height(128, 0, 0) is None
    assert audit.decode_gsi_png_height(255, 255, 156) == pytest.approx(-1.0)
    assert audit.gsi_tile_pixel(35.6896, 139.7006)[:2] == (29099, 12902)  # x = 319.7006/360*2^15 = 29099.86


def test_14_audit_is_read_only(tmp_path):
    before = DEM.stat().st_mtime_ns if DEM.is_file() else None
    _mosaic(tmp_path)
    assert (DEM.stat().st_mtime_ns if DEM.is_file() else None) == before
