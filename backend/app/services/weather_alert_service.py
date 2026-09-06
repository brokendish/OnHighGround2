"""
weather_alert_service.py — 警報・注意報 + 降水予測サマリー サービス

キャッシュ戦略:
  - 警報・注意報: TTL 120秒（メモリ）+ 永続JSONキャッシュ（再起動後も利用）
  - 降水予測: TTL 60秒（メモリのみ）
  - JMA取得失敗時: stale cache あれば status=stale で返す
  - stale もなければ status=unavailable で返す

現在地連動:
  - lat/lon → reverse geocode → city名 → 一次細分区域フィルタリング
  - 都道府県全体から city に該当する area_name の警報のみ返す
  - city 解決失敗時は都道府県全体を返す（フォールバック）
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.weather_alert import WeatherAlertItem, max_severity, to_dict
from app.services.jma_weather_adapter import (
    _AREA_CITY_KEYWORDS,
    fetch_warnings_for_pref,
    filter_alerts_for_city,
    resolve_pref_code,
)

logger = logging.getLogger(__name__)

_ALERT_TTL = 120.0   # 秒
_PRECIP_TTL = 60.0
_NOWCAST_DEFAULT_ZOOM = 8   # jma_rain_tile_service と同値（debug レスポンス用）

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PERSISTENT_CACHE_DIR = _PROJECT_ROOT / "data_runtime" / "cache" / "weather"

# メモリキャッシュ: key = pref_code, value = (items, fetched_at_monotonic)
_alert_cache: dict[str, tuple[list[WeatherAlertItem], float]] = {}
# メモリキャッシュ: key = pref_code, value = (summary_dict, fetched_at_monotonic)
_precip_cache: dict[str, tuple[dict, float]] = {}


def _persistent_cache_path(pref_code: str) -> Path:
    return _PERSISTENT_CACHE_DIR / f"alerts_{pref_code}.json"


def _load_persistent_cache(pref_code: str) -> Optional[list[WeatherAlertItem]]:
    path = _persistent_cache_path(pref_code)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        items = []
        for d in raw:
            items.append(WeatherAlertItem(
                area_code=d.get("area_code"),
                area_name=d.get("area_name", ""),
                source_area_type=d.get("source_area_type"),
                kind=d.get("kind", ""),
                level=d.get("level", ""),
                severity=d.get("severity", "unknown"),
                status=d.get("status", ""),
                headline=d.get("headline", ""),
                issued_at=d.get("issued_at"),
                updated_at=d.get("updated_at"),
                source=d.get("source", "jma"),
                raw_code=d.get("raw_code"),
            ))
        return items
    except Exception as exc:
        logger.warning("weather_alert_service: persistent cache load failed pref=%s: %s", pref_code, exc)
        return None


def _save_persistent_cache(pref_code: str, items: list[WeatherAlertItem]) -> None:
    try:
        _PERSISTENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _persistent_cache_path(pref_code)
        with path.open("w", encoding="utf-8") as f:
            json.dump([to_dict(i) for i in items], f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("weather_alert_service: persistent cache save failed pref=%s: %s", pref_code, exc)


def _city_from_address_text(address: Optional[str]) -> Optional[str]:
    if not address:
        return None
    for keywords in _AREA_CITY_KEYWORDS.values():
        for keyword in keywords:
            if keyword and keyword in address:
                return keyword
    return None


def _pref_from_address_text(address: Optional[str]) -> Optional[str]:
    if not address:
        return None
    for pref_name in _get_pref_name_to_code().keys():
        if pref_name in address:
            return pref_name
    return None


def _resolve_city(lat: float, lon: float) -> tuple[Optional[str], Optional[str]]:
    """
    逆ジオコードから (city, geocoded_pref_name) を返す。
    geocoded_pref_name: Nominatim の address.state 相当（都道府県名）。
    島嶼部など重心距離が誤る場合に pref_code 補正に使う。
    """
    try:
        from app.services.reverse_geocode_service import get_reverse_geocode_service
        result = get_reverse_geocode_service().reverse_geocode(lat, lon)
        city_from_address = _city_from_address_text(result.get("address"))
        city = city_from_address or result.get("city")
        # 逆ジオコードが都道府県名を city に返す場合（島嶼部など）は pref 補正に使う
        raw = result.get("raw") or {}
        addr = raw.get("address") or {}
        geocoded_pref = addr.get("state") or addr.get("province") or _pref_from_address_text(result.get("address"))
        # city 自体が都道府県名のときも pref として扱う（Nominatim が island area で state省略する場合）
        if city and not geocoded_pref:
            if any(city.endswith(s) for s in ("都", "道", "府", "県")):
                geocoded_pref = city
                city = None
        return city, geocoded_pref
    except Exception as exc:
        logger.warning("weather_alert_service: city resolve failed lat=%s lon=%s: %s", lat, lon, exc)
        return None, None


# 都道府県名 → pref_code の逆引きテーブル（起動時に構築）
def _build_pref_name_to_code() -> dict[str, str]:
    from app.services.jma_weather_adapter import _PREF_CENTROIDS
    return {name: code for code, (name, _, _) in _PREF_CENTROIDS.items()}

_PREF_NAME_TO_CODE: dict[str, str] = {}


def _get_pref_name_to_code() -> dict[str, str]:
    global _PREF_NAME_TO_CODE
    if not _PREF_NAME_TO_CODE:
        _PREF_NAME_TO_CODE = _build_pref_name_to_code()
    return _PREF_NAME_TO_CODE


def get_alerts_for_location(lat: float, lon: float) -> dict:
    """
    現在地の警報・注意報を返す。

    Returns:
        {
            status: "ok" | "stale" | "unavailable",
            severity: "emergency" | "warning" | "advisory" | "unknown" | "none",
            location: {lat, lon, area_name, pref_code, city},
            alerts: [...WeatherAlertItem dict...],
            updated_at: ISO8601 str | None,
            message: str | None,
        }
    """
    pref_code, pref_name = resolve_pref_code(lat, lon)
    city, geocoded_pref = _resolve_city(lat, lon)

    # 逆ジオコードが都道府県名を返した場合（島嶼部など）は pref_code を補正
    if geocoded_pref:
        override_code = _get_pref_name_to_code().get(geocoded_pref)
        if override_code and override_code != pref_code:
            logger.info(
                "weather_alert_service: pref_code overridden by geocode %s(%s) → %s lat=%s lon=%s",
                geocoded_pref, pref_code, override_code, lat, lon,
            )
            pref_code = override_code
            pref_name = geocoded_pref
    now = time.monotonic()
    now_iso = datetime.now(timezone.utc).isoformat()

    # メモリキャッシュ確認
    cached = _alert_cache.get(pref_code)
    if cached is not None:
        items, fetched_at = cached
        if now - fetched_at < _ALERT_TTL:
            logger.debug("weather_alert_service: memory cache hit pref=%s", pref_code)
            filtered = filter_alerts_for_city(items, city)
            return _build_alert_response("ok", filtered, pref_code, pref_name, lat, lon, now_iso, city)

    # JMA取得
    try:
        items = fetch_warnings_for_pref(pref_code, pref_name)
        _alert_cache[pref_code] = (items, now)
        _save_persistent_cache(pref_code, items)
        filtered = filter_alerts_for_city(items, city)
        return _build_alert_response("ok", filtered, pref_code, pref_name, lat, lon, now_iso, city)
    except Exception as exc:
        logger.warning("weather_alert_service: fetch failed pref=%s: %s", pref_code, exc)

    # メモリ stale fallback
    if cached is not None:
        items, _ = cached
        logger.info("weather_alert_service: serving memory stale cache pref=%s", pref_code)
        filtered = filter_alerts_for_city(items, city)
        return _build_alert_response("stale", filtered, pref_code, pref_name, lat, lon, now_iso, city)

    # 永続キャッシュ fallback
    persistent = _load_persistent_cache(pref_code)
    if persistent is not None:
        logger.info("weather_alert_service: serving persistent cache pref=%s", pref_code)
        # メモリにも戻す（次回はメモリから返せるように）
        _alert_cache[pref_code] = (persistent, 0.0)
        filtered = filter_alerts_for_city(persistent, city)
        return _build_alert_response("stale", filtered, pref_code, pref_name, lat, lon, now_iso, city)

    # unavailable
    return {
        "status": "unavailable",
        "severity": "none",
        "location": {"lat": lat, "lon": lon, "area_name": pref_name, "pref_code": pref_code, "city": city},
        "alerts": [],
        "updated_at": now_iso,
        "message": "気象情報を取得できません",
    }


def _build_alert_response(
    status: str,
    items: list[WeatherAlertItem],
    pref_code: str,
    pref_name: str,
    lat: float,
    lon: float,
    updated_at: str,
    city: Optional[str] = None,
) -> dict:
    severity = max_severity(items)
    alert_dicts = [to_dict(i) for i in items]
    message = None if items else "警報・注意報なし"
    if status == "stale":
        message = "最新の気象情報を取得できません（前回取得データを表示中）"
    return {
        "status": status,
        "severity": severity,
        "location": {
            "lat": lat,
            "lon": lon,
            "area_name": pref_name,
            "pref_code": pref_code,
            "city": city,
        },
        "alerts": alert_dicts,
        "updated_at": updated_at,
        "message": message,
    }


def get_precipitation_summary(lat: float, lon: float, debug: bool = False) -> dict:
    """
    現在地の降水予測サマリーを返す（Phase1.5: PNG タイルピクセル解析）。

    Returns:
        {
            status: "ok" | "unavailable",
            severity: "warning" | "advisory" | "none" | "unknown",
            summary: str,
            current: {label, intensity},
            forecast: [{minutes, label, intensity}],
            updated_at: ISO8601 str,
            source: "jma_nowcast",
        }
    """
    pref_code, _ = resolve_pref_code(lat, lon)
    now = time.monotonic()
    now_iso = datetime.now(timezone.utc).isoformat()

    cached = _precip_cache.get(pref_code)
    if cached is not None and not debug:
        summary, fetched_at = cached
        if now - fetched_at < _PRECIP_TTL:
            return summary

    summary = _build_precip_summary(lat, lon, now_iso, debug=debug)
    if not debug:
        _precip_cache[pref_code] = (summary, now)
    return summary


def _build_precip_summary(lat: float, lon: float, now_iso: str, debug: bool = False) -> dict:
    """
    降水ナウキャストタイルを取得してピクセル解析し、降水強度サマリーを返す。
    タイル取得失敗時は unavailable を返す（API は落とさない）。
    """
    try:
        from services.jma_rain_tile_service import get_rain_tile_times, fetch_precip_intensities, get_color_table_version
        tile_data = get_rain_tile_times()
        if tile_data is None:
            raise ValueError("tile_data is None")
    except Exception as exc:
        logger.warning("weather_alert_service: precip tile fetch failed: %s", exc)
        return {
            "status": "unavailable",
            "severity": "none",
            "summary": "降水ナウキャストデータを取得できません",
            "current": {"label": "不明", "intensity": "unknown"},
            "forecast": [],
            "updated_at": now_iso,
            "source": "jma_nowcast",
        }

    times = tile_data.get("times", [])
    if not times:
        return {
            "status": "unavailable",
            "severity": "none",
            "summary": "降水ナウキャストデータを取得できません",
            "current": {"label": "不明", "intensity": "unknown"},
            "forecast": [],
            "updated_at": now_iso,
            "source": "jma_nowcast",
        }

    # offset=0 が現在観測、正値が予測（+5〜+30min を対象）
    current_entry = min(times, key=lambda t: abs(t.get("offset_minutes", 0)))
    forecast_entries = sorted(
        [t for t in times if 0 < t.get("offset_minutes", 0) <= 30],
        key=lambda t: t["offset_minutes"],
    )

    # 現在 + 予測 30 分以内を並列取得・解析
    all_targets = [current_entry] + forecast_entries[:6]
    try:
        intensities = fetch_precip_intensities(lat, lon, all_targets, max_workers=4, max_forecast_min=30, debug=debug)
    except Exception as exc:
        logger.warning("weather_alert_service: precip intensity analysis failed: %s", exc)
        intensities = {}

    # 現在の強度
    cur_off = current_entry.get("offset_minutes", 0)
    cur_result = intensities.get(cur_off, {"intensity": "unknown", "label": "判定不能"})
    current_intensity = cur_result.get("intensity", "unknown")
    current_label = cur_result.get("label", "判定不能")

    # 予測リスト構築
    forecast: list[dict] = []
    for t in forecast_entries[:6]:
        off = t["offset_minutes"]
        r = intensities.get(off, {"intensity": "unknown", "label": "判定不能"})
        intensity = r.get("intensity", "unknown")
        forecast.append({
            "minutes":   off,
            "label":     _precip_forecast_label(off, intensity),
            "intensity": intensity,
        })

    # severity 決定（現在 + 予測 30 分以内の最大強度から）
    all_intensities = [current_intensity] + [f["intensity"] for f in forecast]
    severity = _precip_severity(all_intensities)
    summary_text = _precip_summary_text(severity, all_intensities)

    response: dict = {
        "status":   "ok",
        "severity": severity,
        "summary":  summary_text,
        "current":  {"label": current_label, "intensity": current_intensity},
        "forecast": forecast,
        "updated_at": now_iso,
        "source":   "jma_nowcast",
    }
    if debug:
        try:
            ctv = get_color_table_version()
        except Exception:
            ctv = "unknown"
        cur_dbg = cur_result.get("debug") if isinstance(cur_result, dict) else None
        response["debug"] = {
            "color_table_version": ctv,
            "zoom":               _NOWCAST_DEFAULT_ZOOM,
            "sample_radius_px":   2,
            "current_tile_debug": cur_dbg,
        }
    return response


_INTENSITY_RANK = {"severe": 4, "strong": 3, "moderate": 2, "weak": 1, "none": 0, "unknown": -1}


def _precip_severity(intensities: list[str]) -> str:
    known = [i for i in intensities if i != "unknown"]
    if not known:
        return "unknown"
    max_rank = max((_INTENSITY_RANK.get(i, -1) for i in known), default=-1)
    if max_rank >= 3:   # strong or severe
        return "warning"
    if max_rank >= 1:   # weak or moderate
        return "advisory"
    return "none"


_PRECIP_INTENSITY_LABEL: dict[str, str] = {
    "none":     "降水なし",
    "weak":     "弱い雨",
    "moderate": "雨",
    "strong":   "強い雨",
    "severe":   "非常に激しい雨",
    "unknown":  "判定不能",
}


def _precip_forecast_label(offset_min: int, intensity: str) -> str:
    label = _PRECIP_INTENSITY_LABEL.get(intensity, intensity)
    return f"+{offset_min}分: {label}"


def _precip_summary_text(severity: str, intensities: list[str]) -> str:
    if severity == "warning":
        return "30分以内に強雨域が接近する可能性があります"
    if severity == "advisory":
        max_i = max((_INTENSITY_RANK.get(i, -1) for i in intensities if i != "unknown"), default=0)
        if max_i >= 2:
            return "30分以内に雨域が接近する可能性があります"
        return "弱い雨が予測されています"
    if severity == "none":
        return "降水リスクなし"
    return "降水予測を判定できません"
