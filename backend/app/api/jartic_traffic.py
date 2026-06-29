"""
jartic_traffic.py — JARTIC 交通量観測点 REST API

GET /api/jartic/traffic
  クエリ: bbox
  - bbox: "min_lng,min_lat,max_lng,max_lat"（省略時は全件）

  取得失敗時も HTTP 200 を返し、status: "unavailable"
  API自体の異常時のみ 5xx
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Query

from app.services.jartic_traffic_service import get_traffic_observations

router = APIRouter(prefix="/api/jartic", tags=["jartic"])


@router.get("/traffic")
async def get_jartic_traffic(
    bbox: Annotated[Optional[str], Query(description="min_lng,min_lat,max_lng,max_lat")] = None,
) -> Dict[str, Any]:
    """
    JARTIC 交通量観測点の最新スナップショットを返す。

    - APIキー不要（取得失敗時のみ status="unavailable"）
    - bbox 指定時はその範囲内の観測点のみ返す
    """
    return await get_traffic_observations(bbox=bbox)
