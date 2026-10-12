"""
EVACUATION-HAZARD-GEOMETRY-SAFETY（2026-10-12）: Reachable Safe Area（RSA）が危険区域を見落とさない。

旧実装の問題:
  - bbox_only でロードした lowland_poor_drainage の entry は coords を持たず、RSA が KeyError → /api/evacuation が 500
    （横浜 35.4437,139.6380・川崎 35.5308,139.7030 で再現）
  - flood / tsunami / storm_surge / landslide は numpy の bbox 配列だけで RSA の polygon store に無く、RSA は
    これらを差し引かずに安全範囲を描いていた（false-safe）
  - 不正な polygon は黙って捨て、差し引き失敗時は円全体を安全範囲として返していた
対策: bbox_only でも外周 ring を一時ファイル（_RingStore）に残し、RSA は全ロード済み hazard の形状を差し引く。
形状を取得できない・演算に失敗したら status="unavailable"（exists=None）にし、安全範囲を出さない。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import geometry_utils as gu  # noqa: E402
import hazard_service as hsm  # noqa: E402
from hazard_service import HazardService  # noqa: E402

shapely = pytest.importorskip("shapely")
from shapely.geometry import Point, Polygon, shape  # noqa: E402

YOKOHAMA = (35.4437, 139.6380)
KAWASAKI = (35.5308, 139.7030)
TOKYO_OK = (35.6896, 139.7006)      # 新宿（周辺に hazard を置かない）
KANAGAWA_OK = (35.5710, 139.3730)   # 相模原（同上）


def _square(lat, lon, half_deg, offset_lon=0.0):
    c = lon + offset_lon
    return [[c - half_deg, lat - half_deg], [c + half_deg, lat - half_deg], [c + half_deg, lat + half_deg],
            [c - half_deg, lat + half_deg], [c - half_deg, lat - half_deg]]


def _fc(path: Path, rings, props=None, multi=False):
    feats = []
    for r in rings:
        geom = {"type": "MultiPolygon", "coordinates": [[r]]} if multi else {"type": "Polygon", "coordinates": [r]}
        feats.append({"type": "Feature", "properties": props or {}, "geometry": geom})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    return path


def _half_east(lat, lon):
    """点の東側半分（経度 lon 〜 lon+0.05）を覆う矩形。"""
    return [[lon, lat - 0.05], [lon + 0.05, lat - 0.05], [lon + 0.05, lat + 0.05], [lon, lat + 0.05], [lon, lat - 0.05]]


def _rsa(hs, lat, lon, r=300):
    return gu.calc_reachable_safe_area(lat, lon, r, hs.hazard_rings_in_bbox)


def _circle_area(r):
    return Point(0, 0).buffer(r, resolution=32).area


# ── 1-2. bbox-only polygon で 500 にならず、無視もしない ──────────────────────────────

def test_01_bbox_only_lowland_no_longer_raises(tmp_path):
    hs = HazardService()
    hs.load_geojson_streaming("lowland_poor_drainage", _fc(tmp_path / "l.geojson", [_half_east(*YOKOHAMA)]), bbox_only=True)
    assert "coords" not in hs.get_polygon_store()["lowland_poor_drainage"][0]  # bbox-only のまま
    res = _rsa(hs, *YOKOHAMA)
    assert res["status"] == "computed" and res["exists"] is True


@pytest.mark.parametrize("hazard_type", ["lowland_poor_drainage", "tsunami", "flood", "storm_surge", "landslide"])
def test_02_bbox_only_hazard_is_subtracted_not_ignored(tmp_path, hazard_type):
    hs = HazardService()
    hs.load_geojson_streaming(hazard_type, _fc(tmp_path / "h.geojson", [_half_east(*KAWASAKI)]), bbox_only=True)
    res = _rsa(hs, *KAWASAKI)
    assert res["status"] == "computed"
    assert res["area_m2"] == pytest.approx(_circle_area(300) / 2, rel=0.02)  # 東半分が差し引かれる


# ── 3. full geometry の取得 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("loader", ["load", "load_geojson_streaming", "load_geojsonl"])
def test_03_ring_store_returns_full_geometry(tmp_path, loader):
    rings = [_square(35.5, 139.5, 0.001), _square(35.6, 139.6, 0.002, 0.01)]
    hs = HazardService()
    if loader == "load_geojsonl":
        p = tmp_path / "t.geojsonl"
        p.write_text("\n".join(json.dumps({"type": "Feature", "properties": {},
                                           "geometry": {"type": "Polygon", "coordinates": [r]}}) for r in rings))
        hs.load_geojsonl("tsunami", p, bbox_only=True)
    else:
        getattr(hs, loader)("tsunami", _fc(tmp_path / "t.geojson", rings, multi=True), bbox_only=True)
    store = hs._ring_stores["tsunami"]
    assert len(store) == len(hs._tsunami_bboxes_np) == 2
    for i, r in enumerate(rings):
        np.testing.assert_array_equal(store.ring(i), np.asarray(r, dtype=np.float64))


def test_03b_failed_file_load_rolls_back_ring_store(tmp_path):
    hs = HazardService()
    hs.load_geojson_streaming("tsunami", _fc(tmp_path / "a.geojson", [_square(35.5, 139.5, 0.001)]), bbox_only=True)
    bad = tmp_path / "b.geojson"
    bad.write_text('{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Polygon",'
                   '"coordinates":[[[139.6,35.6],[139.7,35.6],[139.7,35.7],[139.6,35.6]]]}}, BROKEN', encoding="utf-8")
    hs.load_geojson_streaming("tsunami", bad, bbox_only=True)
    hs.load_geojson_streaming("tsunami", _fc(tmp_path / "c.geojson", [_square(35.8, 139.8, 0.002)]), bbox_only=True)
    store = hs._ring_stores["tsunami"]
    assert len(store) == len(hs._tsunami_bboxes_np) == 2  # 失敗した file の ring は残らず、番号がずれない
    np.testing.assert_array_equal(store.ring(1), np.asarray(_square(35.8, 139.8, 0.002), dtype=np.float64))


# ── 4. 形状を取得できないときは fail-closed ───────────────────────────────────────────

def test_04_store_failure_makes_rsa_unavailable(tmp_path):
    hs = HazardService()
    hs.load_geojson_streaming("tsunami", _fc(tmp_path / "t.geojson", [_half_east(*KAWASAKI)]), bbox_only=True)
    hs._ring_stores["tsunami"].error = "OSError: disk full"
    res = _rsa(hs, *KAWASAKI)
    assert res["status"] == "unavailable" and res["exists"] is None and res["geometry"] is None
    assert res["unavailable_hazard_types"] == ["tsunami"] and res["area_m2"] is None


def test_04b_write_error_during_load_marks_store_failed(tmp_path, monkeypatch):
    def boom(self):
        raise OSError("No space left on device")
    monkeypatch.setattr(hsm._RingStore, "_flush", boom)
    hs = HazardService()
    hs.load_geojson_streaming("lowland_poor_drainage", _fc(tmp_path / "l.geojson", [_half_east(*YOKOHAMA)]), bbox_only=True)
    assert hs.is_loaded("lowland_poor_drainage")  # 点の判定（bbox）は従来どおり使える
    assert hs._ring_stores["lowland_poor_drainage"].error
    assert _rsa(hs, *YOKOHAMA)["status"] == "unavailable"


def test_04c_lookup_or_geometry_exception_is_unavailable_not_full_circle():
    def provider_raises(*a):
        raise RuntimeError("mmap failed")
    assert gu.calc_reachable_safe_area(*KAWASAKI, 300, provider_raises)["status"] == "unavailable"
    bad = [np.array([[139.70, 35.53], [139.71, 35.53], [np.nan, 35.54]], dtype=np.float32)] * 3
    res = gu.calc_reachable_safe_area(*KAWASAKI, 300, lambda *a: (bad, []))
    assert res["status"] in ("unavailable", "computed")
    if res["status"] == "computed":  # 例外にならなかった場合でも円全体を「安全」にしていない
        assert res["area_m2"] <= _circle_area(300) * 1.0001


def test_04d_entry_without_coords_or_ring_is_unavailable():
    hs = HazardService()
    hs._polygons["lowland_poor_drainage"] = [{"bbox": (35.52, 139.69, 35.54, 139.71)}]  # 旧形式（形状なし）
    res = _rsa(hs, *KAWASAKI)
    assert res["status"] == "unavailable" and res["unavailable_hazard_types"] == ["lowland_poor_drainage"]


# ── 5. false-safe にならない ─────────────────────────────────────────────────────────

def test_05_safe_area_never_overlaps_any_hazard(tmp_path):
    rng = np.random.default_rng(20261012)
    lat, lon = KAWASAKI
    rings = []
    for _ in range(40):  # 円の周辺に大小の矩形・自己交差 ring を散らす
        cy, cx = lat + rng.uniform(-0.004, 0.004), lon + rng.uniform(-0.004, 0.004)
        h = rng.uniform(0.0002, 0.001)
        rings.append(_square(cy, cx, h))
    bowtie = [[lon - 0.002, lat - 0.002], [lon + 0.002, lat + 0.002], [lon + 0.002, lat - 0.002],
              [lon - 0.002, lat + 0.002], [lon - 0.002, lat - 0.002]]  # 自己交差（不正）
    hs = HazardService()
    hs.load_geojson_streaming("tsunami", _fc(tmp_path / "t.geojson", rings[:20]), bbox_only=True)
    hs.load_geojson_streaming("flood", _fc(tmp_path / "f.geojson", rings[20:]), bbox_only=True)
    hs.load_geojson_streaming("lowland_poor_drainage", _fc(tmp_path / "l.geojson", [bowtie]), bbox_only=True)
    res = _rsa(hs, lat, lon, r=400)
    assert res["status"] == "computed" and res["geometry"]
    hazard = shapely.union_all([shapely.make_valid(Polygon(r)) for r in rings + [bowtie]])
    overlap = shape(res["geometry"]).intersection(hazard).area
    assert overlap < 1e-12  # 度² ≒ 0.01 m² 未満


def test_05b_old_store_only_behaviour_would_have_been_false_safe(tmp_path):
    """tsunami は numpy 配列だけで polygon store に入らない。旧 RSA はこれを差し引けなかった。"""
    hs = HazardService()
    hs.load_geojson_streaming("tsunami", _fc(tmp_path / "t.geojson", [_half_east(*KAWASAKI)]), bbox_only=True)
    assert not hs.get_polygon_store().get("tsunami")
    assert _rsa(hs, *KAWASAKI)["area_m2"] < _circle_area(300) * 0.6


def test_05c_inland_detail_without_coords_is_inside_not_outside():
    hs = HazardService()
    hs._polygons["inland_flood"] = [{"bbox": (35.52, 139.69, 35.54, 139.71), "properties": {"depth": 1.0}}]
    assert hs.check_inland_flood_detail(*KAWASAKI)["status"] == "inside"


# ── 6-9. 横浜・川崎・東京／神奈川の正常地点 ───────────────────────────────────────────

def test_06_yokohama_fixture_inside_tsunami_has_no_safe_area(tmp_path):
    """横浜（TTI 1.4 分 → 半径 109m）: 円全体が津波浸水域なら安全範囲なし（旧: 500）。"""
    lat, lon = YOKOHAMA
    hs = HazardService()
    hs.load_geojson_streaming("tsunami", _fc(tmp_path / "t.geojson", [_square(lat, lon, 0.01)]), bbox_only=True)
    hs.load_geojson_streaming("lowland_poor_drainage", _fc(tmp_path / "l.geojson", [_square(lat, lon, 0.03)]), bbox_only=True)
    res = gu.calc_reachable_safe_area(lat, lon, 1.3 * 1.4 * 60, hs.hazard_rings_in_bbox)
    assert res["status"] == "computed" and res["exists"] is False and res["area_m2"] == 0


def test_07_kawasaki_fixture_partial_hazard(tmp_path):
    lat, lon = KAWASAKI
    hs = HazardService()
    hs.load_geojson_streaming("lowland_poor_drainage", _fc(tmp_path / "l.geojson", [_half_east(lat, lon)]), bbox_only=True)
    hs.load("inland_flood", _fc(tmp_path / "i.geojson", [_square(lat, lon - 0.002, 0.0005)]))
    res = gu.calc_reachable_safe_area(lat, lon, 1.3 * 4.2 * 60, hs.hazard_rings_in_bbox)
    assert res["status"] == "computed" and res["exists"] is True
    assert 0 < res["area_m2"] < _circle_area(1.3 * 4.2 * 60) / 2


@pytest.mark.parametrize("point", [TOKYO_OK, KANAGAWA_OK])
def test_08_09_points_without_nearby_hazard_keep_full_circle(tmp_path, point):
    hs = HazardService()
    hs.load_geojson_streaming("tsunami", _fc(tmp_path / "t.geojson", [_square(35.0, 139.0, 0.01)]), bbox_only=True)
    res = _rsa(hs, *point, r=500)
    assert res["status"] == "computed" and res["area_m2"] == pytest.approx(_circle_area(500), rel=1e-6)


# ── 10-13. 判定・順位・tsunami の回帰（ring store は点の判定に影響しない）──────────────────

def test_10_13_point_assessment_unchanged_by_ring_store(tmp_path, monkeypatch):
    lat, lon = KAWASAKI
    files = {t: _fc(tmp_path / f"{t}.geojson", [_half_east(lat, lon)]) for t in
             ("tsunami", "flood", "storm_surge", "landslide", "lowland_poor_drainage")}
    probes = [(lat, lon + 0.001), (lat, lon - 0.001), (lat + 0.2, lon)]

    def assess(hs):
        return [(hs.check_hazards(a, b), hs.assess_candidate(a, b), hs.get_tsunami_centroid_distance_m(a, b))
                for a, b in probes]

    with_store = HazardService()
    for t, f in files.items():
        with_store.load_geojson_streaming(t, f, bbox_only=True)
    monkeypatch.setattr(hsm._RingStore, "add", lambda self, ring: -1)  # ring store を使わない場合
    without = HazardService()
    for t, f in files.items():
        without.load_geojson_streaming(t, f, bbox_only=True)
    assert assess(with_store) == assess(without)
    np.testing.assert_array_equal(with_store._tsunami_bboxes_np, without._tsunami_bboxes_np)
    assert with_store._tsunami_centroids == without._tsunami_centroids


def test_ring_store_keeps_only_offsets_in_memory(tmp_path):
    hs = HazardService()
    hs.load_geojson_streaming("flood", _fc(tmp_path / "f.geojson", [_square(35.5, 139.5, 0.001)] * 1000), bbox_only=True)
    store = hs._ring_stores["flood"]
    assert store._offsets.itemsize == 4 and len(store._offsets) == 1001 and len(store._buf) == 0


def test_app_public_and_ui_follow_the_contract():
    app = (ROOT / "backend/app_public.py").read_text(encoding="utf-8")
    assert "hazard_rings=hazard_engine.hazard_rings_in_bbox" in app and "hazard_polygon_store=" not in app
    ui = (ROOT / "frontend/js/ui.js").read_text(encoding="utf-8")
    i = ui.index("function displayRsa")
    assert ui.index("rsa.status === 'unavailable'", i) < ui.index("L.geoJSON(rsa.geometry", i)
    src = (ROOT / "backend/geometry_utils.py").read_text(encoding="utf-8")
    assert "using full reachable circle" not in src and "except Exception:\n                pass" not in src
