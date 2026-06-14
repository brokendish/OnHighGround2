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

from fastapi import APIRouter

from app.services.live_train_service import build_train_summary

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
