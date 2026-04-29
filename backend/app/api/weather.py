"""
気象API — 現在地の最寄りアメダス観測点データを返す。
"""
import logging
from fastapi import APIRouter, Query, HTTPException

from services.weather_service import get_current_weather

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/weather/current")
async def get_weather_current(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
):
    """
    現在地の気象情報を返す。

    気象庁アメダス観測点から最寄りデータを取得し、雨量・風速・気温を返す。
    欠損フィールドは null。応答は最大 60 秒キャッシュされる。

    追加フィールド（Phase1.5）:
      distance_km     — ユーザー座標から観測点までの距離（km）
      station_quality — near / medium / far
      age_minutes     — 観測時刻からの経過分（null = 不明）
      freshness       — fresh / stale / unknown
    """
    try:
        data = get_current_weather(lat, lon)
        if data is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "weather_unavailable", "message": "気象データを取得できませんでした"},
            )
        return {
            "station":         data["station"],
            "station_id":      data["station_id"],
            "station_lat":     data["station_lat"],
            "station_lon":     data["station_lon"],
            "rain":            data["rain"],
            "wind":            data["wind"],
            "temperature":     data["temperature"],
            "observed_at":     data["observed_at"],
            "distance_km":     data["distance_km"],
            "station_quality": data["station_quality"],
            "age_minutes":     data["age_minutes"],
            "freshness":       data["freshness"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("weather endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"})
