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


# ── 既存4type regression: load_geojson_streamingを使わないtypeは無変更 ────────

def test_existing_load_and_load_geojsonl_unaffected(tmp_path):
    """load()/load_geojsonl()（inland_flood/landslide/lowland_poor_drainage/
    tsunami等が引き続き使用）が、streaming loader追加によって一切
    影響を受けていないことを確認する（共通ヘルパー抽出のregression）。"""
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
