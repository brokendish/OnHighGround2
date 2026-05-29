"""
test_live_kikikuru_summary_service.py — live_kikikuru_summary_service ユニットテスト

build_kikikuru_section_from_samples() の純粋ロジックを検証する。
JMA 外部 API は一切呼ばない。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.live_kikikuru_summary_service import (
    _CACHE_TTL,
    _KIKI_ELEMENTS,
    _MAX_AREAS,
    _MAX_WORKERS,
    _TOTAL_SAMPLING_TIMEOUT,
    build_kikikuru_section_from_samples,
)
from app.services.live_rain_summary_service import LIVE_RAIN_SAMPLE_POINTS

_OBS_AT = "2026-05-29T22:30:00+09:00"


def _make_samples(levels: list[str], hazard: str = "land") -> list[dict]:
    """レベルリストをサンプル地点データに変換する。"""
    pts = LIVE_RAIN_SAMPLE_POINTS[: len(levels)]
    return [
        {**pt, "hazard": hazard, "level": lvl, "source": "test"}
        for pt, lvl in zip(pts, levels)
    ]


# ── 基本構造 ──────────────────────────────────────────────────────────────────

def test_section_has_required_keys():
    samples = _make_samples(["normal"] * 5)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    for key in ("status", "evaluated", "reason", "summary", "areas"):
        assert key in sec


def test_summary_has_required_keys():
    samples = _make_samples(["normal"] * 5)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    for key in ("danger_detected", "watch_area_count", "warning_area_count",
                "danger_area_count", "sample_count", "unknown_count"):
        assert key in sec["summary"]


def test_areas_is_list():
    samples = _make_samples(["normal"] * 5)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert isinstance(sec["areas"], list)


# ── 危険なし ──────────────────────────────────────────────────────────────────

def test_no_danger_detected_false():
    samples = _make_samples(["normal", "watch", "normal", "normal", "watch"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert sec["summary"]["danger_detected"] is False
    assert sec["areas"] == []


def test_no_danger_reason_sampled_kikikuru():
    samples = _make_samples(["normal"] * 8)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["reason"] == "sampled_kikikuru"


def test_no_danger_status_ok():
    samples = _make_samples(["normal"] * 5)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["status"] == "ok"


# ── 危険あり ──────────────────────────────────────────────────────────────────

def test_warning_detected_true():
    samples = _make_samples(["normal", "normal", "warning", "normal", "normal"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert sec["summary"]["danger_detected"] is True


def test_danger_detected_true():
    samples = _make_samples(["danger"] + ["normal"] * 4)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["danger_detected"] is True


def test_warning_area_level():
    samples = _make_samples(["warning"] + ["normal"] * 4)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert len(sec["areas"]) == 1
    assert sec["areas"][0]["level"] == "warning"


def test_danger_area_level():
    samples = _make_samples(["danger"] + ["normal"] * 4)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert len(sec["areas"]) == 1
    assert sec["areas"][0]["level"] == "danger"


def test_area_has_type_kikikuru():
    samples = _make_samples(["danger"] + ["normal"] * 4)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["areas"][0]["type"] == "kikikuru"


def test_area_has_hazard_field():
    samples = _make_samples(["warning"] + ["normal"] * 4, hazard="land")
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["areas"][0]["hazard"] == "land"


def test_area_has_lat_lng():
    samples = _make_samples(["danger"] + ["normal"] * 4)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    area = sec["areas"][0]
    assert area["lat"] is not None
    assert area["lng"] is not None


def test_warning_area_count():
    samples = _make_samples(["warning", "warning", "normal", "normal", "normal"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["warning_area_count"] == 2
    assert sec["summary"]["danger_area_count"] == 0


def test_danger_area_count():
    samples = _make_samples(["danger", "normal", "normal", "normal", "normal"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["danger_area_count"] == 1
    assert sec["summary"]["warning_area_count"] == 0


# ── watch は dangerous_areas に入らない ──────────────────────────────────────

def test_watch_does_not_enter_areas():
    samples = _make_samples(["watch"] * 5)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["areas"] == []
    assert sec["summary"]["danger_detected"] is False


def test_watch_counted_in_summary():
    samples = _make_samples(["watch", "watch", "normal", "normal", "normal"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["watch_area_count"] == 2


# ── areas 最大件数制限 ────────────────────────────────────────────────────────

def test_areas_limited_to_max():
    samples = _make_samples(["danger"] * 10 + ["normal"] * 66)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert len(sec["areas"]) <= _MAX_AREAS
    assert len(sec["areas"]) == _MAX_AREAS


def test_areas_danger_priority():
    samples = _make_samples(["warning", "warning", "danger", "warning", "warning"] + ["normal"] * 71)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    levels = [a["level"] for a in sec["areas"]]
    danger_idx   = [i for i, l in enumerate(levels) if l == "danger"]
    warning_idx  = [i for i, l in enumerate(levels) if l == "warning"]
    if danger_idx and warning_idx:
        assert max(danger_idx) < min(warning_idx)


def test_summary_count_reflects_all_detections():
    samples = _make_samples(["danger"] * 10 + ["normal"] * 66)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["danger_area_count"] == 10
    assert len(sec["areas"]) == _MAX_AREAS


# ── unknown 過多 → false-safe 防止 ────────────────────────────────────────────

def test_too_many_unknown_evaluated_false():
    samples = _make_samples(["unknown"] * 6 + ["normal"] * 5)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is False
    assert sec["summary"]["danger_detected"] is None


def test_too_many_unknown_reason():
    samples = _make_samples(["unknown"] * 6 + ["normal"] * 5)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["reason"] == "too_many_unknown_samples"


def test_too_many_unknown_not_false_safe():
    samples = _make_samples(["unknown"] * 6 + ["normal"] * 5)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["danger_detected"] is not False


def test_warning_with_many_unknowns_still_evaluated():
    """unknown >= 50% でも warning/danger があれば evaluated=True。"""
    samples = _make_samples(["unknown"] * 25 + ["warning"] + ["normal"] * 50)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert sec["summary"]["danger_detected"] is True


def test_danger_with_many_unknowns_still_evaluated():
    samples = _make_samples(["unknown"] * 40 + ["danger"] + ["normal"] * 35)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert sec["summary"]["danger_detected"] is True


# ── 空サンプル → offline ──────────────────────────────────────────────────────

def test_empty_samples_returns_offline():
    sec = build_kikikuru_section_from_samples([], _OBS_AT)
    assert sec["status"] == "offline"
    assert sec["evaluated"] is False
    assert sec["summary"]["danger_detected"] is None


# ── サンプル件数 ──────────────────────────────────────────────────────────────

def test_sample_count_correct():
    samples = _make_samples(["normal"] * 10)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["sample_count"] == 10


def test_unknown_count_correct():
    samples = _make_samples(["unknown", "unknown", "normal", "normal", "normal"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["unknown_count"] == 2


def test_sample_count_matches_total_points():
    n = len(LIVE_RAIN_SAMPLE_POINTS)
    samples = _make_samples(["normal"] * n)
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["sample_count"] == n
    assert n == 76


# ── offline セクション ────────────────────────────────────────────────────────

def test_offline_section_structure():
    from app.services.live_kikikuru_summary_service import _offline_kikikuru_section
    sec = _offline_kikikuru_section()
    assert sec["status"] == "offline"
    assert sec["evaluated"] is False
    assert sec["summary"]["danger_detected"] is None
    assert sec["summary"]["sample_count"] == len(LIVE_RAIN_SAMPLE_POINTS)
    assert sec["summary"]["unknown_count"] == len(LIVE_RAIN_SAMPLE_POINTS)


# ── 定数確認 ─────────────────────────────────────────────────────────────────

def test_cache_ttl_is_120s():
    assert _CACHE_TTL == 120.0


def test_max_workers_is_8():
    assert _MAX_WORKERS == 8


def test_total_timeout_is_reasonable():
    assert 24.0 < _TOTAL_SAMPLING_TIMEOUT <= 36.0


def test_max_areas_is_5():
    assert _MAX_AREAS == 5


# ── Phase 3-B: 複数 hazard 対応 ──────────────────────────────────────────────

def _make_multi_samples(
    land_levels: list[str],
    inund_levels: list[str],
    flood_levels: list[str],
) -> list[dict]:
    """3種別 × N地点のサンプルを生成する（同一地点に3エントリ）。"""
    pts = LIVE_RAIN_SAMPLE_POINTS[: len(land_levels)]
    result = []
    for pt, ll, il, fl in zip(pts, land_levels, inund_levels, flood_levels):
        result.append({**pt, "hazard": "land",       "level": ll, "source": "test"})
        result.append({**pt, "hazard": "inund",      "level": il, "source": "test"})
        result.append({**pt, "hazard": "flood_mesh", "level": fl, "source": "test"})
    return result


def test_kiki_elements_has_three_hazards():
    """Phase 3-B: land / inund / flood_mesh が対象に含まれる。"""
    assert "land"       in _KIKI_ELEMENTS
    assert "inund"      in _KIKI_ELEMENTS
    assert "flood_mesh" in _KIKI_ELEMENTS
    assert len(_KIKI_ELEMENTS) == 3


def test_inund_area_hazard_field():
    """inund 種別の area に hazard='inund' が付く。"""
    samples = _make_multi_samples(["normal"], ["warning"], ["normal"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert len(sec["areas"]) == 1
    assert sec["areas"][0]["hazard"] == "inund"
    assert sec["areas"][0]["level"] == "warning"


def test_flood_mesh_area_hazard_field():
    """flood_mesh 種別の area に hazard='flood_mesh' が付く。"""
    samples = _make_multi_samples(["normal"], ["normal"], ["danger"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["evaluated"] is True
    assert len(sec["areas"]) == 1
    assert sec["areas"][0]["hazard"] == "flood_mesh"
    assert sec["areas"][0]["level"] == "danger"


def test_multi_hazard_sample_count_is_point_count():
    """3 hazard × 76地点 = 228サンプルでも sample_count は地点数（76）。"""
    n = len(LIVE_RAIN_SAMPLE_POINTS)
    samples = _make_multi_samples(["normal"] * n, ["normal"] * n, ["normal"] * n)
    assert len(samples) == n * 3  # 228サンプル
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["sample_count"] == n  # 地点数 = 76


def test_multi_hazard_unknown_count_all_three():
    """地点の unknown 判定: 全3 hazard が unknown の場合のみカウント。"""
    # 3地点を一括生成:
    #   地点0(hokkaido): land=unknown / inund=unknown / flood=unknown → 全unknown
    #   地点1(aomori):   land=unknown / inund=normal  / flood=normal  → 部分 unknown → evaluated
    #   地点2(iwate):    land=normal  / inund=normal  / flood=normal  → 全normal
    samples = _make_multi_samples(
        land_levels=  ["unknown", "unknown", "normal"],
        inund_levels= ["unknown", "normal",  "normal"],
        flood_levels= ["unknown", "normal",  "normal"],
    )
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["sample_count"] == 3
    assert sec["summary"]["unknown_count"] == 1


def test_multi_hazard_one_point_contributes_multiple_areas():
    """1地点で複数 hazard が warning → 複数 areas に出る。"""
    # 地点0: land=danger, inund=warning, flood=normal → 2 areas
    samples = _make_multi_samples(["danger"], ["warning"], ["normal"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert len(sec["areas"]) == 2
    hazards = {a["hazard"] for a in sec["areas"]}
    assert "land"  in hazards
    assert "inund" in hazards


def test_multi_hazard_danger_detected_any_hazard():
    """いずれかの hazard が warning 以上なら danger_detected=True。"""
    # land=normal, inund=normal, flood=warning
    samples = _make_multi_samples(["normal"], ["normal"], ["warning"])
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert sec["summary"]["danger_detected"] is True


def test_multi_hazard_areas_max_5():
    """複数 hazard で areas が増えても 5件上限は守られる。"""
    n = 10
    samples = _make_multi_samples(
        ["danger"] * n + ["normal"] * (len(LIVE_RAIN_SAMPLE_POINTS) - n),
        ["warning"] * n + ["normal"] * (len(LIVE_RAIN_SAMPLE_POINTS) - n),
        ["warning"] * n + ["normal"] * (len(LIVE_RAIN_SAMPLE_POINTS) - n),
    )
    sec = build_kikikuru_section_from_samples(samples, _OBS_AT)
    assert len(sec["areas"]) <= _MAX_AREAS
