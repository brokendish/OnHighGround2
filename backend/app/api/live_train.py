"""
live_train.py — 鉄道運行影響レイヤー REST API

GET /api/live/trains/summary
  クエリ: lat, lng, prefecture
  - lat/lng: 現在地周辺モード（都道府県へ変換）
  - prefecture: 都道府県名（例: "東京都"）。優先。
  - 両方なし: 全国の障害路線を返す

  取得失敗時も HTTP 200 を返し、status: "unavailable"
  API自体の異常時のみ 5xx
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from app.services.live_train_service import build_train_summary
from app.services.live_train_osm_service import get_osm_railways

router = APIRouter(prefix="/api/live", tags=["live"])


@router.get("/trains/summary")
async def get_train_summary(
    lat:        Optional[float] = None,
    lng:        Optional[float] = None,
    prefecture: Optional[str]   = None,
) -> Dict[str, Any]:
    """
    鉄道運行影響サマリーを返す。

    - 取得失敗時は HTTP 200 で status="unavailable"
    - stale cache 使用時は stale=true を付与
    """
    return await build_train_summary(lat=lat, lng=lng, prefecture=prefecture)


@router.get("/trains/osm")
async def get_train_osm(
    south: float = Query(..., ge=-90, le=90),
    west:  float = Query(..., ge=-180, le=180),
    north: float = Query(..., ge=-90, le=90),
    east:  float = Query(..., ge=-180, le=180),
) -> Dict[str, Any]:
    """表示範囲内の鉄道路線を Overpass 互換 JSON で返す。"""
    return get_osm_railways(south=south, west=west, north=north, east=east)
