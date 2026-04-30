"""
earthquakes_recent.py — JMA地震情報 REST API (Phase2C)

GET /api/earthquakes/recent
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Query

from services.jma_quake_client import fetch_recent_earthquakes

router = APIRouter(prefix="/api/earthquakes", tags=["earthquakes"])
logger = logging.getLogger(__name__)


def _add_compat_fields(event: Dict[str, Any]) -> Dict[str, Any]:
    """Phase2C フィールドに加え、既存UIが参照するフィールドを補完する。"""
    e = dict(event)
    # occurred_at: origin_time を優先、なければ report_time
    e.setdefault("occurred_at", e.get("origin_time") or e.get("report_time"))
    # epicenter_name: hypocenter_name のエイリアス
    e.setdefault("epicenter_name", e.get("hypocenter_name") or "不明")
    # lng: lon のエイリアス（既存UIは lng を参照）
    if e.get("lng") is None:
        e["lng"] = e.get("lon")
    # tsunami_info: domestic_tsunami のエイリアス
    e.setdefault("tsunami_info", e.get("domestic_tsunami") or "不明")
    return e


@router.get("/recent")
async def get_earthquakes_recent(
    limit: int = Query(default=10, ge=1, le=30),
) -> Dict[str, Any]:
    """
    気象庁地震情報を返す（Phase2C）。

    Phase2C 指定フィールド + 既存UI互換フィールドを含む events[] を返す。
    - source: "jma"
    - updated_at: ISO 8601 UTC
    - events[]: event_id / title / report_time / origin_time / hypocenter_name /
                lat / lon / depth_km / magnitude / max_intensity /
                domestic_tsunami / headline / intensity_areas +
                互換: occurred_at / epicenter_name / lng / tsunami_info
    """
    events_raw = await fetch_recent_earthquakes(limit=limit)
    events = [_add_compat_fields(e) for e in events_raw]
    updated_at = datetime.now(timezone.utc).isoformat()
    logger.info(
        "earthquakes/recent: limit=%d count=%d updated_at=%s",
        limit, len(events), updated_at,
    )
    return {
        "source": "jma",
        "updated_at": updated_at,
        "events": events,
    }
