"""
test_live_rain_summary_service.py — live_rain_summary_service ユニットテスト

build_rain_section_from_samples() の純粋ロジックを検証する。
JMA 外部 API は一切呼ばない。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.live_rain_summary_service import (
    LIVE_RAIN_SAMPLE_POINTS,
    build_rain_section_from_samples,
)

_OBS_AT = "2026-05-27T22:40:00+09:00"


def _make_samples(intensities: list[str]) -> list[dict]:
    """強度リストをサンプル地点データに変換する（地点数は intensities に合わせる）。"""
    pts = LIVE_RAIN_SAMPLE_POINTS[: len(intensities)]
    return [
        {**pt, "intensity": intens, "rain_class": -1 if intens == "unknown" else 0, "source": "test"}
        for pt, intens in zip(pts, intensities)
    ]


# ── 基本構造 ──────────────────────────────────────────────────────────────────

def test_section_has_required_keys():
    samples = _make_samples(["none"] * 5)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    for key in ("status", "evaluated", "reason", "summary", "areas"):
        assert key in sec


def test_summary_has_required_keys():
    samples = _make_samples(["none"] * 5)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    for key in ("strong_rain_detected", "warning_area_count", "danger_area_count",
                "sample_count", "unknown_count"):
        assert key in sec["summary"]


def test_areas_is_list():
    samples = _make_samples(["none"] * 5)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert isinstance(sec["areas"], list)


# ── 強雨なし ──────────────────────────────────────────────────────────────────

def test_no_strong_rain_detected_false():
    samples = _make_samples(["none", "weak", "moderate", "none", "weak"])
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert sec["summary"]["strong_rain_detected"] is False
    assert sec["areas"] == []


def test_no_strong_rain_reason_sampled_nowcast():
    samples = _make_samples(["none"] * 8)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["reason"] == "sampled_nowcast"


def test_no_strong_rain_status_ok():
    samples = _make_samples(["weak"] * 5)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["status"] == "ok"


# ── 強雨あり ──────────────────────────────────────────────────────────────────

def test_strong_rain_detected_true():
    samples = _make_samples(["none", "none", "strong", "none", "none"])
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert sec["summary"]["strong_rain_detected"] is True


def test_severe_rain_detected_true():
    samples = _make_samples(["severe"] + ["none"] * 4)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["strong_rain_detected"] is True


def test_strong_rain_area_level_is_warning():
    samples = _make_samples(["strong"] + ["none"] * 4)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert len(sec["areas"]) == 1
    assert sec["areas"][0]["level"] == "warning"


def test_severe_rain_area_level_is_danger():
    samples = _make_samples(["severe"] + ["none"] * 4)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert len(sec["areas"]) == 1
    assert sec["areas"][0]["level"] == "danger"


def test_area_has_type_rain():
    samples = _make_samples(["strong"] + ["none"] * 4)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["areas"][0]["type"] == "rain"


def test_area_has_lat_lng():
    samples = _make_samples(["severe"] + ["none"] * 4)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    area = sec["areas"][0]
    assert area["lat"] is not None
    assert area["lng"] is not None


def test_warning_area_count():
    samples = _make_samples(["strong", "strong", "none", "none", "none"])
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["warning_area_count"] == 2
    assert sec["summary"]["danger_area_count"] == 0


def test_danger_area_count():
    samples = _make_samples(["severe", "none", "none", "none", "none"])
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["danger_area_count"] == 1
    assert sec["summary"]["warning_area_count"] == 0


# ── moderate は危険地域に含めない ─────────────────────────────────────────────

def test_moderate_does_not_enter_areas():
    samples = _make_samples(["moderate"] * 5)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["areas"] == []
    assert sec["summary"]["strong_rain_detected"] is False


# ── unknown 過多 → false-safe 防止 ────────────────────────────────────────────

def test_too_many_unknown_evaluated_false():
    """unknown が 50% 以上なら evaluated=False（false-safe 防止）。"""
    samples = _make_samples(["unknown"] * 6 + ["none"] * 5)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is False
    assert sec["summary"]["strong_rain_detected"] is None


def test_too_many_unknown_reason():
    samples = _make_samples(["unknown"] * 6 + ["none"] * 5)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["reason"] == "too_many_unknown_samples"


def test_too_many_unknown_not_false_safe():
    """unknown 過多のとき strong_rain_detected は False であってはならない。"""
    samples = _make_samples(["unknown"] * 6 + ["none"] * 5)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["strong_rain_detected"] is not False


def test_unknown_below_threshold_still_evaluates():
    """unknown が 49% 未満なら評価可能。"""
    samples = _make_samples(["unknown"] * 4 + ["none"] * 7)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True


# ── 空サンプル → offline ──────────────────────────────────────────────────────

def test_empty_samples_returns_offline():
    sec = build_rain_section_from_samples([], _OBS_AT)
    assert sec["status"] == "offline"
    assert sec["evaluated"] is False
    assert sec["summary"]["strong_rain_detected"] is None


# ── サンプル件数 ──────────────────────────────────────────────────────────────

def test_sample_count_correct():
    samples = _make_samples(["none"] * 7)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["sample_count"] == 7


def test_unknown_count_correct():
    samples = _make_samples(["unknown", "unknown", "none", "none", "none"])
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["unknown_count"] == 2


# ── LIVE_RAIN_SAMPLE_POINTS 定義確認 ─────────────────────────────────────────

def test_sample_points_count():
    assert len(LIVE_RAIN_SAMPLE_POINTS) >= 8


def test_sample_points_have_required_fields():
    for pt in LIVE_RAIN_SAMPLE_POINTS:
        assert "id" in pt
        assert "lat" in pt
        assert "lng" in pt
        assert "prefecture" in pt
