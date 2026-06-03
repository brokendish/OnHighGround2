"""
jma_weather_adapter.py — JMA 警報・注意報の取得と正規化

JMA仕様変更はこのファイルだけで吸収する。UI側は正規化モデルのみ参照すること。

エンドポイント（2026年6月時点）:
  https://www.jma.go.jp/bosai/warning/data/r8/{pref_code}.json  ← 公式ページが実際に読むURL
  （旧 data/warning/{pref_code}.json は更新が止まっており使用不可）

pref_code: 6桁の都道府県コード（例: 130000 = 東京都）

r8 フォーマット仕様:
  - root: array（5件前後）。各要素が dataTypeCode ごとの現象種別レコード。
  - record.warning.class10Items / class20Items に area ごとの発令状況。
  - 旧 areaTypes 構造ではなく areaCode + kinds[] フィールド。
  - 全レコードをマージし、解除・はなし 以外をアクティブと判定する。

仕様変更対策:
  - raw payload を UI に流さない
  - field名変更は _parse_r8_payload() / _extract_warnings() で吸収
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

# 公式ページが実際に使用している新 URL（2026-06 確認）
_JMA_WARNING_BASE = "https://www.jma.go.jp/bosai/warning/data/r8/{pref_code}.json"
# 旧 URL（更新停止のため使用不可。構造参照用として残す）
_JMA_WARNING_LEGACY_BASE = "https://www.jma.go.jp/bosai/warning/data/warning/{pref_code}.json"
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

# 一次細分区域コード → 区域名（class10s）
# 2026-06 JMA仕様変更対応: areaTypes.areas[].name が廃止され code のみになった
_AREA_CODE_NAME: dict[str, str] = _area_codes_data.get("area_code_names", {})

# 警報種別コード → severity（JMA / warning JSON の warn code）
# 仕様変更時はここを修正する。名前ベースのフォールバックも持つ。
_CODE_SEVERITY: dict[str, str] = {
    # 特別警報（emergency）
    "32": "emergency",  # 暴風雪特別警報
    "33": "emergency",  # 大雨特別警報
    "35": "emergency",  # 暴風特別警報
    "36": "emergency",  # 大雪特別警報
    "37": "emergency",  # 波浪特別警報
    "38": "emergency",  # 高潮特別警報
    # 警報（warning）
    "02": "warning",    # 暴風雪警報
    "03": "warning",    # 大雨警報
    "04": "warning",    # 洪水警報
    "05": "warning",    # 暴風警報
    "06": "warning",    # 大雪警報
    "07": "warning",    # 波浪警報
    "08": "warning",    # 高潮警報
    # 注意報（advisory）
    "10": "advisory",   # 大雨注意報
    "12": "advisory",   # 大雪注意報
    "13": "advisory",   # 風雪注意報
    "14": "advisory",   # 雷注意報
    "15": "advisory",   # 強風注意報
    "16": "advisory",   # 波浪注意報
    "17": "advisory",   # 融雪注意報
    "18": "advisory",   # 洪水注意報
    "19": "advisory",   # 高潮注意報
    "20": "advisory",   # 濃霧注意報（実データ確認済み: code 20 = 濃霧注意報）
    "21": "advisory",   # 乾燥注意報
    "22": "advisory",   # なだれ注意報
    "23": "advisory",   # 低温注意報
    "24": "advisory",   # 霜注意報
    "25": "advisory",   # 着氷注意報
    "26": "advisory",   # 着雪注意報
    "27": "advisory",   # その他の注意報
}

# 警報種別コード → 名称（JMA仕様変更で warnings[].name が廃止された場合のフォールバック）
# 仕様変更時は _CODE_SEVERITY と同時に更新すること
_CODE_NAME: dict[str, str] = {
    # 特別警報
    "32": "暴風雪特別警報",
    "33": "大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "高潮特別警報",
    # 警報
    "02": "暴風雪警報",
    "03": "大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "高潮警報",
    # 注意報
    "10": "大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "高潮注意報",
    "20": "濃霧注意報",   # 実データ確認済み（静岡・愛知・福岡・東京など）
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
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

    - city_name が None または keywords_map が空 → 全件返す（府県全体として扱う）
    - city_name が keywords_map に一致しない → 全件返す（対応区域不明）
    - city_name の区域が特定できた → その区域の items のみ返す（ゼロ件でも全件返さない）
      これにより「区域が特定できたが警報なし」と「区域不明」を区別する。
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

    # 区域が特定できなければ全件返す（府県全体として扱う）
    if not matched_areas:
        return items

    # 区域が特定できた場合はその区域の警報のみ返す（ゼロ件でも全件フォールバックしない）
    return [i for i in items if i.area_name in matched_areas]


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


def _make_alert_item(
    area_code: str,
    area_name: str,
    warn_code: str,
    status_raw: str,
    updated_at: str,
    pref_name: str,
) -> Optional[WeatherAlertItem]:
    """(area_code, warn_code, status) から WeatherAlertItem を生成する共通ヘルパー。"""
    name = _CODE_NAME.get(warn_code) or ""
    severity = _normalize_severity(warn_code, name)

    if "特別警報" in name:
        level = "特別警報"
    elif "警報" in name:
        level = "警報"
    elif "注意報" in name:
        level = "注意報"
    elif severity == "emergency":
        level = "特別警報"
    elif severity == "warning":
        level = "警報"
    elif severity == "advisory":
        level = "注意報"
    else:
        level = "不明"

    display_name = name or f"警報・注意報（コード{warn_code}）"
    headline = f"{display_name} {status_raw}".strip()

    return WeatherAlertItem(
        area_code=area_code or None,
        area_name=area_name or pref_name,
        source_area_type=None,
        kind=display_name,
        level=level,
        severity=severity,
        status=status_raw,
        headline=headline,
        issued_at=updated_at,
        updated_at=updated_at,
        source="jma",
        raw_code=warn_code,
    )


def _parse_r8_payload(
    payload: list,
    pref_name: str,
) -> list[WeatherAlertItem]:
    """
    r8 フォーマット（root: array）の JMA 警報 JSON を WeatherAlertItem リストに変換する。

    各レコードは dataTypeCode ごとに現象種別が分かれており、全レコードをマージして
    発令中の警報・注意報一覧を作る。同一 (areaCode, warnCode) に複数レコードが存在する
    場合は reportDatetime が新しい方の status を採用する。
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    # (area_code, warn_code) → (status, report_datetime)
    latest: dict[tuple[str, str], tuple[str, str]] = {}

    for record in payload:
        if not isinstance(record, dict):
            continue
        report_dt = record.get("reportDatetime") or now_iso
        w = record.get("warning")
        if not isinstance(w, dict):
            continue

        for key in ("class10Items", "class20Items"):
            for area_item in w.get(key, []):
                if not isinstance(area_item, dict):
                    continue
                area_code = str(area_item.get("areaCode", ""))
                for kind in area_item.get("kinds", []):
                    if not isinstance(kind, dict):
                        continue
                    warn_code = str(kind.get("code", "")) or None
                    if not warn_code:
                        continue
                    status_raw = str(kind.get("status", ""))
                    pair = (area_code, warn_code)
                    existing = latest.get(pair)
                    # より新しい reportDatetime を優先
                    if existing is None or report_dt >= existing[1]:
                        latest[pair] = (status_raw, report_dt)

    items: list[WeatherAlertItem] = []
    for (area_code, warn_code), (status_raw, report_dt) in latest.items():
        if status_raw in ("解除", "発表警報・注意報はなし"):
            continue
        area_name = _AREA_CODE_NAME.get(area_code) or pref_name
        item = _make_alert_item(area_code, area_name, warn_code, status_raw, report_dt, pref_name)
        if item:
            items.append(item)
    return items


def _parse_legacy_payload(
    payload: dict,
    pref_name: str,
    reported_at: Optional[str],
) -> list[WeatherAlertItem]:
    """
    旧フォーマット（root: object, areaTypes[]）の JMA 警報 JSON を変換する。
    r8 URL が失敗した場合のフォールバック用。
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    report_dt = _safe_report_datetime(payload)
    updated_at = report_dt or reported_at or now_iso
    items: list[WeatherAlertItem] = []

    area_types = payload.get("areaTypes")
    if not isinstance(area_types, list):
        return []

    for at in area_types:
        if not isinstance(at, dict):
            continue
        areas = at.get("areas")
        if not isinstance(areas, list):
            continue
        for area in areas:
            if not isinstance(area, dict):
                continue
            area_code_raw = str(area.get("code", ""))
            area_name = area.get("name") or _AREA_CODE_NAME.get(area_code_raw) or pref_name
            for w in _extract_warnings(area):
                if not isinstance(w, dict):
                    continue
                try:
                    raw_code = str(w.get("code", "")) or None
                    name = w.get("name") or (raw_code and _CODE_NAME.get(raw_code)) or ""
                    status_raw = str(w.get("status", ""))
                    if not name and not raw_code:
                        continue
                    if status_raw in ("解除", "発表警報・注意報はなし"):
                        continue
                    if raw_code:
                        item = _make_alert_item(area_code_raw, area_name, raw_code, status_raw, updated_at, pref_name)
                        if item:
                            items.append(item)
                except Exception as exc:
                    logger.warning("jma_weather_adapter: legacy item parse error area=%s: %s", area_name, exc)
    return items


def fetch_warnings_for_pref(
    pref_code: str,
    pref_name: str,
    reported_at: Optional[str] = None,
) -> list[WeatherAlertItem]:
    """
    指定都道府県の JMA 警報・注意報を取得して WeatherAlertItem リストに変換する。

    r8 URL（公式ページが使用する最新 URL）を優先して取得する。
    r8 が失敗した場合は旧 URL にフォールバックする。
    Returns: アクティブな警報・注意報のリスト。エラー時は例外を再送出。
    """
    r8_url = _JMA_WARNING_BASE.format(pref_code=pref_code)
    legacy_url = _JMA_WARNING_LEGACY_BASE.format(pref_code=pref_code)

    # --- r8 URL（メイン）---
    try:
        raw = _http_get(r8_url)
        payload = json.loads(raw)
        if isinstance(payload, list):
            items = _parse_r8_payload(payload, pref_name)
            logger.info("jma_weather_adapter: r8 pref=%s items=%d", pref_code, len(items))
            return items
        # list でない場合は旧形式として下のフォールバックへ
        logger.warning("jma_weather_adapter: r8 returned non-list pref=%s, falling back", pref_code)
    except Exception as exc:
        logger.warning("jma_weather_adapter: r8 fetch failed pref=%s: %s — falling back to legacy", pref_code, exc)

    # --- 旧 URL（フォールバック）---
    try:
        raw = _http_get(legacy_url)
        payload = json.loads(raw)
        items = _parse_legacy_payload(payload, pref_name, reported_at)
        logger.info("jma_weather_adapter: legacy pref=%s items=%d", pref_code, len(items))
        return items
    except Exception as exc:
        logger.warning("jma_weather_adapter: legacy fetch also failed pref=%s: %s", pref_code, exc)
        raise


def _safe_report_datetime(payload: dict) -> Optional[str]:
    for key in ("reportDatetime", "targetDateTime", "report_datetime"):
        val = payload.get(key)
        if val and isinstance(val, str):
            return val
    return None
