"""
earthquake_service.py — 地震情報サービス
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.services.earthquake_source_p2p import fetch_earthquakes

logger = logging.getLogger(__name__)


async def get_recent_earthquakes(days: int = 1) -> List[Dict[str, Any]]:
    """指定日数以内の地震情報を新しい順で返す。"""
    days = max(1, min(days, 30))
    all_quakes = await fetch_earthquakes()
    if not all_quakes:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = []
    for q in all_quakes:
        occurred_at = q.get("occurred_at")
        if not occurred_at:
            continue
        try:
            dt = datetime.fromisoformat(occurred_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                result.append(q)
        except ValueError:
            logger.debug("Invalid occurred_at: %s", occurred_at)

    result.sort(key=lambda x: x.get("occurred_at", ""), reverse=True)
    return result
