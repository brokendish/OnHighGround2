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
    """reason は非空文字列であること（Phase 2-A では sampled_nowcast / tile_only / 等）。"""
    body = _run(get_live_summary())
    reason = body["rain"].get("reason")
    assert isinstance(reason, str) and len(reason) > 0


# ── kikikuru セクション ──────────────────────────────────────────────────────

def test_kikikuru_evaluated_is_boolean():
    body = _run(get_live_summary())
    assert isinstance(body["kikikuru"].get("evaluated"), bool)


def test_kikikuru_evaluated_is_false_for_tile_only():
    body = _run(get_live_summary())
    assert body["kikikuru"]["evaluated"] is False


def test_kikikuru_status_is_valid():
    body = _run(get_live_summary())
    assert body["kikikuru"]["status"] in _VALID_STATUSES


def test_kikikuru_danger_detected_is_null_when_unevaluated():
    """evaluated=False のとき danger_detected は null（False にしない）。"""
    body = _run(get_live_summary())
    kk = body["kikikuru"]
    assert kk["evaluated"] is False
    assert kk["summary"]["danger_detected"] is None


def test_kikikuru_has_reason_tile_only():
    body = _run(get_live_summary())
    assert body["kikikuru"].get("reason") == "tile_only"


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
