"""
live_summary_service.py — /live サマリー集計サービス

各カテゴリに evaluated フラグを持ち、
タイル表示のみのソース（rain / kikikuru）は evaluated=False として
危険なし/あり の断定を防ぐ。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.services.earthquake_service import get_recent_earthquakes
from app.services.live_kikikuru_summary_service import build_live_kikikuru_summary
from app.services.live_rain_summary_service import build_live_rain_summary
from app.services.live_storm_surge_service import build_live_storm_surge_summary
from app.services.tsunami_warning_service import get_tsunami_warnings

_JST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)

_TSUNAMI_ACTIVE_LEVELS = frozenset({"major_warning", "warning", "advisory"})

_TSUNAMI_LEVEL_MAP: Dict[str, str] = {
    "major_warning": "danger",
    "warning":       "danger",
    "advisory":      "warning",
}

_VALID_STATUSES = frozenset({"ok", "offline", "stale", "unknown"})


async def build_live_summary() -> Dict[str, Any]:
    """全ソースを集約して /api/live/summary レスポンスを返す。"""
    now = datetime.now(_JST).isoformat()

    (
        eq_section,
        tsunami_section,
        storm_surge_section,
        rain_section,
        kikikuru_section,
    ) = await asyncio.gather(
        _build_earthquake_section(),
        _build_tsunami_section(),
        build_live_storm_surge_summary(),
        build_live_rain_summary(),
        build_live_kikikuru_summary(),
    )

    dangerous_areas = _merge_dangerous_areas(
        tsunami_section.get("areas", []),
        storm_surge_section.get("areas", []),
        eq_section.get("areas", []),
        kikikuru_section.get("areas", []),
        rain_section.get("areas", []),
    )

    overall = _overall_status(
        eq_section["status"], tsunami_section["status"],
        storm_surge_section["status"],
        rain_section["status"], kikikuru_section["status"],
    )

    # Phase 3-C / 4-C: サマリー観察ログ
    rain_area_count       = len(rain_section.get("areas", []))
    kikikuru_area_count   = len(kikikuru_section.get("areas", []))
    storm_surge_area_count = len(storm_surge_section.get("areas", []))
    dangerous_area_count  = len(dangerous_areas)
    top_area  = dangerous_areas[0].get("label", "none") if dangerous_areas else "none"
    top_level = dangerous_areas[0].get("level", "none") if dangerous_areas else "none"
    logger.info(
        "live summary observation: rain_areas=%d kikikuru_areas=%d"
        " storm_surge_areas=%d dangerous_areas=%d top_area=%s top_level=%s",
        rain_area_count, kikikuru_area_count,
        storm_surge_area_count, dangerous_area_count, top_area, top_level,
    )

    return {
        "updated_at":      now,
        "status":          overall,
        "rain":            rain_section,
        "kikikuru":        kikikuru_section,
        "earthquake":      eq_section,
        "tsunami":         tsunami_section,
        "storm_surge":     storm_surge_section,
        "dangerous_areas": dangerous_areas,
        "observation": {
            "rain_area_count":        rain_area_count,
            "kikikuru_area_count":    kikikuru_area_count,
            "storm_surge_area_count": storm_surge_area_count,
            "dangerous_area_count":   dangerous_area_count,
            "max_areas":              5,
        },
    }


# ── 地震セクション ───────────────────────────────────────────────────────────

async def _build_earthquake_section() -> Dict[str, Any]:
    try:
        items: List[Dict[str, Any]] = await get_recent_earthquakes(days=1)
        count_24h = len(items)
        m5_count  = sum(1 for e in items if (e.get("magnitude") or 0) >= 5.0)
        m6_count  = sum(1 for e in items if (e.get("magnitude") or 0) >= 6.0)
        return {
            "status":    "ok",
            "evaluated": True,
            "summary": {
                "count_24h": count_24h,
                "m5_count":  m5_count,
                "m6_count":  m6_count,
            },
            "areas": _build_eq_areas(items),
        }
    except Exception as exc:
        logger.warning("live_summary: earthquake 取得失敗: %s", exc)
        return {
            "status":    "offline",
            "evaluated": False,
            "summary":   {"count_24h": None, "m5_count": None, "m6_count": None},
            "areas":     [],
        }


def _build_eq_areas(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for i, eq in enumerate(items):
        mag = eq.get("magnitude") or 0
        if mag < 5.0:
            continue
        result.append({
            "id":    f"eq-{i}",
            "label": eq.get("epicenter_name") or "震源不明",
            "level": "danger" if mag >= 6.0 else "warning",
            "type":  "earthquake",
            "source": "jma",
            "lat":   eq.get("lat"),
            "lng":   eq.get("lng"),
        })
    return result[:3]


# ── 津波セクション ───────────────────────────────────────────────────────────

async def _build_tsunami_section() -> Dict[str, Any]:
    try:
        data: Dict[str, Any] = await get_tsunami_warnings()
        raw_areas = data.get("areas") or []
        active    = any(a.get("level") in _TSUNAMI_ACTIVE_LEVELS for a in raw_areas)
        w_count   = sum(1 for a in raw_areas if a.get("level") in _TSUNAMI_ACTIVE_LEVELS)
        raw_status = data.get("status")
        if raw_status == "stale":
            status = "stale"
        elif raw_status in (None, "error"):
            status = "offline"
        else:
            status = "ok"
        return {
            "status":    status,
            "evaluated": True,
            "summary":   {"active": active, "warning_area_count": w_count},
            "areas":     _build_tsunami_areas(raw_areas),
        }
    except Exception as exc:
        logger.warning("live_summary: tsunami 取得失敗: %s", exc)
        return {
            "status":    "offline",
            "evaluated": False,
            "summary":   {"active": None, "warning_area_count": None},
            "areas":     [],
        }


def _build_tsunami_areas(raw_areas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for i, area in enumerate(raw_areas):
        level_str = area.get("level") or ""
        if level_str not in _TSUNAMI_ACTIVE_LEVELS:
            continue
        result.append({
            "id":    f"tsunami-{i}",
            "label": area.get("name") or "不明",
            "level": _TSUNAMI_LEVEL_MAP.get(level_str, "warning"),
            "type":  "tsunami",
            "source": "jma",
            "lat":   area.get("lat"),
            "lng":   area.get("lng"),
        })
    return result


# ── タイル専用セクション（evaluated=False 固定）───────────────────────────────

def _rain_section_tile_only() -> Dict[str, Any]:
    """雨雲はタイル表示のみ。strong_rain_detected は null（未判定）で返す。"""
    return {
        "status":    "ok",
        "evaluated": False,
        "reason":    "tile_only",
        "summary": {
            "strong_rain_detected": None,
            "warning_area_count":   None,
            "danger_area_count":    None,
        },
        "areas": [],
    }


def _kikikuru_section_tile_only() -> Dict[str, Any]:
    """キキクルはタイル表示のみ。danger_detected は null（未判定）で返す。"""
    return {
        "status":    "ok",
        "evaluated": False,
        "reason":    "tile_only",
        "summary": {
            "danger_detected":    None,
            "warning_area_count": None,
            "danger_area_count":  None,
        },
        "areas": [],
    }


# ── 危険地域統合 ──────────────────────────────────────────────────────────────

def _merge_dangerous_areas(
    tsunami_areas: List[Dict[str, Any]],
    storm_surge_areas: List[Dict[str, Any]] | None = None,
    eq_areas: List[Dict[str, Any]] | None = None,
    kikikuru_areas: List[Dict[str, Any]] | None = None,
    rain_areas: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """津波・高潮・地震・キキクル・雨雲の危険地域を danger → warning 順に統合する。"""
    _level_order = {"danger": 0, "warning": 1, "watch": 2, "normal": 3, "unknown": 4}
    # タイプ優先度: 津波 > 高潮 > 地震 > キキクル > 雨雲
    _type_order  = {"tsunami": 0, "storm_surge": 1, "earthquake": 2, "kikikuru": 3, "rain": 4}

    combined = (
        tsunami_areas
        + (storm_surge_areas or [])
        + (eq_areas or [])
        + (kikikuru_areas or [])
        + (rain_areas or [])
    )
    combined.sort(key=lambda a: (
        _level_order.get(a.get("level", "unknown"), 4),
        _type_order.get(a.get("type", ""), 9),
    ))

    # Phase 3-C: 同一地域が複数種別で出た場合に観察ログ（統合はしない）
    label_types: Dict[str, List[str]] = {}
    for area in combined:
        label = area.get("label", "")
        if label:
            label_types.setdefault(label, []).append(area.get("type", ""))
    for label, types in label_types.items():
        if len(types) > 1:
            logger.info(
                "live duplicate area observation: label=%s types=%s",
                label, ",".join(types),
            )

    return combined


# ── 全体ステータス ────────────────────────────────────────────────────────────

def _overall_status(*statuses: str) -> str:
    if any(s == "offline" for s in statuses):
        return "degraded"
    if any(s == "stale" for s in statuses):
        return "stale"
    return "ok"
