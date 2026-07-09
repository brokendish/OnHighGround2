"""
live_weather_jma.py — 全国気象ミニテロップ（Open-Meteo Forecast）REST API

GET /api/live/weather/jma/prefectures
  都道府県代表地点（北海道は複数地点）の気象概況を返す。
  取得失敗時も HTTP 200 を返し、cache_status: "stale" | "unavailable" とする。

  Phase 8-A.1: backend は Open-Meteo `/v1/forecast` を利用する（`/v1/jma` は
  precipitation_probability が常に null のため不採用）。エンドポイントパス自体は
  互換性のため変更していない。
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app.services.live_weather_jma_service import get_weather_summary

router = APIRouter(prefix="/api/live", tags=["live"])


@router.get("/weather/jma/prefectures")
async def get_weather_jma_prefectures() -> Dict[str, Any]:
    """全国気象ミニテロップ用サマリーを返す。"""
    return await get_weather_summary()
