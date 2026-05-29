"""
test_live_summary_api.py — /api/live/summary API 契約テスト

検証観点:
- レスポンス構造と型
- rain / kikikuru の evaluated=False / null 契約
- earthquake / tsunami の evaluated=True
- status が契約値内
- dangerous_areas が配列
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api.live_summary import get_live_summary

_VALID_STATUSES = {"ok", "offline", "stale", "unknown", "degraded"}


def _run(coro):
    return asyncio.run(coro)


# ── 基本レスポンス構造 ───────────────────────────────────────────────────────

def test_live_summary_returns_200_shape():
    body = _run(get_live_summary())

    assert isinstance(body, dict)
    assert "updated_at" in body
    assert "status"     in body
    assert "rain"       in body
    assert "kikikuru"   in body
    assert "earthquake" in body
    assert "tsunami"    in body
    assert "dangerous_areas" in body


def test_live_summary_overall_status_is_valid():
    body = _run(get_live_summary())
    assert body["status"] in _VALID_STATUSES


def test_live_summary_dangerous_areas_is_list():
    body = _run(get_live_summary())
    assert isinstance(body["dangerous_areas"], list)


# ── rain セクション ──────────────────────────────────────────────────────────

def test_rain_evaluated_is_boolean():
    body = _run(get_live_summary())
    rain = body["rain"]
    assert isinstance(rain.get("evaluated"), bool)


def test_rain_evaluated_and_detected_are_consistent():
    """evaluated=True なら strong_rain_detected は bool、evaluated=False なら null。"""
    body = _run(get_live_summary())
    rain = body["rain"]
    if rain["evaluated"] is True:
        assert isinstance(rain["summary"].get("strong_rain_detected"), bool), (
            "evaluated=True なのに strong_rain_detected が bool でない"
        )
    else:
        assert rain["summary"].get("strong_rain_detected") is not False, (
            "evaluated=False なのに strong_rain_detected=False は false-safe 違反"
        )


def test_rain_status_is_valid():
    body = _run(get_live_summary())
    assert body["rain"]["status"] in _VALID_STATUSES


def test_rain_strong_rain_detected_is_null_when_unevaluated():
    """evaluated=False のとき strong_rain_detected は null（False にしない）。"""
    body = _run(get_live_summary())
    rain = body["rain"]
    if rain["evaluated"] is False:
        assert rain["summary"]["strong_rain_detected"] is None


def test_rain_has_reason_string():
    """reason は非空文字列であること（Phase 2-D: tile_scan / scan_failed / source_unavailable 等）。"""
    body = _run(get_live_summary())
    reason = body["rain"].get("reason")
    assert isinstance(reason, str) and len(reason) > 0


def test_rain_scan_metadata_present_when_evaluated():
    """evaluated=True のとき scan_tile_count / scan_pixel_stride が summary に含まれる。"""
    body = _run(get_live_summary())
    rain = body["rain"]
    if rain["evaluated"] is True:
        summary = rain.get("summary", {})
        assert "scan_tile_count" in summary, "scan_tile_count が summary にない"
        assert "scan_pixel_stride" in summary, "scan_pixel_stride が summary にない"


# ── kikikuru セクション ──────────────────────────────────────────────────────

def test_kikikuru_evaluated_is_boolean():
    body = _run(get_live_summary())
    assert isinstance(body["kikikuru"].get("evaluated"), bool)


def test_kikikuru_status_is_valid():
    body = _run(get_live_summary())
    assert body["kikikuru"]["status"] in _VALID_STATUSES


def test_kikikuru_danger_detected_is_null_when_unevaluated():
    """evaluated=False のとき danger_detected は null（False にしない）。"""
    body = _run(get_live_summary())
    kk = body["kikikuru"]
    if kk["evaluated"] is False:
        assert kk["summary"]["danger_detected"] is None


def test_kikikuru_has_reason_string():
    """reason は非空文字列（Phase 3-A: sampled_kikikuru / source_unavailable 等）。"""
    body = _run(get_live_summary())
    reason = body["kikikuru"].get("reason")
    assert isinstance(reason, str) and len(reason) > 0


def test_kikikuru_danger_detected_consistent():
    """evaluated=True なら danger_detected は bool、evaluated=False なら null。"""
    body = _run(get_live_summary())
    kk = body["kikikuru"]
    if kk["evaluated"] is True:
        assert isinstance(kk["summary"].get("danger_detected"), bool), (
            "evaluated=True なのに danger_detected が bool でない"
        )
    else:
        assert kk["summary"].get("danger_detected") is not False, (
            "evaluated=False なのに danger_detected=False は false-safe 違反"
        )


# ── earthquake セクション ────────────────────────────────────────────────────

def test_earthquake_evaluated_is_boolean():
    body = _run(get_live_summary())
    assert isinstance(body["earthquake"].get("evaluated"), bool)


def test_earthquake_status_is_valid():
    body = _run(get_live_summary())
    assert body["earthquake"]["status"] in _VALID_STATUSES


def test_earthquake_areas_is_list():
    body = _run(get_live_summary())
    assert isinstance(body["earthquake"]["areas"], list)


# ── tsunami セクション ───────────────────────────────────────────────────────

def test_tsunami_evaluated_is_boolean():
    body = _run(get_live_summary())
    assert isinstance(body["tsunami"].get("evaluated"), bool)


def test_tsunami_status_is_valid():
    body = _run(get_live_summary())
    assert body["tsunami"]["status"] in _VALID_STATUSES


def test_tsunami_areas_is_list():
    body = _run(get_live_summary())
    assert isinstance(body["tsunami"]["areas"], list)


# ── false-safe 防止契約 ──────────────────────────────────────────────────────

def test_no_false_safe_in_rain():
    """rain evaluated=False なら strong_rain_detected が False であってはならない。"""
    body = _run(get_live_summary())
    rain = body["rain"]
    if rain["evaluated"] is False:
        assert rain["summary"]["strong_rain_detected"] is not False, (
            "evaluated=False なのに strong_rain_detected=False は false-safe 違反"
        )


def test_no_false_safe_in_kikikuru():
    """kikikuru evaluated=False なら danger_detected が False であってはならない。"""
    body = _run(get_live_summary())
    kk = body["kikikuru"]
    if kk["evaluated"] is False:
        assert kk["summary"]["danger_detected"] is not False, (
            "evaluated=False なのに danger_detected=False は false-safe 違反"
        )


# ── Phase 3-C: observation フィールド ────────────────────────────────────────

def test_live_summary_has_observation_field():
    """Phase 3-C: observation フィールドが存在する。"""
    body = _run(get_live_summary())
    assert "observation" in body


def test_observation_has_required_keys():
    """Phase 3-C: observation に必要なキーが揃っている。"""
    body = _run(get_live_summary())
    obs = body.get("observation", {})
    for key in ("rain_area_count", "kikikuru_area_count", "dangerous_area_count", "max_areas"):
        assert key in obs, f"observation に {key} がない"


def test_observation_area_counts_are_int():
    """Phase 3-C: observation の件数フィールドは int。"""
    body = _run(get_live_summary())
    obs = body.get("observation", {})
    assert isinstance(obs.get("rain_area_count"), int)
    assert isinstance(obs.get("kikikuru_area_count"), int)
    assert isinstance(obs.get("dangerous_area_count"), int)


def test_observation_max_areas_is_5():
    """Phase 3-C: max_areas は 5。"""
    body = _run(get_live_summary())
    assert body["observation"]["max_areas"] == 5


def test_observation_dangerous_area_count_matches():
    """Phase 3-C: observation.dangerous_area_count と dangerous_areas の長さが一致する。"""
    body = _run(get_live_summary())
    assert body["observation"]["dangerous_area_count"] == len(body["dangerous_areas"])
