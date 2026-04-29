"""
気象API — 現在地の最寄りアメダス観測点データ / 警報・注意報を返す。
"""
import logging
from fastapi import APIRouter, Query, HTTPException

from services.weather_service import get_current_weather
from services.weather_warning_service import get_current_warnings

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


@router.get("/api/weather/warnings/current")
async def get_weather_warnings_current(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
):
    """
    現在地の警報・注意報情報を返す（Phase2A）。

    気象庁の警報 JSON から lat/lon に対応する予報区の情報を取得する。
    警報がない場合は warnings=[] / highest_level="なし" で正常 200 を返す。
    データ取得失敗時は 503 を返す。
    """
    try:
        data = get_current_warnings(lat, lon)
        if data is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "warning_unavailable", "message": "警報データを取得できませんでした"},
            )
        return {
            "area_name":     data["area_name"],
            "office_name":   data["office_name"],
            "office_code":   data["office_code"],
            "class10_code":  data["class10_code"],
            "warnings":      data["warnings"],
            "highest_level": data["highest_level"],
            "updated_at":    data["updated_at"],
            "match_type":    data["match_type"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("weather warnings endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"})
