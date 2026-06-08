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
        "dangerous_areas":             dangerous_areas,
        "integrated_dangerous_regions": _build_integrated_regions(dangerous_areas),
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
        elif raw_status == "none":
            # 警報なし / 解除済み
            status = "cleared"
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


# ── 統合危険地域ランキング（Phase 5-A）────────────────────────────────────────

_TYPE_PRIORITY: Dict[str, int] = {
    "tsunami": 0, "storm_surge": 1, "earthquake": 2, "kikikuru": 3, "rain": 4,
}
_LEVEL_ORDER_INT: Dict[str, int] = {
    "danger": 0, "warning": 1, "watch": 2, "normal": 3, "unknown": 4,
}
_MAX_REGIONS = 10


def _event_label(area: Dict[str, Any]) -> str:
    """dangerous_areas の 1エントリからイベント表示ラベルを生成する。"""
    type_ = area.get("type", "")
    if type_ == "tsunami":
        # dangerous_areas の level は "danger"/"warning" に正規化済み
        return "津波警報" if area.get("level") == "danger" else "津波注意報"
    if type_ == "storm_surge":
        return area.get("detail") or "高潮警報"
    if type_ == "earthquake":
        return "地震"
    if type_ == "kikikuru":
        hazard = area.get("hazard", "")
        _HAZARD_LABEL = {"land": "土砂", "inund": "浸水", "flood_mesh": "洪水"}
        h = _HAZARD_LABEL.get(hazard, hazard)
        return f"キキクル（{h}）" if h else "キキクル"
    if type_ == "rain":
        return "雨雲"
    return area.get("label") or type_


def _build_integrated_regions(dangerous_areas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    dangerous_areas を label キーで地域単位に統合し、
    危険度・タイプ優先度でソートして最大 _MAX_REGIONS 件を返す。

    既存の dangerous_areas 契約は破壊しない（追加フィールドとして提供）。
    """
    groups: Dict[str, Dict[str, Any]] = {}

    for area in dangerous_areas:
        label = area.get("label") or ""
        if not label:
            continue

        event_type  = area.get("type", "")
        area_level  = area.get("level", "unknown")
        type_prio   = _TYPE_PRIORITY.get(event_type, 9)
        level_order = _LEVEL_ORDER_INT.get(area_level, 4)

        if label not in groups:
            groups[label] = {
                "label":          label,
                "level":          area_level,
                "lat":            area.get("lat"),
                "lng":            area.get("lng"),
                "events":         [],
                "_seen_keys":     set(),
                "_level_order":   level_order,
                "_type_priority": type_prio,
            }

        g = groups[label]

        # 代表 level: より重い方へ更新
        if level_order < g["_level_order"]:
            g["level"]        = area_level
            g["_level_order"] = level_order

        # 代表座標: 最初の non-None を使用
        if g["lat"] is None and area.get("lat") is not None:
            g["lat"] = area["lat"]
        if g["lng"] is None and area.get("lng") is not None:
            g["lng"] = area["lng"]

        # 代表タイプ優先度: より高い方へ更新
        if type_prio < g["_type_priority"]:
            g["_type_priority"] = type_prio

        # イベント重複除去キー: (type, hazard)
        dedup_key = (event_type, area.get("hazard") or "")
        if dedup_key not in g["_seen_keys"]:
            g["_seen_keys"].add(dedup_key)
            g["events"].append({
                "type":  event_type,
                "label": _event_label(area),
                "level": area_level,
            })

    # ソート: danger 優先 → タイプ優先度
    sorted_groups = sorted(
        groups.values(),
        key=lambda r: (r["_level_order"], r["_type_priority"]),
    )

    # ログ
    logger.info(
        "live integrated danger regions: input_areas=%d regions=%d",
        len(dangerous_areas), min(len(sorted_groups), _MAX_REGIONS),
    )
    for g in sorted_groups[:_MAX_REGIONS]:
        if len(g["events"]) > 1:
            logger.info(
                "live integrated region: label=%s types=%s",
                g["label"], ",".join(e["type"] for e in g["events"]),
            )

    # 出力: 内部管理フィールドを除去し最大件数に絞る
    result = []
    _TYPE_ORDER = ["tsunami", "storm_surge", "earthquake", "kikikuru", "rain"]
    for g in sorted_groups[:_MAX_REGIONS]:
        seen = set()
        types = [
            t for t in _TYPE_ORDER
            if t in {e["type"] for e in g["events"]} and not seen.add(t)  # type: ignore[func-returns-value]
        ]
        result.append({
            "label":  g["label"],
            "level":  g["level"],
            "lat":    g["lat"],
            "lng":    g["lng"],
            "types":  types,
            "events": g["events"],
        })

    return result


# ── 全体ステータス ────────────────────────────────────────────────────────────

def _overall_status(*statuses: str) -> str:
    if any(s == "offline" for s in statuses):
        return "degraded"
    if any(s == "stale" for s in statuses):
        return "stale"
    return "ok"
