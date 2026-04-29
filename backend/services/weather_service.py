"""
気象サービス — 最寄りアメダス観測点の気象データを返す。

キャッシュ:
  - 観測点テーブル: amedas_client 内で 24h キャッシュ
  - map データ:     amedas_client 内で 60s キャッシュ
  - weather 結果:   本モジュールで 60s キャッシュ（lat/lon 0.01 度丸め共有）
"""
import math
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from services.amedas_client import (
    fetch_station_table,
    fetch_map_data,
    fetch_latest_time_utc,
    extract_value,
)

logger = logging.getLogger(__name__)

_WEATHER_CACHE: dict = {}  # key: (lat_q, lon_q) → (result, fetched_at)
_WEATHER_TTL = 60.0
_JST = timezone(timedelta(hours=9))


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(a, 1.0)))


def get_nearest_station(lat: float, lon: float, station_table: dict) -> Optional[dict]:
    """観測点テーブルから最寄りを返す（O(n) 線形探索）。"""
    best = None
    best_dist = float("inf")
    for info in station_table.values():
        dist = _haversine(lat, lon, info["lat"], info["lon"])
        if dist < best_dist:
            best_dist = dist
            best = info
    return best


def _utc_str_to_jst_iso(utc_str: str) -> Optional[str]:
    """UTC タイムスタンプ文字列を JST ISO8601 文字列に変換する。"""
    try:
        dt_utc = datetime.strptime(utc_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        dt_jst = dt_utc.astimezone(_JST)
        return dt_jst.isoformat()
    except Exception:
        return None


def get_current_weather(lat: float, lon: float) -> Optional[dict]:
    """
    現在地の最寄り観測点の気象データを返す。

    Returns:
        {station, station_id, station_lat, station_lon, rain, wind, temperature, observed_at}
        or None on error
    """
    lat_q = round(lat, 2)
    lon_q = round(lon, 2)
    cache_key = (lat_q, lon_q)
    now = time.monotonic()

    if cache_key in _WEATHER_CACHE:
        result, fetched_at = _WEATHER_CACHE[cache_key]
        if now - fetched_at < _WEATHER_TTL:
            return result

    station_table = fetch_station_table()
    if not station_table:
        logger.warning("weather: station table empty")
        return None

    nearest = get_nearest_station(lat, lon, station_table)
    if not nearest:
        return None

    map_data = fetch_map_data()
    if not map_data:
        logger.warning("weather: map data unavailable")
        return None

    sid = nearest["station_id"]
    obs = map_data.get(sid)
    if not obs:
        logger.warning("weather: station %s not in map data", sid)
        return None

    rain = extract_value(obs, "precipitation1h")
    wind = extract_value(obs, "wind")
    temperature = extract_value(obs, "temp")

    ts_utc = fetch_latest_time_utc()
    observed_at = _utc_str_to_jst_iso(ts_utc) if ts_utc else None

    result = {
        "station": nearest["station_name"],
        "station_id": sid,
        "station_lat": nearest["lat"],
        "station_lon": nearest["lon"],
        "rain": rain,
        "wind": wind,
        "temperature": temperature,
        "observed_at": observed_at,
    }
    _WEATHER_CACHE[cache_key] = (result, now)
    logger.info(
        "weather: station=%s rain=%s wind=%s temp=%s ts=%s",
        nearest["station_name"], rain, wind, temperature, observed_at,
    )
    return result
