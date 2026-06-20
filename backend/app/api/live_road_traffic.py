"""
live_road_traffic.py — 道路交通影響レイヤー REST API

GET /api/live/road-traffic/summary
  クエリ: lat, lng, prefecture, bbox
  - bbox:       "min_lng,min_lat,max_lng,max_lat"（最優先）
  - prefecture: 都道府県名（例: "東京都"）
  - lat/lng:    現在地周辺モード
  - なし:       全国観測地点を返す

  取得失敗時も HTTP 200 を返し、status: "unavailable"
  API自体の異常時のみ 5xx
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Query

from app.services.live_road_traffic_service import build_road_traffic_summary

router = APIRouter(prefix="/api/live", tags=["live"])


@router.get("/road-traffic/summary")
async def get_road_traffic_summary(
    lat:        Optional[float] = None,
    lng:        Optional[float] = None,
    prefecture: Optional[str]   = None,
    bbox:       Annotated[Optional[str], Query(description="min_lng,min_lat,max_lng,max_lat")] = None,
) -> Dict[str, Any]:
    """
    道路交通影響サマリーを返す。

    - 取得失敗時は HTTP 200 で status="unavailable"
    - stale cache 使用時は stale=true を付与
    - bbox > prefecture > lat/lng の優先順でフィルター
    """
    return await build_road_traffic_summary(
        lat=lat,
        lng=lng,
        prefecture=prefecture,
        bbox=bbox,
    )
