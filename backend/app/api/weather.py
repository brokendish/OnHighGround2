"""
気象API — 現在地の最寄りアメダス観測点データ / 雨量レーダータイルを返す。
"""
import logging
from fastapi import APIRouter, Query, HTTPException

from services.weather_service import get_current_weather
from services.jma_rain_tile_service import get_rain_tile_latest, get_rain_tile_times

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
      station_desc    — 観測点名と提供データ種別の説明
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
            "station_desc":    data["station_desc"],
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
            "confidence":      data["confidence"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("weather endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"})


@router.get("/api/weather/rain/tile/latest")
async def get_rain_tile_latest_endpoint():
    """
    JMA 降水ナウキャストの最新タイル情報を返す（Phase2B）。

    気象庁の降水ナウキャスト targetTimes から最新の basetime/validtime を取得し、
    Leaflet 用タイル URL テンプレートを返す。応答は 120 秒キャッシュされる。
    """
    try:
        data = get_rain_tile_latest()
        if data is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "rain_tile_unavailable", "message": "雨量タイル情報を取得できませんでした"},
            )
        return {
            "source":            data["source"],
            "basetime":          data["basetime"],
            "validtime":         data["validtime"],
            "tile_url_template": data["tile_url_template"],
            "updated_at":        data["updated_at"],
            "ttl_seconds":       data["ttl_seconds"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("rain tile endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"})


@router.get("/api/weather/rain/tile/times")
async def get_rain_tile_times_endpoint():
    """
    JMA 降水ナウキャストの最新 basetime に対する全 validtime 一覧を返す。

    スライダー・アニメーション用。各エントリに offset_minutes（basetime からの分差）を付与する。
    """
    try:
        data = get_rain_tile_times()
        if data is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "rain_tile_times_unavailable", "message": "雨量タイル時刻一覧を取得できませんでした"},
            )
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("rain tile times endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"})
