"""
jma_weather_adapter.py — JMA 警報・注意報の取得と正規化

JMA仕様変更はこのファイルだけで吸収する。UI側は正規化モデルのみ参照すること。

エンドポイント（2026年5月時点）:
  https://www.jma.go.jp/bosai/warning/data/warning/{pref_code}.json

pref_code: 6桁の都道府県コード（例: 130000 = 東京都）

仕様変更対策:
  - raw payload を UI に流さない
  - field名変更は _extract_warnings() で吸収
  - unknown な警報種別は "unknown" severity として保持
  - parse failure 時も例外を握り潰してログのみ出す
"""
import json
import logging
import math
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.weather_alert import WeatherAlertItem

logger = logging.getLogger(__name__)

_JMA_WARNING_BASE = "https://www.jma.go.jp/bosai/warning/data/warning/{pref_code}.json"
_HTTP_TIMEOUT = 10
_USER_AGENT = "OnHighGround2/1.0 (https://ohg.brokendish.org/)"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_AREA_CODES_PATH = _PROJECT_ROOT / "data_runtime" / "backend" / "weather" / "jma_area_codes.json"
_AREA_CODES_FALLBACK = _PROJECT_ROOT / "data_lake" / "registry" / "weather" / "jma_area_codes.json"


def _load_area_codes() -> dict:
    for path in (_AREA_CODES_PATH, _AREA_CODES_FALLBACK):
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("jma_weather_adapter: failed to load area codes from %s: %s", path, exc)
    logger.error("jma_weather_adapter: jma_area_codes.json not found — using empty fallback")
    return {}


_area_codes_data = _load_area_codes()

# 都道府県コード → (都道府県名, 重心緯度, 重心経度)
_PREF_CENTROIDS: dict[str, tuple[str, float, float]] = {
    code: (info["name"], info["lat"], info["lon"])
    for code, info in _area_codes_data.get("pref_centroids", {}).items()
}

# 一次細分区域名 → 市区町村キーワードリスト
_AREA_CITY_KEYWORDS: dict[str, list[str]] = _area_codes_data.get("area_city_keywords", {})

# 警報種別コード → severity（JMA 2026年5月時点の警報コード）
# 仕様変更時はここを修正する。名前ベースのフォールバックも持つ。
_CODE_SEVERITY: dict[str, str] = {
    # 特別警報（emergency）
    "14": "emergency",  # 大雨特別警報（土砂災害）
    "15": "emergency",  # 大雨特別警報（浸水害）
    "16": "emergency",  # 大雨特別警報（河川氾濫）
    "22": "emergency",  # 洪水特別警報
    "35": "emergency",  # 暴風特別警報
    "36": "emergency",  # 暴風雪特別警報
    "37": "emergency",  # 大雪特別警報
    "38": "emergency",  # 波浪特別警報
    "39": "emergency",  # 高潮特別警報
    # 警報（warning）
    "04": "warning",    # 大雨警報（土砂災害）
    "05": "warning",    # 大雨警報（浸水害）
    "03": "warning",    # 洪水警報
    "02": "warning",    # 大雨警報（土砂・浸水）
    "33": "warning",    # 暴風警報
    "34": "warning",    # 暴風雪警報
    "32": "warning",    # 大雪警報
    "10": "warning",    # 高潮警報
    "12": "warning",    # 波浪警報
    # 注意報（advisory）
    "17": "advisory",   # 大雨注意報
    "18": "advisory",   # 洪水注意報
    "19": "advisory",   # 強風注意報
    "20": "advisory",   # 風雪注意報
    "21": "advisory",   # 大雪注意報
    "23": "advisory",   # 波浪注意報
    "24": "advisory",   # 高潮注意報
    "25": "advisory",   # 雷注意報
    "26": "advisory",   # 融雪注意報
    "27": "advisory",   # 濃霧注意報
    "28": "advisory",   # 乾燥注意報
    "29": "advisory",   # なだれ注意報
    "30": "advisory",   # 低温注意報
    "31": "advisory",   # 霜注意報
    "40": "advisory",   # 着氷注意報
    "41": "advisory",   # 着雪注意報
}

# active と見なすステータス文字列（仕様変更でテキストが変わった場合はここを修正）
_ACTIVE_STATUSES = frozenset(["発表", "継続", "更新", "発表・更新"])


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(a, 1.0)))


def filter_alerts_for_city(
    items: list[WeatherAlertItem],
    city_name: Optional[str],
    area_city_keywords: Optional[dict[str, list[str]]] = None,
) -> list[WeatherAlertItem]:
    """
    city_name が含まれる一次細分区域の警報・注意報のみ返す。
    city_name が None または area_city_keywords に該当なければ全件返す（府県全体として扱う）。
    """
    if not city_name or not items:
        return items

    keywords_map = area_city_keywords if area_city_keywords is not None else _AREA_CITY_KEYWORDS
    if not keywords_map:
        return items

    # city_name が属する一次細分区域名を特定
    matched_areas: set[str] = set()
    for area_label, keywords in keywords_map.items():
        for kw in keywords:
            if city_name.startswith(kw) or kw in city_name:
                matched_areas.add(area_label)
                break

    if not matched_areas:
        return items

    # area_name が matched_areas に含まれる items だけ返す
    filtered = [i for i in items if i.area_name in matched_areas]
    return filtered if filtered else items


def resolve_pref_code(lat: float, lon: float) -> tuple[str, str]:
    """lat/lon から最近傍の都道府県コードと名称を返す。"""
    best_code = "130000"
    best_name = "東京都"
    best_dist = float("inf")
    for code, (name, clat, clon) in _PREF_CENTROIDS.items():
        dist = _haversine(lat, lon, clat, clon)
        if dist < best_dist:
            best_dist = dist
            best_code = code
            best_name = name
    return best_code, best_name


def _infer_severity_from_name(name: str) -> str:
    """警報種別名から severity を推定する（コードが不明な場合のフォールバック）。"""
    if "特別警報" in name:
        return "emergency"
    if "警報" in name:
        return "warning"
    if "注意報" in name:
        return "advisory"
    return "unknown"


def _normalize_severity(raw_code: Optional[str], name: str) -> str:
    if raw_code and raw_code in _CODE_SEVERITY:
        return _CODE_SEVERITY[raw_code]
    return _infer_severity_from_name(name)


def _extract_warnings(area: dict) -> list[dict]:
    """area dict から警報・注意報リストを取り出す。フィールド名変更を吸収する。"""
    for key in ("warnings", "kinds", "items", "alerts"):
        val = area.get(key)
        if isinstance(val, list):
            return val
    return []


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return resp.read()


def fetch_warnings_for_pref(
    pref_code: str,
    pref_name: str,
    reported_at: Optional[str] = None,
) -> list[WeatherAlertItem]:
    """
    指定都道府県の JMA 警報・注意報を取得して WeatherAlertItem リストに変換する。

    Returns: アクティブな警報・注意報のリスト。エラー時は空リスト。
    """
    url = _JMA_WARNING_BASE.format(pref_code=pref_code)
    try:
        raw = _http_get(url)
    except Exception as exc:
        logger.warning("jma_weather_adapter: HTTP fetch failed pref=%s: %s", pref_code, exc)
        raise

    try:
        payload = json.loads(raw)
    except Exception as exc:
        logger.error("jma_weather_adapter: JSON parse error pref=%s: %s", pref_code, exc)
        return []

    items: list[WeatherAlertItem] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    report_dt = _safe_report_datetime(payload)
    updated_at = report_dt or reported_at or now_iso

    area_types = payload.get("areaTypes")
    if not isinstance(area_types, list):
        logger.warning("jma_weather_adapter: unexpected structure pref=%s (no areaTypes)", pref_code)
        return []

    for at in area_types:
        if not isinstance(at, dict):
            continue
        area_type = str(at.get("areaType", ""))
        areas = at.get("areas")
        if not isinstance(areas, list):
            continue

        for area in areas:
            if not isinstance(area, dict):
                continue
            area_code_raw = str(area.get("code", ""))
            area_name = str(area.get("name", pref_name))
            warnings = _extract_warnings(area)

            for w in warnings:
                if not isinstance(w, dict):
                    continue
                try:
                    raw_code = str(w.get("code", "")) or None
                    name = str(w.get("name", ""))
                    status_raw = str(w.get("status", ""))

                    if not name:
                        continue

                    # 解除済みはスキップ（「解除」のみスキップ、不明ステータスは保持）
                    if status_raw == "解除":
                        continue

                    severity = _normalize_severity(raw_code, name)

                    # level 判定（警報 or 注意報 or 特別警報）
                    if "特別警報" in name:
                        level = "特別警報"
                    elif "警報" in name:
                        level = "警報"
                    elif "注意報" in name:
                        level = "注意報"
                    else:
                        level = "不明"

                    headline = f"{name} {status_raw}" if status_raw else name

                    items.append(WeatherAlertItem(
                        area_code=area_code_raw or None,
                        area_name=area_name,
                        source_area_type=area_type or None,
                        kind=name,
                        level=level,
                        severity=severity,
                        status=status_raw,
                        headline=headline,
                        issued_at=updated_at,
                        updated_at=updated_at,
                        source="jma",
                        raw_code=raw_code,
                    ))
                except Exception as exc:
                    logger.warning(
                        "jma_weather_adapter: item parse error pref=%s area=%s: %s",
                        pref_code, area_name, exc,
                    )
                    continue

    logger.info(
        "jma_weather_adapter: fetched pref=%s items=%d updated_at=%s",
        pref_code, len(items), updated_at,
    )
    return items


def _safe_report_datetime(payload: dict) -> Optional[str]:
    for key in ("reportDatetime", "targetDateTime", "report_datetime"):
        val = payload.get(key)
        if val and isinstance(val, str):
            return val
    return None
