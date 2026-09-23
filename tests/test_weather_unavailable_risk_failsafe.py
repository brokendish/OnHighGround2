"""
test_weather_unavailable_risk_failsafe.py — 警報・降水の取得失敗（unavailable）fail-safe 回帰テスト

WEATHER-ALERTS-UNAVAILABLE-RISK-FAILSAFE:
  - 取得失敗（unavailable）を「警報なし」「降水なし」＝ none と扱わない
  - 正常取得の none は none のまま
  - 既知の advisory/warning/emergency は unavailable に上書きされない
  - 取得失敗の区別は weather.alert_status / weather.precip_status で保持される

入力は各サービスの実際の失敗レスポンス（get_alerts_for_location / get_precipitation_summary の
unavailable 形）を実コード経由で生成し、外部APIは呼ばない。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.services.weather_alert_service as was  # noqa: E402
import app.services.weather_risk_context_service as rcs  # noqa: E402

# ── 実サービスの失敗レスポンスを生成 ─────────────────────────────────────────


def _alerts_unavailable() -> dict:
    """JMA 取得失敗・stale cache なし → get_alerts_for_location の実 unavailable 応答。"""
    was._alert_cache.clear()
    with patch.object(was, "resolve_pref_code", return_value=("130000", "東京都")), \
         patch.object(was, "_resolve_city", return_value=(None, None)), \
         patch.object(was, "fetch_warnings_for_pref", side_effect=RuntimeError("JMA down")), \
         patch.object(was, "_load_persistent_cache", return_value=None):
        data = was.get_alerts_for_location(35.68, 139.77)
    was._alert_cache.clear()
    assert data["status"] == "unavailable"
    return data


def _precip_unavailable() -> dict:
    """ナウキャストタイル取得失敗 → _build_precip_summary の実 unavailable 応答。"""
    import services.jma_rain_tile_service as tiles
    with patch.object(tiles, "get_rain_tile_times", side_effect=RuntimeError("tile down")):
        data = was._build_precip_summary(35.68, 139.77, "2026-09-23T00:00:00+00:00")
    assert data["status"] == "unavailable"
    return data


def _alerts(severity: str) -> dict:
    return {"status": "ok", "severity": severity, "alerts": []}


def _precip(severity: str) -> dict:
    intensity = {"none": "none", "advisory": "weak", "warning": "strong"}[severity]
    return {"status": "ok", "severity": severity,
            "current": {"intensity": intensity}, "forecast": []}


ALERTS = {
    "unavailable": _alerts_unavailable,
    "none":        lambda: _alerts("none"),
    "unknown":     lambda: _alerts("unknown"),
    "advisory":    lambda: _alerts("advisory"),
    "warning":     lambda: _alerts("warning"),
    "emergency":   lambda: _alerts("emergency"),
}
PRECIP = {
    "unavailable": _precip_unavailable,
    "none":        lambda: _precip("none"),
    "warning":     lambda: _precip("warning"),
}


def _risk(alerts: dict, precip: dict) -> dict:
    """get_risk_context を実行（ハザードなし＝other risk none）。"""
    rcs._RISK_CACHE.clear()
    with patch.object(rcs, "get_alerts_for_location", return_value=alerts), \
         patch.object(rcs, "get_precipitation_summary", return_value=precip), \
         patch.object(rcs, "get_hazard_service", return_value=None):
        data = rcs.get_risk_context(35.68, 139.77)
    rcs._RISK_CACHE.clear()
    return data


# ── 実サービスの失敗レスポンスは status=unavailable を持つ（前提確認）────────────

def test_real_failure_responses_carry_unavailable_status():
    a = _alerts_unavailable()
    assert a["alerts"] == [] and a["message"] == "気象情報を取得できません"
    p = _precip_unavailable()
    assert p["forecast"] == [] and p["current"]["intensity"] == "unknown"


# ── Case A〜H ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case,alerts,precip,expected", [
    ("A", "unavailable", "none",        "unknown"),
    ("B", "none",        "unavailable", "unknown"),
    ("C", "unavailable", "unavailable", "unknown"),
    ("D", "none",        "none",        "none"),
    ("E", "unknown",     "none",        "unknown"),
    ("F", "warning",     "unavailable", "warning"),
    ("G", "emergency",   "unavailable", "emergency"),
    ("H", "advisory",    "unavailable", "advisory"),
])
def test_risk_context_cases(case, alerts, precip, expected):
    data = _risk(ALERTS[alerts](), PRECIP[precip]())
    assert data["status"] == "ok"
    assert data["risk_level"] == expected, f"Case {case}"
    if expected == "unknown":
        assert data["risk_level"] != "none"


@pytest.mark.parametrize("alerts,precip,alert_status,precip_status", [
    ("unavailable", "none",        "unavailable", "ok"),
    ("none",        "unavailable", "ok",          "unavailable"),
    ("unavailable", "unavailable", "unavailable", "unavailable"),
    ("none",        "none",        "ok",          "ok"),
])
def test_unavailable_status_is_preserved_in_context(alerts, precip, alert_status, precip_status):
    weather = _risk(ALERTS[alerts](), PRECIP[precip]())["weather"]
    assert weather["alert_status"] == alert_status
    assert weather["precip_status"] == precip_status


def test_alerts_unavailable_plus_known_precip_warning_keeps_warning():
    assert _risk(ALERTS["unavailable"](), PRECIP["warning"]())["risk_level"] == "warning"


def test_precip_unavailable_plus_unknown_alert_is_unknown():
    assert _risk(ALERTS["unknown"](), PRECIP["unavailable"]())["risk_level"] == "unknown"


def test_alert_fetch_exception_path_is_not_none():
    """get_alerts_for_location 自体が例外 → risk context 内 fallback も none にしない。"""
    rcs._RISK_CACHE.clear()
    with patch.object(rcs, "get_alerts_for_location", side_effect=RuntimeError("boom")), \
         patch.object(rcs, "get_precipitation_summary", return_value=_precip("none")), \
         patch.object(rcs, "get_hazard_service", return_value=None):
        data = rcs.get_risk_context(35.68, 139.77)
    rcs._RISK_CACHE.clear()
    assert data["weather"]["alert_status"] == "unavailable"
    assert data["risk_level"] == "unknown"


def test_legacy_inputs_without_status_are_treated_as_ok():
    """status キーを持たない既存呼び出しは従来どおり（none のまま）。"""
    weather = rcs._build_weather_summary({"severity": "none"}, {"severity": "none"})
    assert weather["alert_status"] == "ok" and weather["precip_status"] == "ok"
    assert rcs._compute_risk_level(weather, {}, []) == "none"


# ── stale fallback（既存 policy: stale 値で評価）は変更しない ─────────────────

def test_stale_alerts_are_evaluated_with_stale_values():
    stale_warning = {"status": "stale", "severity": "warning", "alerts": []}
    stale_none = {"status": "stale", "severity": "none", "alerts": []}
    assert _risk(stale_warning, _precip("none"))["risk_level"] == "warning"
    ctx = _risk(stale_none, _precip("none"))
    assert ctx["weather"]["alert_status"] == "stale"
    assert ctx["risk_level"] == "none"


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    from fastapi import FastAPI
    from _testclient_compat import TestClient
    from app.api.weather import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_api_risk_context_alerts_unavailable(api_client):
    alerts, precip = ALERTS["unavailable"](), PRECIP["none"]()
    rcs._RISK_CACHE.clear()
    with patch.object(rcs, "get_alerts_for_location", return_value=alerts), \
         patch.object(rcs, "get_precipitation_summary", return_value=precip), \
         patch.object(rcs, "get_hazard_service", return_value=None):
        res = api_client.get("/api/weather/risk/context", params={"lat": 35.68, "lon": 139.77})
    rcs._RISK_CACHE.clear()
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "unknown"
    assert body["weather"]["alert_status"] == "unavailable"
    assert body["weather"]["precip_status"] == "ok"


def test_api_risk_context_internal_error_fallback_marks_unavailable(api_client):
    import app.api.weather as weather_api
    with patch.object(weather_api, "get_risk_context", side_effect=RuntimeError("boom")):
        body = api_client.get("/api/weather/risk/context", params={"lat": 35.68, "lon": 139.77}).json()
    assert body["risk_level"] == "unknown"
    assert body["weather"]["alert_status"] == "unavailable"
    assert body["weather"]["precip_status"] == "unavailable"


def test_api_warnings_alerts_unavailable_is_ok_false(api_client):
    """/api/weather/warnings は取得失敗を ok=false で返す（has_warning/max_level=none 形にしない）。"""
    import app.services.jma_warning_service as jws
    with patch.object(jws, "get_alerts_for_location", return_value=_alerts_unavailable()):
        body = api_client.get("/api/weather/warnings", params={"lat": 35.68, "lon": 139.77}).json()
    assert body["ok"] is False
    assert body["reason"] == "failed_to_fetch_warning_data"
    assert "max_level" not in body and "has_warning" not in body


# ── route risk（_compute_risk_level 共有）: 降水取得失敗の点を none にしない ──

def test_route_risk_point_precip_unavailable_is_unknown():
    import app.services.weather_route_risk_service as wrr
    with patch.object(wrr, "get_precipitation_summary", return_value=_precip_unavailable()), \
         patch.object(wrr, "_fetch_hazard_assessment", return_value={}):
        point = wrr._assess_point(35.68, 139.77)
    assert point["risk_level"] == "unknown"
    assert point["weather"]["precip_status"] == "unavailable"
