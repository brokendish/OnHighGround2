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
from app.services.live_rain_summary_service import build_live_rain_summary
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

    eq_section, tsunami_section, rain_section = await asyncio.gather(
        _build_earthquake_section(),
        _build_tsunami_section(),
        build_live_rain_summary(),
    )

    dangerous_areas = _merge_dangerous_areas(
        tsunami_section.get("areas", []),
        eq_section.get("areas", []),
        rain_section.get("areas", []),
    )

    overall = _overall_status(
        eq_section["status"], tsunami_section["status"], rain_section["status"]
    )

    return {
        "updated_at":      now,
        "status":          overall,
        "rain":            rain_section,
        "kikikuru":        _kikikuru_section_tile_only(),
        "earthquake":      eq_section,
        "tsunami":         tsunami_section,
        "dangerous_areas": dangerous_areas,
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
    eq_areas: List[Dict[str, Any]],
    rain_areas: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """津波・地震・雨雲の危険地域を danger → warning 順に統合する。"""
    _level_order = {"danger": 0, "warning": 1, "watch": 2, "normal": 3, "unknown": 4}
    # タイプ優先度: 津波 > 地震 > 雨雲
    _type_order  = {"tsunami": 0, "earthquake": 1, "rain": 2}

    combined = tsunami_areas + eq_areas + (rain_areas or [])
    combined.sort(key=lambda a: (
        _level_order.get(a.get("level", "unknown"), 4),
        _type_order.get(a.get("type", ""), 9),
    ))
    return combined


# ── 全体ステータス ────────────────────────────────────────────────────────────

def _overall_status(*statuses: str) -> str:
    if any(s == "offline" for s in statuses):
        return "degraded"
    if any(s == "stale" for s in statuses):
        return "stale"
    return "ok"
