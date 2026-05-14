"""
tide API — 現在地から最寄り地点の満潮・干潮情報を返す。
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from app.services.tide_service import (
    get_tide_info,
    get_stations,
    get_hourly_data,
    get_extremes_for_date,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_JST = timezone(timedelta(hours=9))


@router.get("/api/tide/current")
async def get_tide_current(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
):
    try:
        data = get_tide_info(lat, lon)
    except Exception as e:
        logger.warning("tide lookup failed lat=%s lon=%s: %s", lat, lon, e)
        data = None

    if data is None:
        data = {"available": False, "source": "jma"}

    return {"lat": lat, "lon": lon, **data}


@router.get("/api/tide/stations")
async def tide_stations():
    """全国潮位観測地点一覧を返す。"""
    try:
        stations = get_stations()
    except Exception as e:
        logger.warning("tide stations failed: %s", e)
        stations = []
    return {"stations": stations}


@router.get("/api/tide/hourly")
async def tide_hourly(
    station: str = Query(..., description="観測地点コード"),
    date: Optional[str] = Query(None, description="日付 YYYY-MM-DD (省略=今日JST)"),
):
    """指定地点・日付の時間毎潮位データと満干潮情報を返す。"""
    if date is None:
        date = datetime.now(_JST).strftime("%Y-%m-%d")
    try:
        records = get_hourly_data(station, date)
        extremes = get_extremes_for_date(station, date)
    except Exception as e:
        logger.warning("tide hourly failed station=%s date=%s: %s", station, date, e)
        records = []
        extremes = None
    return {"station": station, "date": date, "records": records, "extremes": extremes}
