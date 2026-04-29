"""
気象警報サービス — lat/lon から警報・注意報情報を返す。

キャッシュ:
  - area 解決結果:   本モジュールで 24h キャッシュ（lat/lon 0.05 度丸め）
  - 警報 JSON:       jma_warning_client が 120s キャッシュ
"""
import time
import logging
from typing import Optional

from services.jma_area_client import find_office_and_area
from services.jma_warning_client import fetch_warning_data, parse_area_warnings, get_highest_level

logger = logging.getLogger(__name__)

_AREA_CACHE: dict = {}   # key: (lat_q, lon_q) → (area_info, fetched_at)
_AREA_CACHE_TTL = 86400.0  # 24h — area コードは変わらない


def get_current_warnings(lat: float, lon: float) -> Optional[dict]:
    """
    現在地の警報・注意報情報を返す。

    Returns:
        {
            area_name, office_name, office_code, class10_code,
            warnings: [{code, name, level}, ...],
            highest_level,
            updated_at,      — reportDatetime (ISO8601) or None
            match_type,      — "bbox"|"fallback"|"default"
        }
        or None on unrecoverable error
    """
    # エリア解決（粗いキャッシュ: 0.05度≒5km 精度）
    lat_q = round(lat * 20) / 20   # 0.05 単位
    lon_q = round(lon * 20) / 20
    area_key = (lat_q, lon_q)
    now = time.monotonic()

    if area_key in _AREA_CACHE:
        area_info, cached_at = _AREA_CACHE[area_key]
        if now - cached_at < _AREA_CACHE_TTL:
            logger.debug("warning area: cache hit lat=%.2f lon=%.2f", lat_q, lon_q)
        else:
            area_info = None
    else:
        area_info = None

    if area_info is None:
        area_info = find_office_and_area(lat, lon)
        _AREA_CACHE[area_key] = (area_info, now)

    office_code  = area_info["office_code"]
    class10_code = area_info["class10_code"]
    area_name    = area_info["area_name"]
    office_name  = area_info["office_name"]
    match_type   = area_info["match_type"]

    # 警報 JSON 取得
    warning_data = fetch_warning_data(office_code)
    if warning_data is None:
        logger.warning(
            "warning: data unavailable office=%s area=%s", office_code, area_name
        )
        return None

    # 警報パース
    warnings = parse_area_warnings(warning_data, class10_code)
    highest_level = get_highest_level(warnings)
    updated_at = warning_data.get("reportDatetime")

    logger.info(
        "warning: office=%s(%s) area=%s(%s) match=%s warning_count=%d highest=%s",
        office_code, office_name, class10_code, area_name,
        match_type, len(warnings), highest_level,
    )

    return {
        "area_name":    area_name,
        "office_name":  office_name,
        "office_code":  office_code,
        "class10_code": class10_code,
        "warnings":     warnings,
        "highest_level": highest_level,
        "updated_at":   updated_at,
        "match_type":   match_type,
    }
