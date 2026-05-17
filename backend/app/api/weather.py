"""
気象API — アメダス観測点データ / 雨量レーダータイル / 警報・注意報 / 降水予測 / 複合リスク
"""
import logging
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, model_validator

from services.weather_service import get_current_weather
from services.jma_rain_tile_service import get_rain_tile_latest, get_rain_tile_times
from app.services.weather_alert_service import (
    get_alerts_for_location,
    get_precipitation_summary,
)
from app.services.weather_risk_context_service import get_risk_context
from app.services.weather_route_risk_service import get_route_risk


class _RouteCoords(BaseModel):
    coordinates: list[list[float]]


class _RouteRiskRequest(BaseModel):
    """route.coordinates 形式と top-level coordinates 形式の両方を受け付ける。"""
    route: Optional[_RouteCoords] = None
    coordinates: Optional[list[list[float]]] = None
    current_segment_index: int = 0

    @model_validator(mode='after')
    def resolve_coordinates(self) -> '_RouteRiskRequest':
        if self.route is not None and self.coordinates is None:
            self.coordinates = self.route.coordinates
        if not self.coordinates:
            raise ValueError('coordinates required: provide route.coordinates or top-level coordinates')
        return self

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


@router.get("/api/weather/alerts/current")
async def get_weather_alerts_current(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
):
    """
    現在地の気象警報・注意報を返す。

    現在地の lat/lon から都道府県を推定し、JMA 警報・注意報 API から
    正規化済みのアラート一覧を返す。120秒 TTL キャッシュ付き。

    severity: emergency > warning > advisory > unknown > none
    status:   ok | stale | unavailable
    """
    try:
        return get_alerts_for_location(lat, lon)
    except Exception as exc:
        logger.exception("weather alerts endpoint error: %s", exc)
        return {
            "status": "unavailable",
            "severity": "none",
            "location": {"lat": lat, "lon": lon, "area_name": None, "pref_code": None},
            "alerts": [],
            "updated_at": None,
            "message": "気象情報を取得できません",
        }


@router.get("/api/weather/precipitation/summary")
async def get_precipitation_summary_endpoint(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
    debug: bool = Query(False, description="デバッグ情報を含める（開発用）"),
):
    """
    現在地の降水予測サマリーを返す（Phase1.5: PNG タイルピクセル解析）。

    intensity: severe > strong > moderate > weak > none > unknown
    debug=1 指定時のみ color_table_version / zoom 等のデバッグ情報を付加する。
    """
    try:
        return get_precipitation_summary(lat, lon, debug=debug)
    except Exception as exc:
        logger.exception("precipitation summary endpoint error: %s", exc)
        return {
            "status": "unavailable",
            "severity": "none",
            "summary": "降水情報を取得できません",
            "current": {"label": "不明", "intensity": "unknown"},
            "forecast": [],
            "updated_at": None,
            "source": "jma_nowcast",
        }


@router.get("/api/weather/risk/context")
async def get_weather_risk_context(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
):
    """
    現在地の気象 × ハザード統合リスクコンテキストを返す（Phase2-C）。

    気象警報・降水予測 × ハザードゾーン（flood/inland_flood/landslide/lowland）を統合し、
    避難判断向けの複合リスク（combined risk）と統合リスクレベルを返す。

    risk_level: none | advisory | warning | emergency | unknown
    combined:   [{type, level, headline, message}]
    hazards:    {lowland, flood, inland_flood, landslide, tsunami, storm_surge, data_available}

    hazard data_available=false の場合はハザード判定なし（API は落とさない）。
    """
    try:
        return get_risk_context(lat, lon)
    except Exception as exc:
        logger.exception("risk context endpoint error: %s", exc)
        return {
            "status":     "unavailable",
            "risk_level": "unknown",
            "weather":    {"alert_severity": "unknown", "precip_severity": "unknown",
                           "current_intensity": "unknown", "forecast_max_intensity": None, "forecast_max_minutes": None},
            "hazards":    {"lowland": None, "flood": None, "inland_flood": None, "landslide": None,
                           "tsunami": None, "storm_surge": None, "data_available": False},
            "combined":   [],
            "updated_at": None,
        }


@router.post("/api/weather/risk/route")
async def get_weather_risk_route(body: _RouteRiskRequest):
    """
    ルート前方の気象リスクを返す（Phase2-D）。

    ルート座標列をサンプリングし、降水強度 × ハザードゾーンで複合リスクを評価。
    coordinates: [[lon, lat], ...] (GeoJSON 形式)
    current_segment_index: 現在位置に最も近いルート座標インデックス

    risk_level: none | advisory | warning | emergency | unknown
    summary: {headline, message} — ナビバナー文言
    segments: [{lat, lon, risk_level, combined}] — サンプル点ごとの結果
    """
    try:
        return get_route_risk(body.coordinates, body.current_segment_index)
    except Exception as exc:
        logger.exception("weather risk route endpoint error: %s", exc)
        return {
            "status":     "unavailable",
            "risk_level": "unknown",
            "segments":   [],
            "summary":    {"headline": None, "message": None},
            "updated_at": None,
        }


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
