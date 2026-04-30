"""
気象サービス — 最寄りアメダス観測点の気象データを返す。

キャッシュ:
  - 観測点テーブル: amedas_client 内で 24h キャッシュ
  - map データ:     amedas_client 内で 60s キャッシュ
  - weather 結果:   本モジュールで 60s キャッシュ（lat/lon 0.01 度丸め共有）

レスポンスフィールド:
  station, station_id, station_lat, station_lon
  rain, wind, temperature       — 欠損時は None
  observed_at                   — JST ISO8601 or None
  distance_km                   — ユーザー座標から観測点までの距離（km）
  station_quality               — near(<10km) / medium(<30km) / far(>=30km)
  age_minutes                   — observed_at から現在までの経過分 or None
  freshness                     — fresh(<30min) / stale(>=30min) / unknown
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


def get_nearest_station_with_keys(
    lat: float,
    lon: float,
    station_table: dict,
    map_data: dict,
    required_keys: list[str],
) -> Optional[dict]:
    """
    map_data 内で required_keys の値が全て非 null な観測点のうち最寄りを返す。
    タイプC（雨量専用）観測点は temp / wind を持たないため、
    気温・風速取得時はこの関数で絞り込む。
    """
    best = None
    best_dist = float("inf")
    for sid, obs in map_data.items():
        if not all(extract_value(obs, k) is not None for k in required_keys):
            continue
        info = station_table.get(sid)
        if not info:
            continue
        dist = _haversine(lat, lon, info["lat"], info["lon"])
        if dist < best_dist:
            best_dist = dist
            best = info
    return best


def _utc_str_to_jst_iso(utc_str: str) -> Optional[str]:
    """UTC タイムスタンプ文字列を JST ISO8601 文字列に変換する。"""
    try:
        dt_utc = datetime.strptime(utc_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return dt_utc.astimezone(_JST).isoformat()
    except Exception:
        return None


def _calc_station_quality(distance_km: float) -> str:
    if distance_km < 10.0:
        return "near"
    if distance_km < 30.0:
        return "medium"
    return "far"


def _calc_freshness(observed_at: Optional[str]) -> tuple[Optional[float], str]:
    """Returns (age_minutes, freshness_label)."""
    if not observed_at:
        return None, "unknown"
    try:
        obs_dt = datetime.fromisoformat(observed_at)
        age_sec = (datetime.now(timezone.utc) - obs_dt.astimezone(timezone.utc)).total_seconds()
        age_min = round(age_sec / 60.0, 1)
        freshness = "fresh" if age_min < 30.0 else "stale"
        return age_min, freshness
    except Exception:
        return None, "unknown"


def get_current_weather(lat: float, lon: float) -> Optional[dict]:
    """
    現在地の最寄り観測点の気象データを返す。

    Returns:
        dict with station / rain / wind / temperature / observed_at /
        distance_km / station_quality / age_minutes / freshness
        — or None on unrecoverable error
    """
    lat_q = round(lat, 2)
    lon_q = round(lon, 2)
    cache_key = (lat_q, lon_q)
    now = time.monotonic()

    if cache_key in _WEATHER_CACHE:
        result, fetched_at = _WEATHER_CACHE[cache_key]
        if now - fetched_at < _WEATHER_TTL:
            logger.info(
                "weather: cache hit lat=%.2f lon=%.2f station=%s distance_km=%s freshness=%s",
                lat_q, lon_q, result.get("station"), result.get("distance_km"), result.get("freshness"),
            )
            return result

    station_table = fetch_station_table()
    if not station_table:
        logger.warning("weather: station table empty")
        return None

    map_data = fetch_map_data()
    if not map_data:
        logger.warning("weather: map data unavailable")
        return None

    # 気温・風速は全観測点データを持つ観測点（タイプA相当）から最寄りを選ぶ。
    full_station = get_nearest_station_with_keys(
        lat, lon, station_table, map_data, ["temp", "wind"]
    )
    nearest = get_nearest_station(lat, lon, station_table)
    if not nearest:
        return None

    primary = full_station or nearest
    primary_obs = map_data.get(primary["station_id"]) or {}
    nearest_obs = map_data.get(nearest["station_id"]) or {}

    # 雨量: タイプA観測点（full_station）を優先し、未取得なら最寄りにフォールバック
    rain_primary = extract_value(primary_obs, "precipitation1h")
    rain         = rain_primary if rain_primary is not None else extract_value(nearest_obs, "precipitation1h")
    wind         = extract_value(primary_obs, "wind")
    temperature  = extract_value(primary_obs, "temp")

    # 表示観測点: 気温/風速/雨量の取得元を優先表示
    station_name = nearest["station_name"]
    primary_is_distinct = (
        full_station is not None
        and full_station["station_id"] != nearest["station_id"]
    )
    if primary_is_distinct:
        station_name = full_station["station_name"]
        logger.info(
            "weather: rain/wind/temp from %s (full station); nearest=%s",
            full_station["station_name"], nearest["station_name"],
        )

    # 観測点説明ラベル（提供データの種別を明示）
    if primary_is_distinct and rain_primary is not None:
        station_desc = f"{station_name}（気温・風・雨量）"
    elif primary_is_distinct:
        station_desc = (
            f"{station_name}（気温・風）"
            f" / {nearest['station_name']}（雨量のみ参考）"
        )
    else:
        station_desc = station_name

    sid = primary["station_id"]

    # 距離・品質
    dist_m = _haversine(lat, lon, primary["lat"], primary["lon"])
    distance_km = round(dist_m / 1000.0, 1)
    station_quality = _calc_station_quality(distance_km)

    # 観測時刻・鮮度
    ts_utc = fetch_latest_time_utc()
    observed_at = _utc_str_to_jst_iso(ts_utc) if ts_utc else None
    age_minutes, freshness = _calc_freshness(observed_at)

    # 欠損フィールドのログ
    missing = [k for k, v in [("rain", rain), ("wind", wind), ("temperature", temperature)] if v is None]
    if missing:
        logger.info("weather: missing fields=%s station=%s", missing, station_name)

    logger.info(
        "weather: cache miss — station=%s(%s) distance_km=%.1f quality=%s "
        "rain=%s(src=%s) wind=%s temp=%s freshness=%s age_min=%s",
        station_name, sid, distance_km, station_quality,
        rain, "primary" if rain_primary is not None else "nearest",
        wind, temperature, freshness, age_minutes,
    )

    result = {
        "station":         station_name,
        "station_desc":    station_desc,
        "station_id":      sid,
        "station_lat":     primary["lat"],
        "station_lon":     primary["lon"],
        "rain":            rain,
        "wind":            wind,
        "temperature":     temperature,
        "observed_at":     observed_at,
        "distance_km":     distance_km,
        "station_quality": station_quality,
        "age_minutes":     age_minutes,
        "freshness":       freshness,
    }
    _WEATHER_CACHE[cache_key] = (result, now)
    return result
