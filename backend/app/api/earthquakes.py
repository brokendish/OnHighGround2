"""
earthquakes.py — 地震情報 REST API

GET /api/earthquakes?days=1
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from app.services.earthquake_service import get_recent_earthquakes
from app.services.config_definition_service import get_config_definition_service
from app.services.config_state_service import get_config_state_service

router = APIRouter(prefix="/api/earthquakes", tags=["earthquakes"])
logger = logging.getLogger(__name__)


def _get_display_days() -> int:
    """Config から earthquake.display_days を取得する（デフォルト 1）。"""
    try:
        defn = get_config_definition_service().get("earthquake.display_days")
        if defn is None:
            return 1
        items = get_config_state_service().list_items([defn])
        if items:
            return int(items[0].current_value)
    except Exception as exc:
        logger.debug("earthquake.display_days 取得失敗: %s", exc)
    return 1


def _coerce_days(days: Optional[str]) -> int:
    if days is None:
        return _get_display_days()
    try:
        return int(days)
    except (TypeError, ValueError):
        logger.debug("invalid days parameter: %r", days)
        return _get_display_days()


@router.get("")
async def get_earthquakes(
    days: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """
    地震情報を返す。

    - days: 取得日数 (1–30)。省略時は Config の earthquake.display_days を使用。
    """
    effective_days = _coerce_days(days)
    items = await get_recent_earthquakes(effective_days)
    logger.info("earthquakes: days=%d count=%d", effective_days, len(items))
    return {"count": len(items), "items": items}
