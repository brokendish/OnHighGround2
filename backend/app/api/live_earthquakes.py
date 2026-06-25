"""
live_earthquakes.py — /live 地震履歴 API

GET /api/live/earthquakes/history?days=3
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Query

from app.services.earthquake_service import get_recent_earthquakes

router = APIRouter(prefix="/api/live/earthquakes", tags=["live-earthquakes"])
logger = logging.getLogger(__name__)


@router.get("/history")
async def get_earthquake_history(
    days: int = Query(default=3, ge=1, le=7),
) -> Dict[str, Any]:
    """
    過去 N 日間の地震情報を返す（/live 地震履歴表示用）。
    デフォルト 3 日間。最大 7 日間。
    """
    items = await get_recent_earthquakes(days=days)
    now = datetime.now(timezone.utc)
    logger.info("live/earthquakes/history: days=%d count=%d", days, len(items))
    return {
        "days": days,
        "updated_at": now.isoformat(),
        "count": len(items),
        "items": items,
    }
