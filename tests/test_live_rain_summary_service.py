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
    _CACHE_TTL,
    _MAX_AREAS,
    _MAX_WORKERS,
    _TOTAL_SAMPLING_TIMEOUT,
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


# ── areas 最大件数制限 ────────────────────────────────────────────────────────

def test_areas_limited_to_max():
    """areas は _MAX_AREAS 件を超えない。"""
    samples = _make_samples(["severe"] * 10 + ["none"] * 37)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert len(sec["areas"]) <= _MAX_AREAS
    assert len(sec["areas"]) == _MAX_AREAS


def test_areas_danger_priority():
    """areas は danger が warning より前に並ぶ。"""
    samples = _make_samples(["strong", "strong", "strong", "severe", "strong"] + ["none"] * 42)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    levels = [a["level"] for a in sec["areas"]]
    danger_indices = [i for i, l in enumerate(levels) if l == "danger"]
    warning_indices = [i for i, l in enumerate(levels) if l == "warning"]
    if danger_indices and warning_indices:
        assert max(danger_indices) < min(warning_indices)


def test_warning_danger_count_reflects_all_detections():
    """summary カウントは areas 上限前の全検出数を反映する。"""
    samples = _make_samples(["severe"] * 10 + ["none"] * 37)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["danger_area_count"] == 10
    assert sec["summary"]["warning_area_count"] == 0
    assert len(sec["areas"]) == _MAX_AREAS


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


def test_warning_with_many_unknowns_still_evaluated():
    """unknown >= 50% でも warning/danger があれば evaluated=True。"""
    # unknown 25件 / total 47件 = 53%、かつ strong 1件
    samples = _make_samples(["unknown"] * 25 + ["strong"] + ["none"] * 21)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert sec["summary"]["strong_rain_detected"] is True


def test_danger_with_many_unknowns_still_evaluated():
    """unknown >= 50% でも danger があれば evaluated=True。"""
    samples = _make_samples(["unknown"] * 30 + ["severe"] + ["none"] * 16)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert sec["summary"]["strong_rain_detected"] is True


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

def test_sample_points_count_is_70_to_80():
    """Phase 2-C: サンプリング地点は 70〜80地点（47都道府県 + 地域代表点）。"""
    assert 70 <= len(LIVE_RAIN_SAMPLE_POINTS) <= 80


def test_sample_points_have_required_fields():
    for pt in LIVE_RAIN_SAMPLE_POINTS:
        assert "id" in pt, f"{pt} に id がない"
        assert "label" in pt, f"{pt} に label がない"
        assert "lat" in pt, f"{pt} に lat がない"
        assert "lng" in pt, f"{pt} に lng がない"
        assert "prefecture" in pt, f"{pt} に prefecture がない"


def test_sample_points_label_has_suffix():
    """label は「○○付近」形式。"""
    for pt in LIVE_RAIN_SAMPLE_POINTS:
        assert pt["label"].endswith("付近"), f"{pt['id']}: label={pt['label']} が「付近」で終わらない"


def test_sample_points_ids_unique():
    """id が重複しない。"""
    ids = [pt["id"] for pt in LIVE_RAIN_SAMPLE_POINTS]
    assert len(ids) == len(set(ids))


def test_sample_count_matches_total_points():
    """全地点サンプルで sample_count が地点数と一致する。"""
    n = len(LIVE_RAIN_SAMPLE_POINTS)
    samples = _make_samples(["none"] * n)
    sec = build_rain_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["sample_count"] == n
    assert 70 <= n <= 80


# ── kind フィールド確認 ───────────────────────────────────────────────────────

def test_sample_points_have_kind_field():
    """Phase 2-C: 各地点に kind フィールドがある。"""
    for pt in LIVE_RAIN_SAMPLE_POINTS:
        assert "kind" in pt, f"{pt['id']} に kind がない"
        assert pt["kind"] in ("prefecture_capital", "regional"), (
            f"{pt['id']}: kind={pt['kind']} が不正"
        )


def test_sample_points_kind_has_prefecture_capitals():
    """47都道府県代表点が prefecture_capital として含まれる。"""
    capitals = [pt for pt in LIVE_RAIN_SAMPLE_POINTS if pt["kind"] == "prefecture_capital"]
    assert len(capitals) == 47


def test_sample_points_kind_has_regionals():
    """地域代表点（regional）が1件以上含まれる。"""
    regionals = [pt for pt in LIVE_RAIN_SAMPLE_POINTS if pt["kind"] == "regional"]
    assert len(regionals) >= 1


# ── TTL / タイムアウト 定数確認 ───────────────────────────────────────────────

def test_cache_ttl_is_120s():
    assert _CACHE_TTL == 120.0


def test_max_workers_is_8():
    assert _MAX_WORKERS == 8


def test_total_sampling_timeout_is_reasonable():
    """Phase 2-C 向けタイムアウトは 24〜36秒以内。"""
    assert 24.0 < _TOTAL_SAMPLING_TIMEOUT <= 36.0


def test_offline_sample_count_matches_total():
    """offline レスポンスの sample_count は地点数と一致する。"""
    from app.services.live_rain_summary_service import _offline_rain_section
    sec = _offline_rain_section()
    assert sec["summary"]["sample_count"] == len(LIVE_RAIN_SAMPLE_POINTS)
    assert sec["summary"]["unknown_count"] == len(LIVE_RAIN_SAMPLE_POINTS)


def test_sampling_concurrency_is_limited():
    assert _MAX_WORKERS == 8


def test_total_sampling_timeout_is_configured():
    assert _TOTAL_SAMPLING_TIMEOUT > 0
