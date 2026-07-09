"""
test_live_weather_jma_service.py — live_weather_jma_service ユニットテスト

外部 API (Open-Meteo) は一切呼ばない。
天気コード正規化・数値強調フラグ・地点マスタ・キャッシュ動作を検証する。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.live_weather_jma_service import (
    compute_flags,
    get_weather_summary,
    normalize_weather_code,
    _build_item,
    _load_points,
    _select_hour_index,
    _OPEN_METEO_URL,
    _SOURCE_LABEL,
)


def _run(coro):
    return asyncio.run(coro)


# ── Open-Meteo エンドポイント (Phase 8-A.1: /v1/jma → /v1/forecast) ────────────

def test_uses_forecast_endpoint_not_jma():
    """/v1/jma は precipitation_probability が常に null のため /v1/forecast を使う。"""
    assert _OPEN_METEO_URL == "https://api.open-meteo.com/v1/forecast"
    assert "/v1/jma" not in _OPEN_METEO_URL


def test_source_label_is_open_meteo_forecast():
    assert _SOURCE_LABEL == "Open-Meteo Forecast"


# ── _build_item: precipitation_probability が null にならないこと (mock) ───────

def _mock_forecast_payload(precip_values):
    """/v1/forecast の hourly レスポンス形状を模したモック。"""
    hours = len(precip_values)
    return {
        "hourly": {
            "time": [f"2026-07-10T{h:02d}:00" for h in range(hours)],
            "weather_code": [3] * hours,
            "temperature_2m": [25.0] * hours,
            "relative_humidity_2m": [70] * hours,
            "precipitation_probability": precip_values,
        }
    }


def test_build_item_precipitation_not_null_with_mock_forecast_response():
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))

    point = {
        "id": "kanto_tokyo", "pref_code": "13", "pref_name": "東京都",
        "point_name": "東京", "display_order": 310, "lat": 35.69, "lon": 139.69,
    }
    forecast = _mock_forecast_payload([10, 20, 30, 40, 50, 60, 70, 80] * 3)
    target = datetime(2026, 7, 10, 7, 0, tzinfo=jst)

    item, forecast_time = _build_item(point, forecast, target)

    assert item is not None
    assert item["precipitation_probability_percent"] is not None
    assert item["precipitation_probability_percent"] == 80
    assert item["flags"]["precipitation_high"] is True
    assert forecast_time == "2026-07-10T07:00"


def test_build_item_precipitation_never_null_across_all_hours():
    """/v1/jma で発生していた「全時間帯 null」の再発を防ぐ回帰テスト。"""
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))

    point = {
        "id": "kanto_tokyo", "pref_code": "13", "pref_name": "東京都",
        "point_name": "東京", "display_order": 310, "lat": 35.69, "lon": 139.69,
    }
    precip_values = list(range(0, 24))  # 全24時間ぶん、null は一つもない
    forecast = _mock_forecast_payload(precip_values)

    for hour in range(24):
        target = datetime(2026, 7, 10, hour, 0, tzinfo=jst)
        item, _ = _build_item(point, forecast, target)
        assert item is not None
        assert item["precipitation_probability_percent"] is not None


# ── normalize_weather_code ─────────────────────────────────────────────────────

def test_weather_code_sunny():
    assert normalize_weather_code(0) == ("sunny", "晴")
    assert normalize_weather_code(1) == ("sunny", "晴")
    assert normalize_weather_code(2) == ("sunny", "晴")


def test_weather_code_cloudy():
    assert normalize_weather_code(3) == ("cloudy", "曇")


def test_weather_code_fog():
    assert normalize_weather_code(45) == ("fog", "霧")
    assert normalize_weather_code(48) == ("fog", "霧")


def test_weather_code_rain():
    for code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        assert normalize_weather_code(code) == ("rain", "雨")


def test_weather_code_snow():
    for code in (71, 73, 75, 77, 85, 86):
        assert normalize_weather_code(code) == ("snow", "雪")


def test_weather_code_thunder():
    for code in (95, 96, 99):
        assert normalize_weather_code(code) == ("thunder", "雷")


def test_weather_code_unknown():
    assert normalize_weather_code(999) == ("unknown", "不明")
    assert normalize_weather_code(None) == ("unknown", "不明")
    assert normalize_weather_code("not-a-number") == ("unknown", "不明")


# ── compute_flags 境界値 ────────────────────────────────────────────────────────

def test_precipitation_flag_boundary():
    assert compute_flags(20, 50, 69)["precipitation_high"] is False
    assert compute_flags(20, 50, 70)["precipitation_high"] is True


def test_temperature_hot_boundary():
    assert compute_flags(34.9, 50, 0)["temperature_hot"] is False
    assert compute_flags(35.0, 50, 0)["temperature_hot"] is True


def test_temperature_cold_boundary():
    assert compute_flags(0.1, 50, 0)["temperature_cold"] is False
    assert compute_flags(0.0, 50, 0)["temperature_cold"] is True


def test_humidity_flag_boundary():
    assert compute_flags(20, 84, 0)["humidity_high"] is False
    assert compute_flags(20, 85, 0)["humidity_high"] is True


def test_flags_none_values_are_false():
    flags = compute_flags(None, None, None)
    assert flags == {
        "precipitation_high": False,
        "temperature_hot":    False,
        "temperature_cold":   False,
        "humidity_high":      False,
    }


# ── 地点マスタ ─────────────────────────────────────────────────────────────────

def test_points_master_has_53_points():
    points = _load_points()
    assert len(points) == 53


def test_points_master_ids_unique():
    points = _load_points()
    ids = [p["id"] for p in points]
    assert len(ids) == len(set(ids))


def test_points_master_hokkaido_has_7_points():
    points = _load_points()
    hokkaido = [p for p in points if p["pref_code"] == "01"]
    names = {p["point_name"] for p in hokkaido}
    assert names == {"函館", "札幌", "旭川", "帯広", "釧路", "網走", "稚内"}


def test_points_master_sorted_by_display_order():
    points = _load_points()
    orders = [p["display_order"] for p in points]
    assert orders == sorted(orders)


def test_points_master_south_to_north_order():
    points = _load_points()
    order_by_name = {p["point_name"]: p["display_order"] for p in points}
    assert order_by_name["那覇"] < order_by_name["鹿児島"]
    assert order_by_name["鹿児島"] < order_by_name["福岡"]
    assert order_by_name["福岡"] < order_by_name["大阪"]
    assert order_by_name["大阪"] < order_by_name["東京"]
    assert order_by_name["東京"] < order_by_name["仙台"]
    assert order_by_name["仙台"] < order_by_name["札幌"]
    assert order_by_name["札幌"] < order_by_name["稚内"]


# ── _select_hour_index ─────────────────────────────────────────────────────────

def test_select_hour_index_exact_match():
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    times = [f"2026-07-10T{h:02d}:00" for h in range(24)]
    target = datetime(2026, 7, 10, 15, 0, tzinfo=jst)
    assert _select_hour_index(times, target) == 15


def test_select_hour_index_empty_list():
    from datetime import datetime, timezone
    assert _select_hour_index([], datetime.now(timezone.utc)) is None


# ── キャッシュ動作 ─────────────────────────────────────────────────────────────

def _make_points_items():
    return [
        {
            "id": "test_point", "pref_code": "13", "pref_name": "東京都",
            "point_name": "東京", "display_order": 10,
            "weather_code": 3, "weather_category": "cloudy", "weather_label": "曇",
            "temperature_c": 28.0, "humidity_percent": 76,
            "precipitation_probability_percent": 40,
            "flags": {
                "precipitation_high": False, "temperature_hot": False,
                "temperature_cold": False, "humidity_high": False,
            },
        }
    ]


def test_fresh_fetch_returns_ok_and_fresh():
    import app.services.live_weather_jma_service as svc

    svc._cache = None
    svc._cache_at = 0.0

    async def _ok():
        return _make_points_items(), "2026-07-10T23:00:00+09:00"

    with patch("app.services.live_weather_jma_service._fetch_all_points", side_effect=_ok):
        result = _run(get_weather_summary())

    assert result["status"] == "ok"
    assert result["cache_status"] == "fresh"
    assert result["source"] == "Open-Meteo Forecast"
    assert len(result["items"]) == 1
    svc._cache = None
    svc._cache_at = 0.0


def test_stale_cache_on_fetch_failure_within_max_age():
    import app.services.live_weather_jma_service as svc

    svc._cache = {
        "items": _make_points_items(),
        "forecast_time": "2026-07-10T22:00:00+09:00",
        "fetched_at": "2026-07-10T22:10:00+09:00",
    }
    svc._cache_at = svc._monotonic() - (30 * 60)  # TTL(20分)切れだがstale許容内

    async def _fail():
        raise RuntimeError("fetch failed")

    try:
        with patch("app.services.live_weather_jma_service._fetch_all_points", side_effect=_fail):
            result = _run(get_weather_summary())
        assert result["status"] == "ok"
        assert result["cache_status"] == "stale"
        assert len(result["items"]) == 1
    finally:
        svc._cache = None
        svc._cache_at = 0.0


def test_unavailable_when_stale_cache_exceeds_max_age():
    import app.services.live_weather_jma_service as svc

    svc._cache = {
        "items": _make_points_items(),
        "forecast_time": "2026-07-10T10:00:00+09:00",
        "fetched_at": "2026-07-10T10:00:00+09:00",
    }
    svc._cache_at = svc._monotonic() - (3 * 60 * 60)  # 3時間前 = stale上限(2時間)超過

    async def _fail():
        raise RuntimeError("fetch failed")

    try:
        with patch("app.services.live_weather_jma_service._fetch_all_points", side_effect=_fail):
            result = _run(get_weather_summary())
        assert result["status"] == "unavailable"
        assert result["cache_status"] == "unavailable"
        # 前回取得時刻は保持したまま返す（unavailableと「なし」を混同させないため）
        assert result["fetched_at"] == "2026-07-10T10:00:00+09:00"
    finally:
        svc._cache = None
        svc._cache_at = 0.0


def test_unavailable_when_no_cache_ever():
    import app.services.live_weather_jma_service as svc

    svc._cache = None
    svc._cache_at = 0.0

    async def _fail():
        raise RuntimeError("fetch failed")

    with patch("app.services.live_weather_jma_service._fetch_all_points", side_effect=_fail):
        result = _run(get_weather_summary())

    assert result["status"] == "unavailable"
    assert result["cache_status"] == "unavailable"
    assert result["items"] == []
    assert result["fetched_at"] is None
