"""
test_weather_alert_service.py — weather_alert_service 永続キャッシュユニットテスト

Residual Finding Remediation 01 (data_runtime cache boundary移行) の検証:
- persistent cache dir が /data_runtime/cache/weather へ絶対pathで解決されること
- save/load の往復
- cache miss（file不在）
- 破損cacheの graceful handling
- mkdir(parents=True, exist_ok=True) によるdirectory自動生成
- write失敗時に例外を外へ漏らさない（graceful handling）
- stale fallback（JMA取得失敗時に永続cacheから応答する）semanticsの維持
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.weather_alert import WeatherAlertItem  # noqa: E402


def _sample_items() -> list[WeatherAlertItem]:
    return [
        WeatherAlertItem(
            area_code="130010",
            area_name="東京地方",
            source_area_type="pref",
            kind="大雨警報",
            level="warning",
            severity="warning",
            status="発表",
            headline="大雨警報が発表されました",
            issued_at="2026-09-06T00:00:00+09:00",
            updated_at="2026-09-06T00:00:00+09:00",
            source="jma",
            raw_code="03",
        )
    ]


def test_persistent_cache_dir_is_absolute_under_data_runtime_cache_weather():
    import app.services.weather_alert_service as svc

    assert svc._PERSISTENT_CACHE_DIR.is_absolute()
    assert svc._PERSISTENT_CACHE_DIR.parts[-3:] == ("data_runtime", "cache", "weather")


def test_save_and_load_persistent_cache_roundtrip(tmp_path):
    import app.services.weather_alert_service as svc

    cache_dir = tmp_path / "cache" / "weather"
    with patch.object(svc, "_PERSISTENT_CACHE_DIR", cache_dir):
        items = _sample_items()
        svc._save_persistent_cache("130000", items)

        loaded = svc._load_persistent_cache("130000")

    assert loaded is not None
    assert len(loaded) == 1
    assert loaded[0].area_code == "130010"
    assert loaded[0].kind == "大雨警報"


def test_save_persistent_cache_creates_directory(tmp_path):
    import app.services.weather_alert_service as svc

    cache_dir = tmp_path / "nested" / "cache" / "weather"
    assert not cache_dir.exists()

    with patch.object(svc, "_PERSISTENT_CACHE_DIR", cache_dir):
        svc._save_persistent_cache("140000", _sample_items())

    assert cache_dir.exists()
    assert (cache_dir / "alerts_140000.json").exists()


def test_load_persistent_cache_missing_returns_none(tmp_path):
    import app.services.weather_alert_service as svc

    cache_dir = tmp_path / "cache" / "weather"
    with patch.object(svc, "_PERSISTENT_CACHE_DIR", cache_dir):
        result = svc._load_persistent_cache("999999")

    assert result is None


def test_load_persistent_cache_malformed_returns_none(tmp_path):
    import app.services.weather_alert_service as svc

    cache_dir = tmp_path / "cache" / "weather"
    cache_dir.mkdir(parents=True)
    (cache_dir / "alerts_130000.json").write_text("{not valid json", encoding="utf-8")

    with patch.object(svc, "_PERSISTENT_CACHE_DIR", cache_dir):
        result = svc._load_persistent_cache("130000")

    assert result is None


def test_save_persistent_cache_write_failure_is_graceful(tmp_path):
    """mkdir成功後のfile write失敗（例: permission denied相当）でも例外を外へ漏らさない。"""
    import app.services.weather_alert_service as svc

    cache_dir = tmp_path / "cache" / "weather"
    with patch.object(svc, "_PERSISTENT_CACHE_DIR", cache_dir), \
         patch.object(Path, "open", side_effect=PermissionError("[Errno 13] Permission denied")):
        # 例外を送出せず正常return（ログ警告のみ）することを確認する
        svc._save_persistent_cache("130000", _sample_items())


def test_get_alerts_for_location_stale_falls_back_to_persistent_cache(tmp_path):
    """メモリキャッシュなし・JMA取得失敗時、永続cacheがあればstatus=staleで返す。"""
    import app.services.weather_alert_service as svc

    cache_dir = tmp_path / "cache" / "weather"
    with patch.object(svc, "_PERSISTENT_CACHE_DIR", cache_dir):
        svc._save_persistent_cache("130000", _sample_items())

        svc._alert_cache.clear()
        with patch.object(svc, "resolve_pref_code", return_value=("130000", "東京都")), \
             patch.object(svc, "_resolve_city", return_value=(None, None)), \
             patch.object(svc, "fetch_warnings_for_pref", side_effect=RuntimeError("JMA unavailable")):
            result = svc.get_alerts_for_location(35.68, 139.77)

    assert result["status"] == "stale"
    assert result["alerts"]
    assert result["alerts"][0]["kind"] == "大雨警報"
