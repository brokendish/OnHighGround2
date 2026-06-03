"""
live_storm_surge.py — /live 高潮警報・注意報 REST API

GET /api/live/storm_surge/warnings
GET /api/live/storm_surge/warnings?mock=warning|advisory|none|error
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from app.services.live_storm_surge_service import build_live_storm_surge_summary

router = APIRouter(prefix="/api/live", tags=["live"])

_JST = timezone(timedelta(hours=9))

_MOCK_AREAS: Dict[str, list] = {
    "warning": [
        {
            "id":             "storm_surge-0",
            "label":          "東京都",
            "detail":         "高潮警報",
            "level":          "danger",
            "type":           "storm_surge",
            "source":         "mock",
            "lat":            35.6762,
            "lng":            139.6503,
            "pref_code":      "130000",
            "affected_areas": [
                {"area_name": "江東区", "area_code": "1314200", "kind": "高潮警報", "level": "warning"},
                {"area_name": "江戸川区", "area_code": "1312300", "kind": "高潮警報", "level": "warning"},
            ],
        },
        {
            "id":             "storm_surge-1",
            "label":          "神奈川県",
            "detail":         "高潮注意報",
            "level":          "warning",
            "type":           "storm_surge",
            "source":         "mock",
            "lat":            35.4478,
            "lng":            139.6425,
            "pref_code":      "140000",
            "affected_areas": [
                {"area_name": "横浜市", "area_code": "1410000", "kind": "高潮注意報", "level": "advisory"},
            ],
        },
    ],
    "advisory": [
        {
            "id":             "storm_surge-0",
            "label":          "大阪府",
            "detail":         "高潮注意報",
            "level":          "warning",
            "type":           "storm_surge",
            "source":         "mock",
            "lat":            34.6937,
            "lng":            135.5023,
            "pref_code":      "270000",
            "affected_areas": [
                {"area_name": "大阪市", "area_code": "2710000", "kind": "高潮注意報", "level": "advisory"},
            ],
        },
    ],
}


def _mock_response(level: str) -> Dict[str, Any]:
    now = datetime.now(_JST).isoformat()
    if level == "error":
        return {
            "status": "offline",
            "evaluated": False,
            "summary": {"active": None, "warning_area_count": None},
            "areas": [],
            "updated_at": now,
        }
    if level == "none":
        return {
            "status": "ok",
            "evaluated": True,
            "summary": {"active": False, "warning_area_count": 0},
            "areas": [],
            "updated_at": now,
        }
    areas = _MOCK_AREAS.get(level, _MOCK_AREAS["advisory"])
    w_count = sum(1 for a in areas if a["level"] == "danger")
    return {
        "status": "ok",
        "evaluated": True,
        "summary": {"active": True, "warning_area_count": w_count},
        "areas": areas,
        "updated_at": now,
    }


@router.get("/storm_surge/warnings")
async def get_storm_surge_warnings(
    mock: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """現在の高潮警報・注意報情報を返す。"""
    if mock is not None:
        return _mock_response(mock)
    result = await build_live_storm_surge_summary()
    result["updated_at"] = datetime.now(_JST).isoformat()
    return result
