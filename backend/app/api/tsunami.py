"""
tsunami.py — 津波警報・注意報 REST API

GET /api/tsunami/warnings/current
GET /api/tsunami/warnings/current?lat=...&lon=...
GET /api/tsunami/warnings/current?mock=major_warning|warning|advisory|none|stale|error
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.services.tsunami_warning_service import get_tsunami_warnings

router = APIRouter(prefix="/api/tsunami", tags=["tsunami"])
logger = logging.getLogger(__name__)

_JST = timezone(timedelta(hours=9))

_MOCK_AREAS: Dict[str, List[Dict[str, Any]]] = {
    "major_warning": [
        {
            "code": None, "name": "東京湾内湾", "level": "major_warning",
            "level_label": "大津波警報", "expected_height": "3m以上",
            "arrival_time": None, "is_target": True,
        },
        {
            "code": None, "name": "相模湾・三浦半島", "level": "major_warning",
            "level_label": "大津波警報", "expected_height": "10m以上",
            "arrival_time": None, "is_target": False,
        },
    ],
    "warning": [
        {
            "code": None, "name": "東京湾内湾", "level": "warning",
            "level_label": "津波警報", "expected_height": "1m",
            "arrival_time": None, "is_target": True,
        },
    ],
    "advisory": [
        {
            "code": None, "name": "東京湾内湾", "level": "advisory",
            "level_label": "津波注意報", "expected_height": "0.3m未満",
            "arrival_time": None, "is_target": True,
        },
    ],
}

_MOCK_MESSAGES: Dict[str, str] = {
    "major_warning": "大津波警報が発表されています。直ちに高台へ避難してください。",
    "warning":       "津波警報が発表されています。海岸・河口付近から離れてください。",
    "advisory":      "津波注意報が発表されています。海岸・河口付近から離れてください。",
    "none":          "",
}


def _mock_response(level: str) -> Dict[str, Any]:
    now = datetime.now(_JST).isoformat()
    if level == "error":
        return {
            "source": "mock", "status": "error",
            "observed_at": None, "updated_at": now,
            "ttl_seconds": 60, "areas": [], "message": "",
            "error": "mock tsunami warning fetch error",
        }
    if level == "none":
        return {
            "source": "mock", "status": "none",
            "observed_at": None, "updated_at": now,
            "ttl_seconds": 60, "areas": [], "message": "",
        }
    if level == "stale":
        stale_at = (datetime.now(_JST) - timedelta(hours=2)).isoformat()
        return {
            "source": "mock",
            "status": "stale",
            "observed_at": stale_at,
            "updated_at": now,
            "ttl_seconds": 60,
            "areas": _MOCK_AREAS["warning"],
            "message": "津波警報情報が古い可能性があります。最新情報を確認してください。",
        }
    areas = _MOCK_AREAS.get(level, _MOCK_AREAS["advisory"])
    return {
        "source":      "mock",
        "status":      "active",
        "observed_at": now,
        "updated_at":  now,
        "ttl_seconds": 60,
        "areas":       areas,
        "message":     _MOCK_MESSAGES.get(level, ""),
    }


@router.get("/warnings/current")
async def get_current_warnings(
    lat:  Optional[float] = Query(default=None),
    lon:  Optional[float] = Query(default=None),
    mock: Optional[str]   = Query(default=None),
) -> Dict[str, Any]:
    """現在の津波警報・注意報情報を返す。"""
    if mock is not None:
        return _mock_response(mock)
    return await get_tsunami_warnings(lat=lat, lon=lon)
