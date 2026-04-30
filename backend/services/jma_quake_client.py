"""
jma_quake_client.py — 気象庁Web地震情報JSONクライアント（Phase2C）

データソース（非公式JSON・将来 XML または P2P API へ差し替え可能）:
  list: https://www.jma.go.jp/bosai/quake/data/list.json
  item: https://www.jma.go.jp/bosai/quake/data/{filename}

キャッシュ:
  list.json:  60秒
  個別JSON: 300秒

JSON実構造（VXSE5k「震源・震度情報」）:
  Head.ReportDateTime        → report_time
  Head.Headline.Text         → headline
  Body.Earthquake.OriginTime → origin_time
  Body.Earthquake.Magnitude  → magnitude
  Body.Earthquake.Hypocenter.Area.Name       → hypocenter_name
  Body.Earthquake.Hypocenter.Area.Coordinate → "+lat+lon+depth_m/"
  Body.Intensity.Observation.MaxInt  → max_intensity
  Body.Intensity.Observation.Pref[]  → intensity_areas
  Body.Comments.ForecastComment.Text → domestic_tsunami (テキスト判定)

list.json エントリ（個別JSON取得不要の主要フィールド）:
  anm  → hypocenter_name
  cod  → coordinate "+lat+lon+depth_m/"
  mag  → magnitude
  maxi → max_intensity (直接文字列: "1","2","3","4","5-","5+","6-","6+","7")
  at   → origin_time
  rdt  → report_time
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

# list.json / 個別JSON の MaxInt フィールド（直接文字列コード）→ 震度ラベル
# list.json の maxi と Body.Intensity.Observation.MaxInt は同じ形式
_INTENSITY_LABEL_MAP: Dict[str, str] = {
    "1":  "1",
    "2":  "2",
    "3":  "3",
    "4":  "4",
    "5-": "5弱",
    "5+": "5強",
    "6-": "6弱",
    "6+": "6強",
    "7":  "7",
    # 日本語表記も念のため
    "5弱": "5弱",
    "5強": "5強",
    "6弱": "6弱",
    "6強": "6強",
    "-1": "1未満",
    "0":  "なし",
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


def _intensity_label(value: Any) -> str:
    """震度文字列コード → 表示用震度ラベル。不明は "unknown"。"""
    if value is None:
        return "unknown"
    s = str(value).strip()
    if not s:
        return "unknown"
    return _INTENSITY_LABEL_MAP.get(s, "unknown")


_ISO6709_PAT = re.compile(
    r"^([+-]\d+\.?\d*)([+-]\d+\.?\d*)([+-]\d+\.?\d*)?"
)


def _parse_coordinate(coord: Any) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """
    ISO 6709 座標文字列をパースして (lat, lon, depth_km) を返す。

    JMA形式: "+36.6+137.9-10000/" (第3成分は深さ、単位はメートル)
    深さは絶対値を1000で割ってkmに変換する。
    不明・sentinel値は None。
    """
    if isinstance(coord, dict):
        coord = coord.get("@value") or coord.get("value") or ""
    if not isinstance(coord, str):
        return None, None, None
    coord = coord.strip().rstrip("/")
    if not coord:
        return None, None, None
    m = _ISO6709_PAT.match(coord)
    if not m:
        return None, None, None
    try:
        lat = float(m.group(1))
        lon = float(m.group(2))
        depth_raw = m.group(3)
        # 深さは m 単位 → km 変換（JMA 標準）
        depth_km: Optional[int] = None
        if depth_raw:
            depth_m = abs(int(float(depth_raw)))
            depth_km = depth_m // 1000
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return None, None, None
        if lat == 0.0 and lon == 0.0:
            return None, None, None
        return lat, lon, depth_km
    except (ValueError, TypeError):
        return None, None, None


def _parse_float(value: Any) -> Optional[float]:
    """文字列または数値を float へ変換。変換不能は None。"""
    if value is None:
        return None
    try:
        f = float(value)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _tsunami_from_comment(comments: Dict[str, Any]) -> str:
    """
    Body.Comments.ForecastComment からテキスト判定で津波情報を返す。
    JMA ForecastComment.Code の例:
      0215 → 津波の心配なし
      0201 → 注意報/警報レベル（テキストで細分判定）
    """
    forecast = comments.get("ForecastComment") or {}
    text = str(forecast.get("Text") or "")
    if "津波の心配はありません" in text or "津波なし" in text:
        return "なし"
    if "若干の海面変動" in text:
        return "若干の海面変動あり"
    if "津波警報" in text:
        return "津波警報"
    if "津波注意報" in text:
        return "津波注意報"
    if text:
        return "確認中"
    return "不明"


def _normalize_item(
    entry: Dict[str, Any],
    item_json: Optional[Any],
) -> Dict[str, Any]:
    """
    list.json 1エントリ + 個別JSON から正規化イベントを生成する。

    list.json のフィールド（anm/cod/mag/maxi）を一次ソースとして使用し、
    個別JSON（Body.Earthquake / Body.Intensity.Observation）で補完・精緻化する。
    """
    json_file = entry.get("json", "")
    event_id = json_file.split("/")[-1].replace(".json", "")
    title = entry.get("ttl") or ""

    # ── list.json から基本情報を取得 ────────────────────────────────────────
    report_time = _parse_iso(entry.get("rdt") or entry.get("at"))
    origin_time = _parse_iso(entry.get("at")) or report_time

    # 震源名: list.json anm フィールド
    hypocenter_name = str(entry.get("anm") or "不明").strip() or "不明"

    # 座標: list.json cod フィールド (+lat+lon+depth_m/)
    lat, lon, depth_km = _parse_coordinate(entry.get("cod"))

    # マグニチュード: list.json mag フィールド
    magnitude = _parse_float(entry.get("mag"))

    # 最大震度: list.json maxi フィールド（直接文字列 "1"〜"7", "5-", "5+" 等）
    max_intensity = _intensity_label(entry.get("maxi"))

    domestic_tsunami = "不明"
    headline = ""
    intensity_areas: List[Dict[str, str]] = []

    # ── 個別JSON による補完・精緻化 ──────────────────────────────────────────
    if item_json is not None:
        try:
            root = item_json[0] if isinstance(item_json, list) else item_json
            head = root.get("Head") or {}
            body = root.get("Body") or {}

            # headline: Head.Headline.Text
            head_headline = head.get("Headline") or {}
            headline = str(head_headline.get("Text") or "").strip()

            # report_time: Head.ReportDateTime
            report_time = _parse_iso(head.get("ReportDateTime")) or report_time

            # Earthquake ブロック
            eq = body.get("Earthquake") or {}

            # origin_time: Body.Earthquake.OriginTime
            origin_time = _parse_iso(eq.get("OriginTime")) or origin_time

            # 震源エリア: Body.Earthquake.Hypocenter.Area
            hypo_area = (eq.get("Hypocenter") or {}).get("Area") or {}

            if hypo_area.get("Name"):
                hypocenter_name = str(hypo_area["Name"]).strip() or hypocenter_name

            # 座標の精緻化（個別JSON の方が精度が高い場合あり）
            coord_str = hypo_area.get("Coordinate")
            if coord_str:
                lat_new, lon_new, depth_new = _parse_coordinate(coord_str)
                if lat_new is not None:
                    lat, lon, depth_km = lat_new, lon_new, depth_new

            # magnitude: Body.Earthquake.Magnitude
            mag_from_item = _parse_float(eq.get("Magnitude"))
            if mag_from_item is not None:
                magnitude = mag_from_item

            # Intensity.Observation ブロック
            obs = (body.get("Intensity") or {}).get("Observation") or {}

            # max_intensity: Body.Intensity.Observation.MaxInt
            if obs.get("MaxInt"):
                max_intensity = _intensity_label(obs["MaxInt"])

            # intensity_areas: Body.Intensity.Observation.Pref[].Area[]
            prefs = obs.get("Pref") or []
            if isinstance(prefs, dict):
                prefs = [prefs]
            for pref in prefs:
                pref_name = str(pref.get("Name") or "").strip()
                pref_int = _intensity_label(pref.get("MaxInt"))
                intensity_areas.append({"name": pref_name, "intensity": pref_int})
                areas = pref.get("Area") or []
                if isinstance(areas, dict):
                    areas = [areas]
                for area in areas:
                    area_name = str(area.get("Name") or "").strip()
                    area_int = _intensity_label(area.get("MaxInt"))
                    intensity_areas.append({"name": area_name, "intensity": area_int})

            # domestic_tsunami: Body.Comments.ForecastComment.Text 判定
            comments = body.get("Comments") or {}
            domestic_tsunami = _tsunami_from_comment(comments)

        except Exception as exc:
            logger.debug("jma_quake item parse error (event_id=%s): %s", event_id, exc)

    # intensity_areas フォールバック
    if not intensity_areas and max_intensity not in ("unknown", "なし", "1未満"):
        intensity_areas = [{"name": hypocenter_name, "intensity": max_intensity}]

    logger.info(
        "jma_quake event: event_id=%s hypocenter_name=%s lat=%s lon=%s magnitude=%s max_intensity=%s",
        event_id, hypocenter_name, lat, lon, magnitude, max_intensity,
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
