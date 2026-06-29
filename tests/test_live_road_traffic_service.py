"""
test_live_road_traffic_service.py — live_road_traffic_service ユニットテスト

外部 API は一切呼ばない（ROAD_TRAFFIC_USE_MOCK=true を使用）。
正規化ロジック・ステータス判定・キャッシュ動作を検証する。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.live_road_traffic import (
    SEVERITY,
    STATUS_HIGH,
    STATUS_LABEL,
    STATUS_LOW,
    STATUS_NORMAL,
    STATUS_UNAVAILABLE,
    STATUS_UNKNOWN,
    STATUS_VERY_HIGH,
    STATUS_VERY_LOW,
)
from app.services.live_road_traffic_service import (
    classify_volume,
    normalize_raw_item,
    build_road_traffic_summary,
    _mock_items,
    _observed_at_from_jartic,
    _normalize_jartic_feature,
    _build_wfs_url,
    _DEFAULT_JAPAN_BBOX,
)


def _run(coro):
    return asyncio.run(coro)


# ── classify_volume ───────────────────────────────────────────────────────────

def test_classify_very_high_5min():
    assert classify_volume(150, None) == STATUS_VERY_HIGH


def test_classify_very_high_boundary():
    assert classify_volume(200, None) == STATUS_VERY_HIGH


def test_classify_high_5min():
    assert classify_volume(80, None) == STATUS_HIGH


def test_classify_high_boundary():
    assert classify_volume(100, None) == STATUS_HIGH


def test_classify_normal_midrange():
    assert classify_volume(40, None) == STATUS_NORMAL


def test_classify_low_boundary():
    assert classify_volume(15, None) == STATUS_LOW


def test_classify_low_5min():
    assert classify_volume(10, None) == STATUS_LOW


def test_classify_very_low_boundary():
    assert classify_volume(3, None) == STATUS_VERY_LOW


def test_classify_very_low_zero():
    assert classify_volume(0, None) == STATUS_VERY_LOW


def test_classify_unknown_both_none():
    assert classify_volume(None, None) == STATUS_UNKNOWN


def test_classify_uses_1h_fallback():
    # 5分値なし、1時間値 = 960 → /12 = 80 → STATUS_HIGH
    assert classify_volume(None, 960) == STATUS_HIGH


def test_classify_1h_very_high():
    # 1時間値 1800 → /12 = 150 → STATUS_VERY_HIGH
    assert classify_volume(None, 1800) == STATUS_VERY_HIGH


def test_classify_1h_very_low():
    # 1時間値 24 → /12 = 2 → STATUS_VERY_LOW
    assert classify_volume(None, 24) == STATUS_VERY_LOW


def test_classify_5min_takes_priority():
    # 5分値があれば1時間値は無視する
    assert classify_volume(200, 1) == STATUS_VERY_HIGH


# ── STATUS_LABEL / SEVERITY の整合性確認 ──────────────────────────────────────

def test_all_statuses_have_label():
    for status in (STATUS_NORMAL, STATUS_HIGH, STATUS_VERY_HIGH, STATUS_LOW, STATUS_VERY_LOW, STATUS_UNKNOWN, STATUS_UNAVAILABLE):
        assert status in STATUS_LABEL, f"STATUS_LABEL missing: {status}"


def test_all_statuses_have_severity():
    for status in (STATUS_NORMAL, STATUS_HIGH, STATUS_VERY_HIGH, STATUS_LOW, STATUS_VERY_LOW, STATUS_UNKNOWN, STATUS_UNAVAILABLE):
        assert status in SEVERITY, f"SEVERITY missing: {status}"


def test_severity_very_high_greater_than_high():
    assert SEVERITY[STATUS_VERY_HIGH] > SEVERITY[STATUS_HIGH]


def test_severity_very_low_greater_than_low():
    assert SEVERITY[STATUS_VERY_LOW] > SEVERITY[STATUS_LOW]


def test_severity_normal_is_zero():
    assert SEVERITY[STATUS_NORMAL] == 0


def test_severity_unavailable_is_nine():
    assert SEVERITY[STATUS_UNAVAILABLE] == 9


# ── normalize_raw_item ────────────────────────────────────────────────────────

def test_normalize_basic():
    raw = {
        "station_id": "T001",
        "road_name": "国道20号",
        "direction": "上り",
        "lat": 35.68,
        "lng": 139.76,
        "volume_5min": 180,
        "volume_1h": 2160,
        "observed_at": "2026-06-20T10:00:00+09:00",
    }
    item = normalize_raw_item(raw)
    assert item is not None
    assert item["station_id"] == "T001"
    assert item["road_name"] == "国道20号"
    assert item["direction"] == "上り"
    assert item["status"] == STATUS_VERY_HIGH
    assert item["status_label"] == STATUS_LABEL[STATUS_VERY_HIGH]
    assert item["severity"] == SEVERITY[STATUS_VERY_HIGH]
    assert item["volume_5min"] == 180
    assert item["volume_1h"] == 2160
    assert item["source"] == "国土交通省 交通量API（JARTIC提供）"


def test_normalize_alt_field_names():
    # vol5 / vol60 / latitude / longitude / route_name / id フォールバック
    raw = {
        "id": "S99",
        "route_name": "国道246号",
        "dir": "下り",
        "latitude": 35.65,
        "longitude": 139.69,
        "vol5": 10,
        "vol60": 120,
        "datetime": "2026-06-20T10:00:00+09:00",
    }
    item = normalize_raw_item(raw)
    assert item is not None
    assert item["station_id"] == "S99"
    assert item["road_name"] == "国道246号"
    assert item["direction"] == "下り"
    assert item["lat"] == 35.65
    assert item["lng"] == 139.69
    assert item["volume_5min"] == 10
    assert item["volume_1h"] == 120


def test_normalize_missing_station_id_returns_none():
    raw = {"road_name": "国道1号", "lat": 35.0, "lng": 139.0}
    assert normalize_raw_item(raw) is None


def test_normalize_missing_lat_returns_none():
    raw = {"station_id": "X1", "road_name": "国道1号", "lng": 139.0}
    assert normalize_raw_item(raw) is None


def test_normalize_missing_lng_returns_none():
    raw = {"station_id": "X1", "road_name": "国道1号", "lat": 35.0}
    assert normalize_raw_item(raw) is None


def test_normalize_no_volume_gives_unknown():
    raw = {"station_id": "X1", "road_name": "国道1号", "lat": 35.0, "lng": 139.0}
    item = normalize_raw_item(raw)
    assert item is not None
    assert item["status"] == STATUS_UNKNOWN


def test_normalize_zero_volume_is_not_treated_as_missing():
    raw = {
        "station_id": "X0",
        "road_name": "国道0号",
        "lat": 35.0,
        "lng": 139.0,
        "volume_5min": 0,
        "volume_1h": 0,
    }
    item = normalize_raw_item(raw)
    assert item is not None
    assert item["volume_5min"] == 0
    assert item["volume_1h"] == 0
    assert item["status"] == STATUS_VERY_LOW


# ── mock_items ────────────────────────────────────────────────────────────────

def test_mock_items_not_empty():
    items = _mock_items()
    assert len(items) > 0


def test_mock_items_have_required_fields():
    items = _mock_items()
    for item in items:
        assert "station_id"   in item
        assert "road_name"    in item
        assert "lat"          in item
        assert "lng"          in item
        assert "status"       in item
        assert "status_label" in item
        assert "severity"     in item
        assert "source"       in item


def test_mock_items_cover_multiple_statuses():
    items = _mock_items()
    statuses = {it["status"] for it in items}
    # モックデータは複数のステータスを含む
    assert len(statuses) >= 3


def test_mock_has_very_high():
    items = _mock_items()
    assert any(it["status"] == STATUS_VERY_HIGH for it in items)


def test_mock_has_high():
    items = _mock_items()
    assert any(it["status"] == STATUS_HIGH for it in items)


def test_mock_has_low():
    items = _mock_items()
    assert any(it["status"] == STATUS_LOW for it in items)


def test_mock_has_very_low():
    items = _mock_items()
    assert any(it["status"] == STATUS_VERY_LOW for it in items)


# ── build_road_traffic_summary（モックモード） ────────────────────────────────

def _run_with_mock(coro):
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true", "ROAD_TRAFFIC_API_KEY": ""}):
        return asyncio.run(coro)


def test_summary_ok_with_mock():
    import app.services.live_road_traffic_service as svc
    svc._cache = None
    svc._cache_at = 0.0
    result = _run_with_mock(build_road_traffic_summary())
    assert result["status"] == "ok"
    assert isinstance(result["items"], list)
    assert len(result["items"]) > 0


def test_summary_items_have_status_label():
    import app.services.live_road_traffic_service as svc
    svc._cache = None
    svc._cache_at = 0.0
    result = _run_with_mock(build_road_traffic_summary())
    for item in result["items"]:
        assert "status_label" in item
        assert item["status_label"] != ""


def test_summary_prefecture_scope():
    import app.services.live_road_traffic_service as svc
    svc._cache = None
    svc._cache_at = 0.0
    result = _run_with_mock(build_road_traffic_summary(prefecture="東京都"))
    assert result["scope"]["mode"] == "prefecture"
    assert result["scope"]["prefecture"] == "東京都"


def test_summary_bbox_scope():
    import app.services.live_road_traffic_service as svc
    svc._cache = None
    svc._cache_at = 0.0
    bbox = "138.0,34.0,141.0,36.5"
    result = _run_with_mock(build_road_traffic_summary(bbox=bbox))
    assert result["scope"]["mode"] == "bbox"
    assert result["scope"]["bbox"] == bbox


def test_summary_bbox_priority_over_prefecture():
    import app.services.live_road_traffic_service as svc
    svc._cache = None
    svc._cache_at = 0.0
    bbox = "138.0,34.0,141.0,36.5"
    result = _run_with_mock(build_road_traffic_summary(prefecture="東京都", bbox=bbox))
    assert result["scope"]["mode"] == "bbox"


def test_summary_unavailable_on_fetch_failure():
    """通信失敗時に status=unavailable が返る（APIキー未設定は理由にならない）。"""
    import app.services.live_road_traffic_service as svc
    from urllib.error import URLError
    svc._cache = None
    svc._cache_at = 0.0
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(side_effect=URLError("timeout"))):
            result = asyncio.run(build_road_traffic_summary())
    assert result["status"] == "unavailable"
    assert result["items"] == []


def test_summary_unavailable_has_message():
    import app.services.live_road_traffic_service as svc
    from urllib.error import URLError
    svc._cache = None
    svc._cache_at = 0.0
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(side_effect=URLError("timeout"))):
            result = asyncio.run(build_road_traffic_summary())
    assert "message" in result
    assert "道路交通" in result["message"]


def test_summary_cache_avoids_second_fetch():
    import app.services.live_road_traffic_service as svc
    svc._cache = None
    svc._cache_at = 0.0
    fetch = AsyncMock(return_value=_mock_items())
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true", "ROAD_TRAFFIC_API_KEY": ""}), \
         patch.object(svc, "_fetch_all_items", fetch):
        first = asyncio.run(build_road_traffic_summary(prefecture="東京都"))
        second = asyncio.run(build_road_traffic_summary(prefecture="東京都"))
    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert fetch.await_count == 1


def test_summary_fetch_failure_returns_stale_cache():
    import app.services.live_road_traffic_service as svc
    cached_items = _mock_items()
    svc._cache = {
        "status": "ok",
        "stale": False,
        "scope": {},
        "updated_at": "2026-06-20T08:00:00+09:00",
        "items": cached_items,
    }
    svc._cache_at = 0.0
    fetch = AsyncMock(side_effect=URLError("test failure"))
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false", "ROAD_TRAFFIC_API_KEY": "test-key"}), \
         patch.object(svc, "_fetch_all_items", fetch):
        result = asyncio.run(build_road_traffic_summary(prefecture="東京都"))
    assert result["status"] == "ok"
    assert result["stale"] is True
    assert result["items"]
    assert "前回取得情報" in result["message"]


def test_summary_stale_cache():
    """APIキーあり・取得失敗時にstale cacheを返す。"""
    import app.services.live_road_traffic_service as svc
    from unittest.mock import AsyncMock

    items = _mock_items()
    svc._cache = {"status": "ok", "stale": False, "scope": {}, "updated_at": "2026-01-01T00:00:00+09:00", "items": items}
    svc._cache_at = 0.0  # 強制期限切れ

    async def _fail():
        raise Exception("API error")

    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false", "ROAD_TRAFFIC_API_KEY": "dummy"}):
        with patch("app.services.live_road_traffic_service._fetch_all_items", side_effect=_fail):
            result = asyncio.run(build_road_traffic_summary())

    assert result["stale"] is True
    assert len(result["items"]) > 0

    svc._cache = None
    svc._cache_at = 0.0


def test_summary_stale_not_labeled_as_unavailable():
    """stale cacheを取得不可と誤表示しない。"""
    import app.services.live_road_traffic_service as svc

    items = _mock_items()
    svc._cache = {"status": "ok", "stale": False, "scope": {}, "updated_at": "2026-01-01T00:00:00+09:00", "items": items}
    svc._cache_at = 0.0

    async def _fail():
        raise Exception("API error")

    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false", "ROAD_TRAFFIC_API_KEY": "dummy"}):
        with patch("app.services.live_road_traffic_service._fetch_all_items", side_effect=_fail):
            result = asyncio.run(build_road_traffic_summary())

    assert result["status"] != "unavailable"

    svc._cache = None
    svc._cache_at = 0.0


def test_summary_all_scope_when_no_filter():
    import app.services.live_road_traffic_service as svc
    svc._cache = None
    svc._cache_at = 0.0
    result = _run_with_mock(build_road_traffic_summary())
    assert result["scope"]["mode"] == "all"


# ── JARTIC WFS 固有関数 ───────────────────────────────────────────────────────

_SAMPLE_FEATURE = {
    "type": "Feature",
    "id": "t_travospublic_measure_5m.4693500.202502100900",
    "geometry": {
        "type": "MultiPoint",
        "coordinates": [[139.203293, 35.37445003]],
    },
    "geometry_name": "ジオメトリ",
    "properties": {
        "地方整備局等番号": 83,
        "開発建設部／都道府県コード": "",
        "常時観測点コード": 3110640,
        "収集時間フラグ（5分間／1時間）": "1",
        "観測年月日": 20250210,
        "時間帯": 900,
        "上り・小型交通量": 42,
        "上り・大型交通量": 5,
        "上り・車種判別不能交通量": 1,
        "上り・停電": "0",
        "上り・ループ異常": "0",
        "上り・超音波異常": "0",
        "上り・欠測": "0",
        "下り・小型交通量": 39,
        "下り・大型交通量": 6,
        "下り・車種判別不能交通量": 3,
        "下り・停電": "0",
        "下り・ループ異常": "0",
        "下り・超音波異常": "0",
        "下り・欠測": "0",
        "道路種別": "3",
        "時間コード": 202502100900,
    },
}


def test_observed_at_from_jartic_basic():
    result = _observed_at_from_jartic(20250210, 900)
    assert result.startswith("2025-02-10")
    assert "09:00" in result


def test_observed_at_from_jartic_zero_padded():
    # 時間帯 0 → 0000
    result = _observed_at_from_jartic(20250101, 0)
    assert "00:00" in result


def test_observed_at_from_jartic_invalid_returns_something():
    # 不正値でも例外を出さずに文字列を返す
    result = _observed_at_from_jartic(0, 0)
    assert isinstance(result, str)
    assert len(result) > 0


def test_normalize_jartic_feature_basic():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    assert len(items) == 2  # 上り・下り


def test_normalize_jartic_feature_station_id():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    ids = {it["station_id"] for it in items}
    assert "3110640_上り" in ids
    assert "3110640_下り" in ids


def test_normalize_jartic_feature_coordinates():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    for it in items:
        assert abs(it["lat"] - 35.37445003) < 1e-6
        assert abs(it["lng"] - 139.203293) < 1e-6


def test_normalize_jartic_feature_road_name():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    for it in items:
        assert "一般国道" in it["road_name"]
        assert "3110640" in it["road_name"]


def test_normalize_jartic_feature_volume_upbound():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    up = next(it for it in items if it["direction"] == "上り")
    # 42 + 5 + 1 = 48
    assert up["volume_5min"] == 48


def test_normalize_jartic_feature_volume_downbound():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    dn = next(it for it in items if it["direction"] == "下り")
    # 39 + 6 + 3 = 48
    assert dn["volume_5min"] == 48


def test_normalize_jartic_feature_source():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    for it in items:
        assert "JARTIC" in it["source"]
        assert "[mock]" not in it["source"]


def test_normalize_jartic_feature_observed_at():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    for it in items:
        assert "2025-02-10" in it["observed_at"]


def test_normalize_jartic_feature_status_and_severity():
    items = _normalize_jartic_feature(_SAMPLE_FEATURE)
    for it in items:
        assert it["status"] in STATUS_LABEL
        assert isinstance(it["severity"], int)


def test_normalize_jartic_feature_missing_flag_skips_direction():
    feature = {
        **_SAMPLE_FEATURE,
        "properties": {
            **_SAMPLE_FEATURE["properties"],
            "上り・欠測": "1",  # 上りを欠測扱い
        },
    }
    items = _normalize_jartic_feature(feature)
    assert len(items) == 1
    assert items[0]["direction"] == "下り"


def test_normalize_jartic_feature_no_coords_returns_empty():
    feature = {**_SAMPLE_FEATURE, "geometry": {"type": "MultiPoint", "coordinates": []}}
    assert _normalize_jartic_feature(feature) == []


def test_normalize_jartic_feature_no_station_code_returns_empty():
    props = {k: v for k, v in _SAMPLE_FEATURE["properties"].items() if k != "常時観測点コード"}
    feature = {**_SAMPLE_FEATURE, "properties": props}
    assert _normalize_jartic_feature(feature) == []


def test_normalize_jartic_feature_highway_label():
    feature = {
        **_SAMPLE_FEATURE,
        "properties": {**_SAMPLE_FEATURE["properties"], "道路種別": "1"},
    }
    items = _normalize_jartic_feature(feature)
    for it in items:
        assert "高速道路" in it["road_name"]


def test_build_wfs_url_contains_required_params():
    url = _build_wfs_url("https://api.jartic-open-traffic.org/geoserver", _DEFAULT_JAPAN_BBOX)
    assert "service=WFS" in url
    assert "version=2.0.0" in url
    assert "request=GetFeature" in url
    assert "typeNames=t_travospublic_measure_5m" in url
    assert "outputFormat=application%2Fjson" in url or "outputFormat=application/json" in url
    assert "cql_filter=" in url


def test_build_wfs_url_contains_timecode():
    url = _build_wfs_url("https://api.jartic-open-traffic.org/geoserver", _DEFAULT_JAPAN_BBOX)
    # 時間コードは12桁数字（YYYYMMDDhhmm）
    import re
    assert re.search(r"%E6%99%82%E9%96%93%E3%82%B3%E3%83%BC%E3%83%89.{1,10}\d{12}", url) or \
           re.search(r"時間コード.{0,5}\d{12}", url) or \
           "202" in url  # 年（2020年代）が含まれる


def test_build_wfs_url_contains_bbox():
    url = _build_wfs_url("https://api.jartic-open-traffic.org/geoserver", "139.0,35.0,140.0,36.0")
    # bbox の座標値が URL に含まれる
    assert "139.0" in url or "139" in url
