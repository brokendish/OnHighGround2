"""
test_jma_warning_code_2026.py — JMA 2026年新体系コード追従 + unknown fail-safe の回帰テスト

JMA-2026-WARNING-CODE-UPDATE-AND-UNKNOWN-FAILSAFE:
  - 新体系コード 09/29/39/43/48/49 の名称・severity 登録
  - r8 kinds[].name なしでも正式名称に復元されること（generic 表示に落ちない）
  - 真の unknown code は item を保持し、none（安全）と断定しないこと
  - /api/weather/warnings・risk context・/live 高潮集計の回帰

外部APIは一切呼ばない。r8 payload は 2026-09-23 取得の東京都 r8 JSON（大島町 1336100）を
最小化した fixture を使用する。
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import jma_weather_adapter as adapter  # noqa: E402
from app.services.jma_weather_adapter import (  # noqa: E402
    STORM_SURGE_CODE_META,
    STORM_SURGE_CODES,
    _CODE_NAME,
    _CODE_SEVERITY,
    _make_alert_item,
    _parse_legacy_payload,
    _parse_r8_payload,
    filter_alerts_for_city,
)
from app.models.weather_alert import max_severity  # noqa: E402

_ADAPTER_LOGGER = "app.services.jma_weather_adapter"

# JMA 現行コード管理表（2026年防災気象情報体系）で確認済みの新コード
# code → (公式名称, OnHighGround2 severity)
_NEW_2026_CODES = {
    "09": ("レベル３土砂災害警報", "warning"),
    "29": ("レベル２土砂災害注意報", "advisory"),
    "39": ("レベル５土砂災害特別警報", "emergency"),
    "43": ("レベル４大雨危険警報", "warning"),
    "48": ("レベル４高潮危険警報", "warning"),
    "49": ("レベル４土砂災害危険警報", "warning"),
}

_OSHIMA_CLASS20 = "1336100"   # 大島町
_OSHIMA_CLASS10 = "130020"    # 伊豆諸島北部（fixture 用）


def _kind(code, status, **extra):
    k = {"status": status}
    if code is not None:
        k["code"] = code
    k.update(extra)
    return k


def _record(report_dt, class10=None, class20=None):
    return {
        "reportDatetime": report_dt,
        "warning": {
            "class10Items": class10 or [],
            "class20Items": class20 or [],
        },
    }


def _code29_kind(status="継続"):
    # 実データ形式: name なし / properties 内の locals.code=21 は warn_code ではない
    return _kind("29", status, properties=[{
        "type": "土砂災害危険度",
        "significancyPart": {"locals": [{"code": "21"}]},
    }])


def _oshima_payload():
    """2026-09-23 東京都 r8 JSON（大島町）相当の fixture。"""
    return [
        _record("2026-09-21T21:09:00+09:00",
                class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_kind(None, "発表警報・注意報はなし")]}]),
        _record("2026-09-23T01:52:00+09:00",
                class10=[{"areaCode": _OSHIMA_CLASS10, "kinds": [_code29_kind("継続")]}],
                class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_code29_kind("継続")]}]),
        _record("2026-09-23T04:04:00+09:00",
                class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_kind("15", "解除")]}]),
        _record("2026-09-22T14:33:00+09:00",
                class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_kind("16", "解除")]}]),
    ]


def _warn_msgs(caplog):
    return [r.getMessage() for r in caplog.records
            if r.name == _ADAPTER_LOGGER and r.levelno >= logging.WARNING]


# ── A. adapter unit: code 29 ────────────────────────────────────────────────

def test_code29_without_name_resolves_official_name_and_advisory(caplog):
    with caplog.at_level(logging.WARNING, logger=_ADAPTER_LOGGER):
        items = _parse_r8_payload(_oshima_payload(), "東京都")

    oshima = [i for i in items if i.area_code == _OSHIMA_CLASS20]
    assert len(oshima) == 1
    item = oshima[0]
    assert item.raw_code == "29"
    assert item.kind == "レベル２土砂災害注意報"
    assert item.severity == "advisory"
    assert item.level == "注意報"
    assert item.status == "継続"
    assert "コード29" not in item.kind
    assert item.headline == "レベル２土砂災害注意報 継続"
    assert item.is_high_priority()  # 「土砂災害」キーワード
    assert not _warn_msgs(caplog), "正式コード29で unknown WARNING が出た"


def test_code29_properties_local_code_21_is_not_treated_as_warn_code():
    items = _parse_r8_payload(_oshima_payload(), "東京都")
    assert all(i.raw_code != "21" for i in items)  # 21=乾燥注意報 と誤認しない


# ── B. 新体系コード表 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,expected", sorted(_NEW_2026_CODES.items()))
def test_new_2026_code_registered(code, expected, caplog):
    name, severity = expected
    assert _CODE_NAME.get(code) == name
    assert _CODE_SEVERITY.get(code) == severity

    with caplog.at_level(logging.WARNING, logger=_ADAPTER_LOGGER):
        item = _make_alert_item("1336100", "大島町", code, "発表", "2026-09-23T00:00:00+09:00", "東京都")
    assert item.kind == name
    assert item.severity == severity
    assert not _warn_msgs(caplog), f"正式コード{code}で unknown WARNING が出た"


def test_code_name_and_severity_tables_have_same_keys():
    assert set(_CODE_NAME) == set(_CODE_SEVERITY)


def test_severity_values_stay_within_existing_contract():
    assert set(_CODE_SEVERITY.values()) <= {"emergency", "warning", "advisory"}


@pytest.mark.parametrize("code", sorted(_CODE_SEVERITY))
def test_severity_is_consistent_with_official_name(code):
    """名称の区分（特別警報/警報/注意報）と severity が矛盾しない。"""
    name = _CODE_NAME[code]
    expected = adapter._infer_severity_from_name(name)
    if expected != "unknown":
        assert _CODE_SEVERITY[code] == expected, f"{code}:{name}"


def test_existing_known_codes_unchanged():
    assert _CODE_NAME["03"] == "大雨警報" and _CODE_SEVERITY["03"] == "warning"
    assert _CODE_NAME["10"] == "大雨注意報" and _CODE_SEVERITY["10"] == "advisory"
    assert _CODE_NAME["21"] == "乾燥注意報" and _CODE_SEVERITY["21"] == "advisory"
    assert _CODE_NAME["33"] == "大雨特別警報" and _CODE_SEVERITY["33"] == "emergency"


# ── Name fallback 優先順位 ────────────────────────────────────────────────────

def test_name_priority_upstream_name_wins():
    item = _make_alert_item("1", "a", "29", "発表", "t", "p", upstream_name="上流名称注意報")
    assert item.kind == "上流名称注意報"


def test_name_priority_dictionary_when_upstream_missing():
    item = _make_alert_item("1", "a", "29", "発表", "t", "p", upstream_name=None)
    assert item.kind == "レベル２土砂災害注意報"
    item = _make_alert_item("1", "a", "29", "発表", "t", "p", upstream_name="  ")
    assert item.kind == "レベル２土砂災害注意報"


def test_name_priority_generic_only_for_true_unknown():
    item = _make_alert_item("1", "a", "99", "発表", "t", "p")
    assert item.kind == "警報・注意報（コード99）"


def test_r8_upstream_name_is_used_when_present():
    payload = [_record("2026-09-23T00:00:00+09:00",
                       class20=[{"areaCode": "X", "kinds": [_kind("98", "発表", name="将来の新警報")]}])]
    items = _parse_r8_payload(payload, "東京都")
    assert items[0].kind == "将来の新警報"
    assert items[0].severity == "warning"  # 名称から推定（既存 fallback）


def test_legacy_parser_name_fallback():
    payload = {"reportDatetime": "2026-09-23T00:00:00+09:00", "areaTypes": [{"areas": [{
        "code": "130020", "name": "伊豆諸島北部",
        "warnings": [
            {"code": "29", "status": "継続"},
            {"code": "97", "name": "上流だけが知る注意報", "status": "発表"},
            {"code": "99", "status": "発表"},
        ],
    }]}]}
    items = {i.raw_code: i for i in _parse_legacy_payload(payload, "東京都", None)}
    assert items["29"].kind == "レベル２土砂災害注意報"
    assert items["29"].severity == "advisory"
    assert items["97"].kind == "上流だけが知る注意報"
    assert items["97"].severity == "advisory"
    assert items["99"].kind == "警報・注意報（コード99）"
    assert items["99"].severity == "unknown"


# ── C. class10 / class20 / 最新優先 / 発表・継続・解除 ────────────────────────

def test_code29_class10_and_class20_both_parsed():
    items = _parse_r8_payload(_oshima_payload(), "東京都")
    codes = {(i.area_code, i.raw_code) for i in items}
    assert (_OSHIMA_CLASS10, "29") in codes
    assert (_OSHIMA_CLASS20, "29") in codes


def test_code29_class20_filter_by_city():
    items = _parse_r8_payload(_oshima_payload(), "東京都")
    filtered = filter_alerts_for_city(items, "大島町", city_class20_map={"大島町": _OSHIMA_CLASS20})
    assert [(i.area_code, i.kind) for i in filtered] == [(_OSHIMA_CLASS20, "レベル２土砂災害注意報")]


def test_code29_latest_report_datetime_wins_release():
    payload = [
        _record("2026-09-23T01:00:00+09:00",
                class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_code29_kind("発表")]}]),
        _record("2026-09-23T09:00:00+09:00",
                class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_code29_kind("解除")]}]),
    ]
    assert _parse_r8_payload(payload, "東京都") == []


def test_code29_latest_report_datetime_wins_reissue():
    payload = [
        _record("2026-09-23T09:00:00+09:00",
                class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_code29_kind("継続")]}]),
        _record("2026-09-23T01:00:00+09:00",
                class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_code29_kind("解除")]}]),
    ]
    items = _parse_r8_payload(payload, "東京都")
    assert [(i.raw_code, i.status) for i in items] == [("29", "継続")]


@pytest.mark.parametrize("status,active", [("発表", True), ("継続", True), ("解除", False)])
def test_code29_status_handling(status, active):
    payload = [_record("2026-09-23T01:00:00+09:00",
                       class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_code29_kind(status)]}])]
    items = _parse_r8_payload(payload, "東京都")
    assert bool(items) is active
    if active:
        assert items[0].kind == "レベル２土砂災害注意報"
        assert items[0].status == status


# ── D. 真の unknown ──────────────────────────────────────────────────────────

def test_true_unknown_code_kept_with_warning_log(caplog):
    payload = [_record("2026-09-23T01:00:00+09:00",
                       class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": [_kind("99", "発表")]}])]
    with caplog.at_level(logging.WARNING, logger=_ADAPTER_LOGGER):
        items = _parse_r8_payload(payload, "東京都")

    assert len(items) == 1
    item = items[0]
    assert item.raw_code == "99"
    assert item.kind == "警報・注意報（コード99）"
    assert item.severity == "unknown"
    assert item.level == "不明"
    assert any("99" in m for m in _warn_msgs(caplog))
    assert max_severity(items) == "unknown"  # none に落ちない


# ── F. mixed codes（adapter/model レベル）─────────────────────────────────────

def _items_for(kinds):
    payload = [_record("2026-09-23T01:00:00+09:00",
                       class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": kinds}])]
    return _parse_r8_payload(payload, "東京都")


def test_mixed_29_and_known_warning():
    items = _items_for([_code29_kind("継続"), _kind("03", "発表")])
    assert max_severity(items) == "warning"
    assert {i.kind for i in items} == {"レベル２土砂災害注意報", "大雨警報"}


def test_mixed_29_and_unknown():
    items = _items_for([_code29_kind("継続"), _kind("99", "発表")])
    assert max_severity(items) == "advisory"
    assert {i.severity for i in items} == {"advisory", "unknown"}


def test_mixed_29_and_released_code():
    items = _items_for([_code29_kind("継続"), _kind("10", "解除")])
    assert [(i.raw_code, i.kind) for i in items] == [("29", "レベル２土砂災害注意報")]


# ── E. API: /api/weather/warnings, /api/weather/alerts/current ───────────────

@pytest.fixture
def api_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.weather import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _patched_alerts(kinds):
    """weather_alert_service を fixture r8 payload で駆動する context。"""
    import app.services.weather_alert_service as was

    payload = [_record("2026-09-23T01:52:00+09:00",
                       class20=[{"areaCode": _OSHIMA_CLASS20, "kinds": kinds}])]

    def _fetch(pref_code, pref_name, reported_at=None):
        return _parse_r8_payload(payload, pref_name)

    was._alert_cache.clear()
    return [
        patch.object(was, "resolve_pref_code", return_value=("130000", "東京都")),
        patch.object(was, "_resolve_city", return_value=("大島町", None)),
        patch.object(was, "filter_alerts_for_city", side_effect=lambda items, city: items),
        patch.object(was, "fetch_warnings_for_pref", side_effect=_fetch),
        patch.object(was, "_save_persistent_cache", return_value=None),
    ]


def _call(api_client, path, kinds):
    import contextlib
    with contextlib.ExitStack() as stack:
        for p in _patched_alerts(kinds):
            stack.enter_context(p)
        res = api_client.get(path, params={"lat": 34.75, "lon": 139.36})
    import app.services.weather_alert_service as was
    was._alert_cache.clear()
    return res


def test_api_warnings_code29_only(api_client):
    res = _call(api_client, "/api/weather/warnings", [_code29_kind("継続")])
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["items"] == [{"name": "レベル２土砂災害注意報", "level": "注意報", "status": "継続"}]
    assert body["max_level"] == "advisory"
    assert body["has_warning"] is False   # 既存仕様: emergency/warning のみ true
    assert body["has_unknown"] is False


def test_api_warnings_true_unknown_only(api_client):
    res = _call(api_client, "/api/weather/warnings", [_kind("99", "発表")])
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["items"] == [{"name": "警報・注意報（コード99）", "level": "不明", "status": "発表"}]
    assert body["max_level"] == "unknown"          # none / advisory と断定しない
    assert body["max_level"] not in ("none", "advisory")
    assert body["has_unknown"] is True
    assert body["has_warning"] is False


def test_api_warnings_29_plus_unknown(api_client):
    body = _call(api_client, "/api/weather/warnings", [_code29_kind("継続"), _kind("99", "発表")]).json()
    assert body["max_level"] == "advisory"
    assert body["has_unknown"] is True
    assert len(body["items"]) == 2


def test_api_warnings_29_plus_known_warning(api_client):
    body = _call(api_client, "/api/weather/warnings", [_code29_kind("継続"), _kind("09", "発表")]).json()
    assert body["max_level"] == "warning"
    assert body["has_warning"] is True
    assert {i["name"] for i in body["items"]} == {"レベル２土砂災害注意報", "レベル３土砂災害警報"}


def test_api_warnings_no_alerts_still_none(api_client):
    body = _call(api_client, "/api/weather/warnings", [_code29_kind("解除")]).json()
    assert body["items"] == []
    assert body["max_level"] == "none"
    assert body["has_unknown"] is False


def test_api_alerts_current_code29(api_client):
    res = _call(api_client, "/api/weather/alerts/current", [_code29_kind("継続")])
    assert res.status_code == 200
    body = res.json()
    assert body["severity"] == "advisory"
    assert body["alerts"][0]["kind"] == "レベル２土砂災害注意報"
    assert body["message"] is None


def test_api_alerts_current_true_unknown(api_client):
    body = _call(api_client, "/api/weather/alerts/current", [_kind("99", "発表")]).json()
    assert body["severity"] == "unknown"
    assert body["alerts"][0]["raw_code"] == "99"
    assert body["message"] != "警報・注意報なし"


# ── G. 統合リスク（backend）────────────────────────────────────────────────────

def _risk_level(alert_severity, precip_severity="none", combined=None):
    from app.services.weather_risk_context_service import _compute_risk_level
    weather = {
        "alert_severity": alert_severity, "precip_severity": precip_severity,
        "current_intensity": "none", "forecast_max_intensity": "none", "forecast_max_minutes": None,
    }
    return _compute_risk_level(weather, {}, combined or [])


def test_risk_unknown_alert_with_no_precip_is_not_none():
    assert _risk_level("unknown", "none") == "unknown"


def test_risk_code29_advisory():
    assert _risk_level("advisory", "none") == "advisory"


def test_risk_unknown_does_not_override_known():
    assert _risk_level("unknown", "warning") == "warning"
    assert _risk_level("unknown", "advisory") == "advisory"
    assert _risk_level("unknown", "none", [{"level": "emergency"}]) == "emergency"


def test_risk_none_regression():
    assert _risk_level("none", "none") == "none"
    assert _risk_level("none", "unknown") == "unknown"


def test_risk_context_end_to_end_unknown_only():
    import app.services.weather_risk_context_service as rcs
    rcs._RISK_CACHE.clear()
    alerts = {"status": "ok", "severity": "unknown", "alerts": [{"kind": "警報・注意報（コード99）", "severity": "unknown"}]}
    precip = {"status": "ok", "severity": "none", "current": {"intensity": "none"}, "forecast": []}
    with patch.object(rcs, "get_alerts_for_location", return_value=alerts), \
         patch.object(rcs, "get_precipitation_summary", return_value=precip), \
         patch.object(rcs, "get_hazard_service", return_value=None):
        data = rcs.get_risk_context(34.75, 139.36)
    rcs._RISK_CACHE.clear()
    assert data["status"] == "ok"
    assert data["weather"]["alert_severity"] == "unknown"
    assert data["risk_level"] == "unknown"


# ── I. /live 高潮集計 ─────────────────────────────────────────────────────────

def test_code48_is_storm_surge_and_consistent():
    assert "48" in STORM_SURGE_CODES
    assert STORM_SURGE_CODE_META["48"] == {"severity": "warning", "label": "レベル４高潮危険警報"}


@pytest.mark.parametrize("code", ["09", "29", "39", "43", "49"])
def test_sediment_and_rain_codes_not_in_storm_surge(code):
    assert code not in STORM_SURGE_CODES


def test_live_storm_surge_excludes_sediment_codes_and_includes_48():
    import app.services.live_storm_surge_service as lss

    kinds = [_code29_kind("継続"), _kind("09", "発表"), _kind("39", "発表"),
             _kind("43", "発表"), _kind("49", "発表"), _kind("99", "発表")]
    items_no_surge = _parse_r8_payload(
        [_record("2026-09-23T01:00:00+09:00", class20=[{"areaCode": "1310100", "kinds": kinds}])], "東京都")
    with patch.object(lss, "fetch_warnings_for_pref", return_value=items_no_surge):
        assert asyncio.run(lss._fetch_pref_storm_surge("130000")) == []

    items_with_48 = _parse_r8_payload(
        [_record("2026-09-23T01:00:00+09:00",
                 class20=[{"areaCode": "1310100", "kinds": kinds + [_kind("48", "発表")]}])], "東京都")
    with patch.object(lss, "fetch_warnings_for_pref", return_value=items_with_48):
        result = asyncio.run(lss._fetch_pref_storm_surge("130000"))
    assert len(result) == 1
    assert result[0]["kind"] == "レベル４高潮危険警報"
    assert result[0]["level"] == "warning"
    assert [a["kind"] for a in result[0]["affected_areas"]] == ["レベル４高潮危険警報"]
