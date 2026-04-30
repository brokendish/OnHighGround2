"""
jma_quake_client.py — 気象庁Web地震情報JSONクライアント（Phase2C）

データソース（非公式JSON・将来 XML または P2P API へ差し替え可能）:
  list: https://www.jma.go.jp/bosai/quake/data/list.json
  item: https://www.jma.go.jp/bosai/quake/data/{filename}

キャッシュ:
  list.json:  60秒
  個別JSON: 300秒
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_JMA_BASE = "https://www.jma.go.jp/bosai/quake/data"
_LIST_URL = f"{_JMA_BASE}/list.json"
_LIST_TTL = 60
_ITEM_TTL = 300
_JST = timezone(timedelta(hours=9))

# list.json の maxi フィールド（整数コード）→ 震度ラベル
_MAXI_CODE_MAP: Dict[str, str] = {
    "10": "1", "20": "2", "30": "3", "40": "4",
    "45": "5弱", "50": "5強", "55": "6弱", "60": "6強", "70": "7",
}

# 個別JSON の MaxInt フィールド（文字列コード）→ 震度ラベル
_MAXINT_STR_MAP: Dict[str, str] = {
    "1": "1", "2": "2", "3": "3", "4": "4",
    "5-": "5弱", "5+": "5強", "6-": "6弱", "6+": "6強", "7": "7",
    "5弱": "5弱", "5強": "5強", "6弱": "6弱", "6強": "6強",
    "-1": "1未満", "0": "なし",
}

_TSUNAMI_MAP: Dict[str, str] = {
    "None": "なし",
    "Unknown": "不明",
    "Checking": "確認中",
    "NonEffective": "若干の海面変動あり",
    "Watch": "津波注意報",
    "Warning": "津波警報",
}

_list_cache: Optional[Dict[str, Any]] = None
_item_cache: Dict[str, Dict[str, Any]] = {}


def _now() -> float:
    return time.monotonic()


def _http_get(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "OnHighGround2/1.0 (+https://github.com/brokendish/OnHighGround2)",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_list_sync() -> List[Dict[str, Any]]:
    global _list_cache
    t = _now()
    if _list_cache and t - _list_cache["ts"] < _LIST_TTL:
        logger.info("jma_quake list.json cache hit")
        return _list_cache["data"]
    try:
        data = _http_get(_LIST_URL)
    except Exception as exc:
        logger.warning("jma_quake list.json fetch failed: %s", exc)
        return _list_cache["data"] if _list_cache else []
    if not isinstance(data, list):
        logger.warning("jma_quake list.json unexpected type: %s", type(data).__name__)
        return _list_cache["data"] if _list_cache else []
    _list_cache = {"data": data, "ts": t}
    logger.info("jma_quake list.json cache miss — fetched %d entries", len(data))
    return data


def _fetch_item_sync(filename: str) -> Optional[Dict[str, Any]]:
    t = _now()
    cached = _item_cache.get(filename)
    if cached and t - cached["ts"] < _ITEM_TTL:
        logger.debug("jma_quake item cache hit: %s", filename)
        return cached["data"]
    url = f"{_JMA_BASE}/{filename}"
    try:
        data = _http_get(url)
        _item_cache[filename] = {"data": data, "ts": t}
        logger.debug("jma_quake item cache miss: %s", filename)
        return data
    except Exception as exc:
        logger.warning("jma_quake item fetch failed (%s): %s", filename, exc)
        return None


def _parse_iso(s: Any) -> Optional[str]:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return s
    except ValueError:
        return None


def _maxi_code_label(code: Any) -> str:
    if code is None:
        return "unknown"
    return _MAXI_CODE_MAP.get(str(code), "unknown")


def _maxint_label(value: Any) -> str:
    if value is None:
        return "unknown"
    s = str(value).strip()
    return _MAXINT_STR_MAP.get(s, "unknown")


_ISO6709_PAT = re.compile(
    r"^([+-]\d+\.?\d*)([+-]\d+\.?\d*)([+-]\d+\.?\d*)?"
)


def _parse_coordinate(coord: Any) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """
    ISO 6709 座標文字列または dict をパースして (lat, lon, depth_km) を返す。
    不明・sentinel値は None。
    """
    if isinstance(coord, dict):
        coord = coord.get("@value") or coord.get("value") or ""
    if not isinstance(coord, str):
        return None, None, None
    coord = coord.strip().rstrip("/")
    m = _ISO6709_PAT.match(coord)
    if not m:
        return None, None, None
    try:
        lat = float(m.group(1))
        lon = float(m.group(2))
        depth_raw = m.group(3)
        depth_km = abs(int(float(depth_raw))) if depth_raw else None
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return None, None, None
        if lat == 0.0 and lon == 0.0:
            return None, None, None
        return lat, lon, depth_km
    except (ValueError, TypeError):
        return None, None, None


def _extract_scalar(value: Any) -> Any:
    """JMA JSON の "@value" ラッパーから値を取り出す。"""
    if isinstance(value, dict):
        return value.get("@value") or value.get("value") or value.get("$")
    return value


def _normalize_item(
    entry: Dict[str, Any],
    item_json: Optional[Any],
) -> Dict[str, Any]:
    """list.json 1エントリ + 個別JSON から正規化イベントを生成する。"""
    json_file = entry.get("json", "")
    event_id = json_file.split("/")[-1].replace(".json", "")
    title = entry.get("ttl") or ""
    report_time = _parse_iso(entry.get("at") or entry.get("rdt"))
    max_intensity = _maxi_code_label(entry.get("maxi"))

    origin_time: Optional[str] = report_time
    hypocenter_name = "不明"
    lat: Optional[float] = None
    lon: Optional[float] = None
    depth_km: Optional[int] = None
    magnitude: Optional[float] = None
    domestic_tsunami = "不明"
    headline = ""
    intensity_areas: List[Dict[str, str]] = []

    if item_json is not None:
        try:
            # 配列の場合は最初の要素を使う
            root = item_json[0] if isinstance(item_json, list) else item_json
            props = root.get("properties") or root

            headline = str(props.get("Headline") or "")
            domestic_tsunami = _TSUNAMI_MAP.get(
                str(props.get("Tsunami") or ""), "不明"
            )

            # report_time を個別JSONで上書き
            report_time = _parse_iso(props.get("AnnouncedTime") or props.get("ReportDatetime")) or report_time

            # 地震情報
            eq = props.get("Earthquake") or {}
            origin_time = _parse_iso(
                eq.get("OriginTime") or props.get("OriginTime")
            ) or origin_time

            hypo = eq.get("HypoCenter") or eq.get("Hypocenter") or {}
            hypocenter_name = str(_extract_scalar(hypo.get("Name")) or "不明")
            lat, lon, depth_km = _parse_coordinate(hypo.get("Coordinate"))

            mag_raw = _extract_scalar(hypo.get("Magnitude") or eq.get("Magnitude"))
            try:
                magnitude = float(mag_raw) if mag_raw is not None else None
            except (TypeError, ValueError):
                magnitude = None

            # 震度分布
            intensity_block = props.get("Intensity") or {}
            # MaxInt の上書き（個別JSONの方が詳細）
            item_maxint = intensity_block.get("MaxInt") or props.get("MaxInt")
            if item_maxint:
                max_intensity = _maxint_label(item_maxint)

            prefs = intensity_block.get("Prefs") or intensity_block.get("Pref") or []
            if isinstance(prefs, dict):
                prefs = [prefs]
            for pref in prefs:
                pref_name = str(_extract_scalar(pref.get("Name")) or "")
                pref_int = _maxint_label(pref.get("MaxInt"))
                intensity_areas.append({"name": pref_name, "intensity": pref_int})
                areas = pref.get("Areas") or pref.get("Area") or []
                if isinstance(areas, dict):
                    areas = [areas]
                for area in areas:
                    intensity_areas.append({
                        "name": str(_extract_scalar(area.get("Name")) or ""),
                        "intensity": _maxint_label(area.get("MaxInt")),
                    })

        except Exception as exc:
            logger.debug("jma_quake item parse error (event_id=%s): %s", event_id, exc)

    if not intensity_areas and max_intensity not in ("unknown", "なし"):
        intensity_areas = [{"name": hypocenter_name, "intensity": max_intensity}]

    logger.info(
        "jma_quake event: event_id=%s report_time=%s max_intensity=%s hypocenter_name=%s",
        event_id, report_time, max_intensity, hypocenter_name,
    )
    return {
        "event_id":         event_id,
        "title":            title,
        "report_time":      report_time,
        "origin_time":      origin_time,
        "hypocenter_name":  hypocenter_name,
        "lat":              lat,
        "lon":              lon,
        "depth_km":         depth_km,
        "magnitude":        magnitude,
        "max_intensity":    max_intensity,
        "domestic_tsunami": domestic_tsunami,
        "headline":         headline,
        "intensity_areas":  intensity_areas,
    }


async def fetch_recent_earthquakes(limit: int = 10) -> List[Dict[str, Any]]:
    """
    気象庁 list.json から直近 limit 件の地震情報を正規化して返す。

    list.json は 60 秒キャッシュ、個別 JSON は 300 秒キャッシュ。
    取得失敗時は空リストを返す（例外を外に出さない）。
    """
    limit = max(1, min(limit, 30))
    try:
        raw_list = await asyncio.to_thread(_fetch_list_sync)
    except Exception as exc:
        logger.warning("jma_quake fetch_recent_earthquakes: list fetch error: %s", exc)
        return []
    if not raw_list:
        return []

    candidates = [e for e in raw_list if isinstance(e, dict)][:limit * 2]

    # 個別 JSON を並列取得
    async def _get_item(entry: Dict[str, Any]) -> Optional[Any]:
        json_file = entry.get("json")
        if not json_file:
            return None
        try:
            return await asyncio.to_thread(_fetch_item_sync, json_file)
        except Exception as exc:
            logger.debug("jma_quake item fetch error (%s): %s", json_file, exc)
            return None

    item_jsons = await asyncio.gather(*[_get_item(e) for e in candidates])

    results: List[Dict[str, Any]] = []
    for entry, item_json in zip(candidates, item_jsons):
        if len(results) >= limit:
            break
        try:
            results.append(_normalize_item(entry, item_json))
        except Exception as exc:
            logger.warning(
                "jma_quake normalize error (%s): %s", entry.get("json"), exc
            )
    return results
