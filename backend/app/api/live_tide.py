"""
live_tide.py — /live 潮位観測点 API

GET /api/live/tide/stations          全国観測点一覧
GET /api/live/tide/stations/{id}     観測点詳細（現在潮位・満干潮・時系列）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from app.services.tide_service import (
    get_stations,
    get_station_meta,
    has_station_data,
    get_hourly_data,
    get_extremes_for_date,
    _get_current_tide_cm,
    _get_next_extreme,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live/tide", tags=["live-tide"])

_JST = timezone(timedelta(hours=9))


@router.get("/stations")
async def live_tide_stations() -> Dict[str, Any]:
    """全国潮位観測点一覧を返す（データあり地点のみ）。"""
    try:
        stations = get_stations()
    except Exception as exc:
        logger.warning("live tide stations failed: %s", exc)
        stations = []
    result = [s for s in stations if s.get("has_data")]
    logger.info("live tide stations loaded: count=%d", len(result))
    return {
        "count": len(result),
        "stations": result,
    }


@router.get("/stations/{station_id}")
async def live_tide_station_detail(station_id: str) -> Dict[str, Any]:
    """指定観測点の現在潮位・満干潮・時系列データを返す。"""
    # 観測点マスタ検索（モジュール関数経由で最新 _stations を参照）
    station_meta: Optional[dict] = get_station_meta(station_id)
    if station_meta is None:
        raise HTTPException(status_code=404, detail=f"station not found: {station_id}")

    if not has_station_data(station_id):
        raise HTTPException(status_code=404, detail=f"no data for station: {station_id}")

    now = datetime.now(_JST)
    today    = now.strftime("%Y-%m-%d")
    prev_day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    next_day = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    current_tide_cm = _get_current_tide_cm(station_id, now)
    next_high = _get_next_extreme(station_id, now, "high")
    next_low  = _get_next_extreme(station_id, now, "low")

    # 前日・当日・翌日の時系列（グラフ用）
    records: List[dict] = []
    extremes_all: Dict[str, list] = {"high_tides": [], "low_tides": []}
    for date_str in [prev_day, today, next_day]:
        records.extend(get_hourly_data(station_id, date_str))
        ex = get_extremes_for_date(station_id, date_str)
        if ex:
            extremes_all["high_tides"].extend(ex.get("high_tides") or [])
            extremes_all["low_tides"].extend(ex.get("low_tides") or [])

    name = station_meta.get("station_name") or station_meta.get("name", station_id)
    logger.info(
        "live tide station: id=%s current=%s",
        station_id,
        current_tide_cm if current_tide_cm is not None else "N/A",
    )

    return {
        "station_id":      station_id,
        "name":            name,
        "lat":             station_meta["lat"],
        "lon":             station_meta["lon"],
        "prefecture":      station_meta.get("prefecture", ""),
        "current_tide_cm": current_tide_cm,
        "next_high_tide":  next_high,
        "next_low_tide":   next_low,
        "records":         records,
        "extremes":        extremes_all,
    }
