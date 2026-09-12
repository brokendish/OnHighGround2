"""
test_hazard_service_streaming_loader.py —
HAZARD-ENGINE-LARGE-DATASET-MEMORY-BLOCKER / HAZARD-ENGINE-VERSIONED-
LAYOUT-MISMATCH remediation テスト。

HazardService.load_geojson_streaming()（ijson streaming、
HAZARD-ENGINE-LARGE-DATASET-MEMORY-BLOCKER対応で新設）が:
  - 通常GeoJSON FeatureCollectionをjson.load()せず、featureを1件ずつ
    処理・破棄すること
  - 既存load()と完全に同じbbox値・feature数・numpy配列を生成すること
    （semantic equivalence）
  - malformed JSONの場合、途中まで読めていてもpartial loadを最終状態へ
    反映せず、is_loaded()==Falseのまま・server-side ERRORログのみ残す
    こと（load()/load_geojsonl()と同じfail-open契約）
  - check_point/assess_candidateの判定結果がlegacy load()と一致する
    こと
を検証する。

app_public.py起動時ローダーのregion配下rglob discoveryパターン
（backend/hazard/{type}/{region}/*.geojson）も、実際のディレクトリ
構造をtmp_path上に再現して検証する（app_public.py自体はimportしない
——既存慣習どおり、test_hazards_api_error_response.pyのコメント参照）。
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hazard_service import HazardService  # noqa: E402


def _make_polygon_feature(props: dict, seed: int = 0) -> dict:
    base_lon, base_lat = 139.0 + (seed % 10) * 0.01, 35.0 + (seed % 7) * 0.01
    coords = [
        [base_lon, base_lat],
        [base_lon + 0.001, base_lat],
        [base_lon + 0.001, base_lat + 0.001],
        [base_lon, base_lat + 0.001],
        [base_lon, base_lat],
    ]
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


def _write_feature_collection(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)


def _flood_features(n: int) -> list[dict]:
    return [_make_polygon_feature({"flood_rank": (i % 5) + 1}, seed=i) for i in range(n)]


def _surge_features(n: int) -> list[dict]:
    return [_make_polygon_feature({"storm_surge_rank": i % 8}, seed=i) for i in range(n)]


def _tsunami_features(n: int) -> list[dict]:
    return [_make_polygon_feature({"tsunami_depth": i % 6}, seed=i) for i in range(n)]


def _landslide_features(n: int) -> list[dict]:
    # 偶数indexはspecial（特別警戒区域）、奇数indexはwarning（警戒区域）。
    return [
        _make_polygon_feature(
            {"zone_type": "special" if i % 2 == 0 else "warning"}, seed=i
        )
        for i in range(n)
    ]


def _lowland_features(n: int) -> list[dict]:
    return [_make_polygon_feature({"risk_level": i % 3}, seed=i) for i in range(n)]


# ── E. streaming bbox == legacy bbox（semantic equivalence） ──────────────────

def test_E_streaming_bbox_equals_legacy_load_bbox(tmp_path):
    path = tmp_path / "flood.geojson"
    _write_feature_collection(path, _flood_features(500))

    svc_legacy = HazardService()
    svc_legacy.load("flood", path, bbox_only=True)

    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("flood", path, bbox_only=True)

    assert svc_legacy.polygon_count("flood") == svc_streaming.polygon_count("flood") == 500
    assert np.array_equal(svc_legacy._flood_bboxes_np, svc_streaming._flood_bboxes_np)
    assert svc_legacy._flood_bboxes_np.dtype == svc_streaming._flood_bboxes_np.dtype == np.float32


def test_E_streaming_bbox_equals_legacy_load_bbox_storm_surge(tmp_path):
    path = tmp_path / "storm_surge.geojson"
    _write_feature_collection(path, _surge_features(500))

    svc_legacy = HazardService()
    svc_legacy.load("storm_surge", path, bbox_only=True)

    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("storm_surge", path, bbox_only=True)

    assert svc_legacy.polygon_count("storm_surge") == svc_streaming.polygon_count("storm_surge") == 500
    assert np.array_equal(svc_legacy._storm_surge_bboxes_np, svc_streaming._storm_surge_bboxes_np)


# ── HAZARD-LOAD-JSONLOAD-TRANSIENT-PEAK-RESIDUAL Phase B0 ──────────────────────
# tsunami / landslide / lowland_poor_drainage も load_geojson_streaming() 経由
# へ切り替える（app_public.py呼び出し元も本Phaseで切替済み）。保持データの
# 最終semanticはlegacy load()と完全に同一であることを検証する。

# ── A/B/C. tsunami: streaming bbox/centroid == legacy、navigation等価性 ────────

def test_A_tsunami_streaming_bbox_and_centroid_equal_legacy(tmp_path):
    path = tmp_path / "tsunami.geojson"
    _write_feature_collection(path, _tsunami_features(300))

    svc_legacy = HazardService()
    svc_legacy.load("tsunami", path, bbox_only=True)

    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("tsunami", path, bbox_only=True)

    assert svc_legacy.polygon_count("tsunami") == svc_streaming.polygon_count("tsunami") == 300
    assert np.array_equal(svc_legacy._tsunami_bboxes_np, svc_streaming._tsunami_bboxes_np)
    assert svc_legacy._tsunami_bboxes_np.dtype == svc_streaming._tsunami_bboxes_np.dtype == np.float32
    # centroidはbbox配列と同じ行indexで対応するため、リスト全体が完全一致すること
    assert svc_legacy._tsunami_centroids == svc_streaming._tsunami_centroids


def test_B_tsunami_check_point_and_centroid_distance_equivalence(tmp_path):
    path = tmp_path / "tsunami.geojson"
    _write_feature_collection(path, [_make_polygon_feature({"tsunami_depth": 2}, seed=0)])

    svc_legacy = HazardService()
    svc_legacy.load("tsunami", path, bbox_only=True)
    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("tsunami", path, bbox_only=True)

    hit_lat, hit_lon = 35.0005, 139.0005
    miss_lat, miss_lon = 50.0, 150.0

    assert svc_legacy.check_point(hit_lat, hit_lon, "tsunami") is True
    assert svc_streaming.check_point(hit_lat, hit_lon, "tsunami") is True
    assert svc_legacy.check_point(miss_lat, miss_lon, "tsunami") is False
    assert svc_streaming.check_point(miss_lat, miss_lon, "tsunami") is False

    dist_legacy = svc_legacy.get_tsunami_centroid_distance_m(hit_lat, hit_lon)
    dist_streaming = svc_streaming.get_tsunami_centroid_distance_m(hit_lat, hit_lon)
    assert dist_legacy is not None and dist_streaming is not None
    assert dist_legacy == pytest.approx(dist_streaming)


def test_C_tsunami_assess_candidate_equivalence(tmp_path):
    path = tmp_path / "tsunami.geojson"
    _write_feature_collection(path, [_make_polygon_feature({"tsunami_depth": 2}, seed=0)])

    svc_legacy = HazardService()
    svc_legacy.load("tsunami", path, bbox_only=True)
    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("tsunami", path, bbox_only=True)

    assert svc_legacy.assess_candidate(35.0005, 139.0005).get("tsunami") == "inside"
    assert svc_streaming.assess_candidate(35.0005, 139.0005).get("tsunami") == "inside"
    assert svc_legacy.assess_candidate(50.0, 150.0).get("tsunami") == "outside"
    assert svc_streaming.assess_candidate(50.0, 150.0).get("tsunami") == "outside"


# ── D/E/F. landslide: streaming bbox/properties == legacy、severity等価性 ──────

def test_D_landslide_streaming_bbox_and_props_equal_legacy(tmp_path):
    path = tmp_path / "landslide.geojson"
    _write_feature_collection(path, _landslide_features(300))

    svc_legacy = HazardService()
    svc_legacy.load("landslide", path, bbox_only=True)

    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("landslide", path, bbox_only=True)

    assert svc_legacy.polygon_count("landslide") == svc_streaming.polygon_count("landslide") == 300
    assert np.array_equal(svc_legacy._landslide_bboxes_np, svc_streaming._landslide_bboxes_np)
    # propertiesはbbox配列と同じ行indexで対応するため、順序も含めて完全一致すること
    assert svc_legacy._landslide_props == svc_streaming._landslide_props


def test_E_landslide_properties_not_dropped(tmp_path):
    """単にbbox_onlyへ落とすのではなく、既存navigation logicが参照する
    zone_typeプロパティが streaming loader でも欠落しないことを確認する。"""
    path = tmp_path / "landslide.geojson"
    _write_feature_collection(path, _landslide_features(10))

    svc = HazardService()
    svc.load_geojson_streaming("landslide", path, bbox_only=True)

    assert len(svc._landslide_props) == 10
    assert all("zone_type" in p for p in svc._landslide_props)
    assert svc._landslide_props[0]["zone_type"] == "special"  # seed=0 → 偶数
    assert svc._landslide_props[1]["zone_type"] == "warning"  # seed=1 → 奇数


def test_F_landslide_check_landslide_detail_equivalence(tmp_path):
    special_feature = _make_polygon_feature({"zone_type": "special"}, seed=0)
    warning_feature = _make_polygon_feature({"zone_type": "warning"}, seed=1)

    special_path = tmp_path / "special.geojson"
    warning_path = tmp_path / "warning.geojson"
    _write_feature_collection(special_path, [special_feature])
    _write_feature_collection(warning_path, [warning_feature])

    svc_legacy = HazardService()
    svc_legacy.load("landslide", special_path, bbox_only=True)
    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("landslide", special_path, bbox_only=True)

    # special zoneの座標（seed=0 → base_lon=139.0, base_lat=35.0）
    detail_legacy = svc_legacy.check_landslide_detail(35.0005, 139.0005)
    detail_streaming = svc_streaming.check_landslide_detail(35.0005, 139.0005)
    assert detail_legacy == detail_streaming == {"status": "inside", "level": "critical", "zone_type": "special"}

    svc_legacy_w = HazardService()
    svc_legacy_w.load("landslide", warning_path, bbox_only=True)
    svc_streaming_w = HazardService()
    svc_streaming_w.load_geojson_streaming("landslide", warning_path, bbox_only=True)

    # warning zoneの座標（seed=1 → base_lon=139.01, base_lat=35.01）
    detail_legacy_w = svc_legacy_w.check_landslide_detail(35.0105, 139.0105)
    detail_streaming_w = svc_streaming_w.check_landslide_detail(35.0105, 139.0105)
    assert detail_legacy_w == detail_streaming_w == {"status": "inside", "level": "danger", "zone_type": "warning"}

    # miss
    assert svc_legacy.check_landslide_detail(50.0, 150.0) == {"status": "outside"}
    assert svc_streaming.check_landslide_detail(50.0, 150.0) == {"status": "outside"}


# ── G/H/I. lowland_poor_drainage: streaming polygons == legacy、hit等価性 ──────

def test_G_lowland_streaming_polygons_equal_legacy(tmp_path):
    path = tmp_path / "lowland.geojson"
    _write_feature_collection(path, _lowland_features(300))

    svc_legacy = HazardService()
    svc_legacy.load("lowland_poor_drainage", path, bbox_only=True)

    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("lowland_poor_drainage", path, bbox_only=True)

    assert svc_legacy.polygon_count("lowland_poor_drainage") == svc_streaming.polygon_count("lowland_poor_drainage") == 300
    # lowland_poor_drainageはnumpy化されず、{"bbox": bbox}のみのdict listのまま
    assert svc_legacy._polygons["lowland_poor_drainage"] == svc_streaming._polygons["lowland_poor_drainage"]
    assert all(set(p.keys()) == {"bbox"} for p in svc_streaming._polygons["lowland_poor_drainage"])


def test_H_lowland_check_point_equivalence(tmp_path):
    path = tmp_path / "lowland.geojson"
    _write_feature_collection(path, [_make_polygon_feature({"risk_level": 1}, seed=0)])

    svc_legacy = HazardService()
    svc_legacy.load("lowland_poor_drainage", path, bbox_only=True)
    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("lowland_poor_drainage", path, bbox_only=True)

    assert svc_legacy.check_point(35.0005, 139.0005, "lowland_poor_drainage") is True
    assert svc_streaming.check_point(35.0005, 139.0005, "lowland_poor_drainage") is True
    assert svc_legacy.check_point(50.0, 150.0, "lowland_poor_drainage") is False
    assert svc_streaming.check_point(50.0, 150.0, "lowland_poor_drainage") is False


def test_I_lowland_assess_candidate_equivalence(tmp_path):
    path = tmp_path / "lowland.geojson"
    _write_feature_collection(path, [_make_polygon_feature({"risk_level": 1}, seed=0)])

    svc_legacy = HazardService()
    svc_legacy.load("lowland_poor_drainage", path, bbox_only=True)
    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("lowland_poor_drainage", path, bbox_only=True)

    assert svc_legacy.assess_candidate(35.0005, 139.0005).get("lowland_poor_drainage") == "inside"
    assert svc_streaming.assess_candidate(35.0005, 139.0005).get("lowland_poor_drainage") == "inside"
    assert svc_legacy.assess_candidate(50.0, 150.0).get("lowland_poor_drainage") == "outside"
    assert svc_streaming.assess_candidate(50.0, 150.0).get("lowland_poor_drainage") == "outside"


# ── J. 対象3typeでjson.load()が一切呼ばれないことの証明 ────────────────────────

def test_J_no_json_load_called_for_three_types(tmp_path, monkeypatch):
    import hazard_service as hazard_service_module

    paths = {
        "tsunami": tmp_path / "tsunami.geojson",
        "landslide": tmp_path / "landslide.geojson",
        "lowland_poor_drainage": tmp_path / "lowland.geojson",
    }
    _write_feature_collection(paths["tsunami"], _tsunami_features(5))
    _write_feature_collection(paths["landslide"], _landslide_features(5))
    _write_feature_collection(paths["lowland_poor_drainage"], _lowland_features(5))

    calls = []
    orig_json_load = hazard_service_module.json.load

    def _spy_json_load(*args, **kwargs):
        calls.append(True)
        return orig_json_load(*args, **kwargs)

    monkeypatch.setattr(hazard_service_module.json, "load", _spy_json_load)

    svc = HazardService()
    for hazard_type, path in paths.items():
        svc.load_geojson_streaming(hazard_type, path, bbox_only=True)

    assert calls == []  # json.load()は一度も呼ばれない
    assert svc.polygon_count("tsunami") == 5
    assert svc.polygon_count("landslide") == 5
    assert svc.polygon_count("lowland_poor_drainage") == 5


# ── M. 6type全てload可能なこと ──────────────────────────────────────────────────

def test_M_six_hazard_types_all_loadable(tmp_path):
    svc = HazardService()

    flood_path = tmp_path / "flood.geojson"
    surge_path = tmp_path / "storm_surge.geojson"
    tsunami_path = tmp_path / "tsunami.geojson"
    landslide_path = tmp_path / "landslide.geojson"
    lowland_path = tmp_path / "lowland.geojson"
    inland_path = tmp_path / "inland_flood.geojson"

    _write_feature_collection(flood_path, _flood_features(5))
    _write_feature_collection(surge_path, _surge_features(5))
    _write_feature_collection(tsunami_path, _tsunami_features(5))
    _write_feature_collection(landslide_path, _landslide_features(5))
    _write_feature_collection(lowland_path, _lowland_features(5))
    _write_feature_collection(inland_path, [_make_polygon_feature({"depth": 0.5}, seed=0)])

    svc.load_geojson_streaming("flood", flood_path, bbox_only=True)
    svc.load_geojson_streaming("storm_surge", surge_path, bbox_only=True)
    svc.load_geojson_streaming("tsunami", tsunami_path, bbox_only=True)
    svc.load_geojson_streaming("landslide", landslide_path, bbox_only=True)
    svc.load_geojson_streaming("lowland_poor_drainage", lowland_path, bbox_only=True)
    svc.load("inland_flood", inland_path, bbox_only=False)  # 今回スコープ外、既存load()のまま

    for hazard_type in [
        "flood", "storm_surge", "tsunami", "landslide", "lowland_poor_drainage", "inland_flood",
    ]:
        assert svc.is_loaded(hazard_type) is True, f"{hazard_type} did not load"

    assert set(svc.loaded_hazard_types()) == {
        "flood", "storm_surge", "tsunami", "landslide", "lowland_poor_drainage", "inland_flood",
    }


# ── N/O. malformed GeoJSON / missing file の既存fail-open契約維持（3type分） ───

@pytest.mark.parametrize("hazard_type", ["tsunami", "landslide", "lowland_poor_drainage"])
def test_N_malformed_json_leaves_type_unloaded(hazard_type, tmp_path, caplog):
    path = tmp_path / "broken.geojson"
    path.write_text('{"type": "FeatureCollection", "features": [{"type": "Feature", BROKEN')

    svc = HazardService()
    with caplog.at_level(logging.ERROR):
        svc.load_geojson_streaming(hazard_type, path, bbox_only=True)

    assert svc.is_loaded(hazard_type) is False
    assert svc.polygon_count(hazard_type) == 0
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


@pytest.mark.parametrize("hazard_type", ["tsunami", "landslide", "lowland_poor_drainage"])
def test_O_missing_file_warns_and_stays_unloaded(hazard_type, tmp_path, caplog):
    svc = HazardService()
    with caplog.at_level(logging.WARNING):
        svc.load_geojson_streaming(hazard_type, tmp_path / "does_not_exist.geojson", bbox_only=True)
    assert svc.is_loaded(hazard_type) is False


def test_multiple_files_accumulate_in_deterministic_order(tmp_path):
    """複数region fileを順次ロードした際、legacy/streamingで累積結果が一致する。"""
    tokyo = tmp_path / "tokyo.geojson"
    kanagawa = tmp_path / "kanagawa.geojson"
    _write_feature_collection(tokyo, _flood_features(300))
    _write_feature_collection(kanagawa, _flood_features(200))

    svc_legacy = HazardService()
    svc_legacy.load("flood", tokyo, bbox_only=True)
    svc_legacy.load("flood", kanagawa, bbox_only=True)

    svc_streaming = HazardService()
    svc_streaming.load_geojson_streaming("flood", tokyo, bbox_only=True)
    svc_streaming.load_geojson_streaming("flood", kanagawa, bbox_only=True)

    assert svc_legacy.polygon_count("flood") == svc_streaming.polygon_count("flood") == 500
    assert np.array_equal(svc_legacy._flood_bboxes_np, svc_streaming._flood_bboxes_np)


# ── F/G. check_point ────────────────────────────────────────────────────────

def test_F_check_point_flood_hit_and_miss(tmp_path):
    path = tmp_path / "flood.geojson"
    _write_feature_collection(path, [_make_polygon_feature({"flood_rank": 3}, seed=0)])

    svc = HazardService(flood_proximity_buffer_deg=0.0)
    svc.load_geojson_streaming("flood", path, bbox_only=True)

    assert svc.check_point(35.0005, 139.0005, "flood") is True  # bbox内
    assert svc.check_point(50.0, 150.0, "flood") is False  # bbox外


def test_G_check_point_storm_surge_hit_and_miss(tmp_path):
    path = tmp_path / "storm_surge.geojson"
    _write_feature_collection(path, [_make_polygon_feature({"storm_surge_rank": 2}, seed=0)])

    svc = HazardService()
    svc.load_geojson_streaming("storm_surge", path, bbox_only=True)

    assert svc.check_point(35.0005, 139.0005, "storm_surge") is True
    assert svc.check_point(50.0, 150.0, "storm_surge") is False


# ── H. assess_candidate ────────────────────────────────────────────────────────

def test_H_assess_candidate_reflects_streaming_loaded_flood(tmp_path):
    path = tmp_path / "flood.geojson"
    _write_feature_collection(path, [_make_polygon_feature({"flood_rank": 3}, seed=0)])

    svc = HazardService(flood_proximity_buffer_deg=0.0)
    svc.load_geojson_streaming("flood", path, bbox_only=True)

    assessment_hit = svc.assess_candidate(35.0005, 139.0005)
    assessment_miss = svc.assess_candidate(50.0, 150.0)

    assert assessment_hit.get("flood") == "inside"
    assert assessment_miss.get("flood") == "outside"


# ── I. malformed JSON → fail（partial loadを正常扱いしない） ──────────────────

def test_I_malformed_json_leaves_type_unloaded(tmp_path, caplog):
    path = tmp_path / "broken.geojson"
    path.write_text('{"type": "FeatureCollection", "features": [{"type": "Feature", BROKEN')

    svc = HazardService()
    with caplog.at_level(logging.ERROR):
        svc.load_geojson_streaming("flood", path, bbox_only=True)

    assert svc.is_loaded("flood") is False
    assert svc.polygon_count("flood") == 0
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_I_partial_valid_then_broken_does_not_commit_partial_state(tmp_path, caplog):
    """100件は構文的に正しく読み進められた後、末尾が壊れているケース。
    途中まで読めたfeatureをpartial successとして反映してはならない。"""
    features_json = ",".join(json.dumps(f) for f in _flood_features(100))
    path = tmp_path / "partial_broken.geojson"
    path.write_text('{"type": "FeatureCollection", "features": [' + features_json + ", BROKEN_TAIL")

    svc = HazardService()
    with caplog.at_level(logging.ERROR):
        svc.load_geojson_streaming("flood", path, bbox_only=True)

    assert svc.is_loaded("flood") is False
    assert svc.polygon_count("flood") == 0


def test_missing_file_warns_and_stays_unloaded(tmp_path, caplog):
    svc = HazardService()
    with caplog.at_level(logging.WARNING):
        svc.load_geojson_streaming("flood", tmp_path / "does_not_exist.geojson", bbox_only=True)
    assert svc.is_loaded("flood") is False


# ── A-D. region配下layout discovery（app_public.pyのrglobパターンを再現） ─────

def _discover(root: Path, hazard_type: str) -> list[Path]:
    """app_public.pyが使うのと同じdiscoveryパターン: {type}配下をrglobする。"""
    type_dir = root / hazard_type
    if not type_dir.is_dir():
        return []
    return sorted(type_dir.rglob("*.geojson"))


def test_A_flood_tokyo_region_layout_discovered(tmp_path):
    root = tmp_path / "backend" / "hazard"
    target = root / "flood" / "tokyo" / "tokyo-river-001.geojson"
    _write_feature_collection(target, _flood_features(10))

    found = _discover(root, "flood")
    assert found == [target]


def test_B_flood_kanagawa_region_layout_discovered(tmp_path):
    root = tmp_path / "backend" / "hazard"
    tokyo = root / "flood" / "tokyo" / "tokyo-river-001.geojson"
    kanagawa = root / "flood" / "kanagawa" / "kanagawa-river-001.geojson"
    _write_feature_collection(tokyo, _flood_features(10))
    _write_feature_collection(kanagawa, _flood_features(10))

    found = _discover(root, "flood")
    assert found == sorted([tokyo, kanagawa])


def test_C_storm_surge_tokyo_discovered(tmp_path):
    root = tmp_path / "backend" / "hazard"
    target = root / "storm_surge" / "tokyo" / "tokyo-surge-001.geojson"
    _write_feature_collection(target, _surge_features(10))

    found = _discover(root, "storm_surge")
    assert found == [target]


def test_D_storm_surge_kanagawa_discovered(tmp_path):
    root = tmp_path / "backend" / "hazard"
    target = root / "storm_surge" / "kanagawa" / "kanagawa-surge-001.geojson"
    _write_feature_collection(target, _surge_features(10))

    found = _discover(root, "storm_surge")
    assert found == [target]


def test_old_flat_root_geojsonl_not_picked_up_by_new_pattern(tmp_path):
    """旧flat直下.geojsonlは新パターン（rglob *.geojson）では拾わない
    （layout是正の意図的な帰結——旧primary経路の廃止を確認する回帰）。"""
    root = tmp_path / "backend" / "hazard"
    old_style = root / "flood" / "tokyo_flood_check.geojsonl"
    old_style.parent.mkdir(parents=True, exist_ok=True)
    old_style.write_text('{"type": "Feature"}\n')

    found = _discover(root, "flood")
    assert found == []


def test_unsupported_region_absent_is_not_an_error(tmp_path):
    root = tmp_path / "backend" / "hazard"
    tokyo = root / "flood" / "tokyo" / "tokyo-river-001.geojson"
    _write_feature_collection(tokyo, _flood_features(10))
    # kanagawaディレクトリは意図的に作らない

    found = _discover(root, "flood")
    assert found == [tokyo]  # エラーにならず、存在するregionのみ


# ── inland_flood regression: load()は今回のスコープ外のまま無変更 ─────────────
# HAZARD-LOAD-JSONLOAD-TRANSIENT-PEAK-RESIDUAL Phase B0でtsunami/landslide/
# lowland_poor_drainageはload_geojson_streaming()経由へ切り替わったが、
# inland_flood（bbox_only=False、実データ約188KBと極小のため優先度低）は
# 今回スコープ外のままload()を使い続ける。

def test_existing_load_and_load_geojsonl_unaffected(tmp_path):
    """load()（inland_flood が引き続き使用）が、streaming loader拡張に
    よって一切影響を受けていないことを確認する（共通ヘルパー抽出の
    regression）。"""
    path = tmp_path / "inland_flood.geojson"
    features = [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[139.0, 35.0], [139.01, 35.0], [139.01, 35.01], [139.0, 35.0]]],
            },
        }
    ]
    _write_feature_collection(path, features)

    svc = HazardService()
    svc.load("inland_flood", path, bbox_only=False)
    assert svc.polygon_count("inland_flood") == 1
    assert svc.check_point(35.001, 139.001, "inland_flood") is True
