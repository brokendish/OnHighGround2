"""
jma_warning_service.py — 警報・注意報専用サービス（/api/weather/warnings 向け）

既存の weather_alert_service / jma_weather_adapter を再利用し、
指示書が定める ok/items/max_level/has_warning フォーマットに変換して返す。

レスポンス仕様:
  ok=True 時:
    {ok, source, area_name, updated_at, has_warning, max_level, items}
    items: [{name, level, status}]
    max_level: "emergency" | "warning" | "advisory" | "none"
  ok=False 時:
    {ok, source, reason, items: []}
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.weather_alert_service import get_alerts_for_location

logger = logging.getLogger(__name__)

_SEVERITY_TO_LEVEL = {
    "emergency": "emergency",
    "warning":   "warning",
    "advisory":  "advisory",
    "unknown":   "advisory",
    "none":      "none",
}


def get_warnings_for_location(lat: float, lon: float) -> dict:
    """
    現在地の警報・注意報を ok/items 形式で返す。

    Returns:
        ok=True:
            {ok, source, area_name, updated_at, has_warning, max_level, items}
        ok=False:
            {ok, source, reason, items}
    """
    try:
        raw = get_alerts_for_location(lat, lon)
    except Exception as exc:
        logger.warning("jma_warning_service: get_alerts_for_location failed: %s", exc)
        return {
            "ok":     False,
            "source": "jma",
            "reason": "failed_to_fetch_warning_data",
            "items":  [],
        }

    status   = raw.get("status", "unavailable")
    severity = raw.get("severity", "none")
    alerts   = raw.get("alerts", [])
    location = raw.get("location", {})

    if status == "unavailable":
        return {
            "ok":     False,
            "source": "jma",
            "reason": "failed_to_fetch_warning_data",
            "items":  [],
        }

    # area_name: city があればそれを優先（市区町村レベル）、なければ pref 名
    area_name: Optional[str] = (
        location.get("city")
        or location.get("area_name")
        or None
    )

    items = [
        {
            "name":   a.get("kind", ""),
            "level":  a.get("level", "不明"),
            "status": a.get("status", ""),
        }
        for a in alerts
        if a.get("kind")
    ]

    max_level = _SEVERITY_TO_LEVEL.get(severity, "none")
    has_warning = severity in ("emergency", "warning")

    return {
        "ok":          True,
        "source":      "jma",
        "area_name":   area_name,
        "updated_at":  raw.get("updated_at"),
        "has_warning": has_warning,
        "max_level":   max_level,
        "items":       items,
    }
