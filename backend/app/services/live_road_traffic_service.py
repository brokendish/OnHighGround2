"""
live_road_traffic_service.py — 道路交通影響レイヤー サービス

国土交通省 交通量API（JARTIC提供）WFS 2.0.0 から道路交通量データを取得し、
正規化して返す。

API仕様（令和8年1月版）:
  エンドポイント : https://api.jartic-open-traffic.org/geoserver
  認証          : APIキー不要（オープンデータAPIとして公開）
  プロトコル    : WFS 2.0.0 GetFeature
  typeNames     : t_travospublic_measure_5m（5分値）
  観測タイミング: 観測から概ね20分後
  CQL注意       : 日本語フィールド名はダブルクォートで囲まない

環境変数:
  ROAD_TRAFFIC_API_BASE_URL - APIベースURL（デフォルト: https://api.jartic-open-traffic.org/geoserver）
  ROAD_TRAFFIC_USE_MOCK     - "true" のときモックデータを返す（テスト用）

キャッシュ:
  TTL 300秒（5分）。取得失敗時はstale cacheを返し、stale=Trueを付与する。

判定ロジック（MVP絶対値ベース）:
  5分値を優先。なければ1時間値/12で換算。
  閾値はすべて # MVP provisional でマーク。

ログ:
  live road traffic: items=X unavailable / stale / ok
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.models.live_road_traffic import (
    SEVERITY,
    STATUS_HIGH,
    STATUS_LABEL,
    STATUS_LOW,
    STATUS_NORMAL,
    STATUS_UNAVAILABLE,
    STATUS_UNKNOWN,
    STATUS_VERY_HIGH,
    STATUS_VERY_LOW,
    RoadTrafficItem,
)

logger = logging.getLogger(__name__)

_JST       = timezone(timedelta(hours=9))
_CACHE_TTL = 300.0  # 秒（5分）

_cache:    Optional[Dict[str, Any]] = None
_cache_at: float = 0.0


# ── 設定 ──────────────────────────────────────────────────────────────────────

def _base_url() -> str:
    return os.getenv("ROAD_TRAFFIC_API_BASE_URL", "https://api.jartic-open-traffic.org/geoserver")


def _use_mock() -> bool:
    return os.getenv("ROAD_TRAFFIC_USE_MOCK", "").lower() == "true"


# ── 交通量閾値判定 ─────────────────────────────────────────────────────────────

def classify_volume(volume_5min: Optional[int], volume_1h: Optional[int]) -> str:
    """
    5分値または1時間値から交通状況ステータスに分類する。

    優先: volume_5min。なければ volume_1h を使用。
    どちらもなければ STATUS_UNKNOWN。
    """
    v = volume_5min
    if v is None and volume_1h is not None:
        v = volume_1h // 12  # 1時間値を5分換算

    if v is None:
        return STATUS_UNKNOWN

    # MVP provisional: 絶対値ベース閾値（将来は平常時比較に置き換え）
    if v >= 150:   # MVP provisional
        return STATUS_VERY_HIGH
    if v >= 80:    # MVP provisional
        return STATUS_HIGH
    if v <= 3:     # MVP provisional
        return STATUS_VERY_LOW
    if v <= 15:    # MVP provisional
        return STATUS_LOW
    return STATUS_NORMAL


# ── モックデータ ───────────────────────────────────────────────────────────────

def _mock_items() -> List[RoadTrafficItem]:
    """テスト用モックデータ。実APIが利用できない場合にフォールバックとして使用。"""
    now = datetime.now(_JST).isoformat()
    return [
        RoadTrafficItem(
            station_id="T001",
            road_name="国道20号",
            direction="上り",
            lat=35.6812,
            lng=139.7671,
            volume_5min=180,
            volume_1h=2160,
            baseline_volume_1h=None,
            status=STATUS_VERY_HIGH,
            status_label=STATUS_LABEL[STATUS_VERY_HIGH],
            severity=SEVERITY[STATUS_VERY_HIGH],
            observed_at=now,
            source="国土交通省 交通量API（JARTIC提供）[mock]",
        ),
        RoadTrafficItem(
            station_id="T002",
            road_name="国道246号",
            direction="下り",
            lat=35.6503,
            lng=139.6941,
            volume_5min=90,
            volume_1h=1080,
            baseline_volume_1h=None,
            status=STATUS_HIGH,
            status_label=STATUS_LABEL[STATUS_HIGH],
            severity=SEVERITY[STATUS_HIGH],
            observed_at=now,
            source="国土交通省 交通量API（JARTIC提供）[mock]",
        ),
        RoadTrafficItem(
            station_id="T003",
            road_name="国道16号",
            direction="外回り",
            lat=35.7281,
            lng=139.8601,
            volume_5min=40,
            volume_1h=480,
            baseline_volume_1h=None,
            status=STATUS_NORMAL,
            status_label=STATUS_LABEL[STATUS_NORMAL],
            severity=SEVERITY[STATUS_NORMAL],
            observed_at=now,
            source="国土交通省 交通量API（JARTIC提供）[mock]",
        ),
        RoadTrafficItem(
            station_id="T004",
            road_name="首都高速3号渋谷線",
            direction="上り",
            lat=35.6597,
            lng=139.7024,
            volume_5min=10,
            volume_1h=120,
            baseline_volume_1h=None,
            status=STATUS_LOW,
            status_label=STATUS_LABEL[STATUS_LOW],
            severity=SEVERITY[STATUS_LOW],
            observed_at=now,
            source="国土交通省 交通量API（JARTIC提供）[mock]",
        ),
        RoadTrafficItem(
            station_id="T005",
            road_name="国道4号",
            direction="南行",
            lat=35.8103,
            lng=139.7951,
            volume_5min=2,
            volume_1h=24,
            baseline_volume_1h=None,
            status=STATUS_VERY_LOW,
            status_label=STATUS_LABEL[STATUS_VERY_LOW],
            severity=SEVERITY[STATUS_VERY_LOW],
            observed_at=now,
            source="国土交通省 交通量API（JARTIC提供）[mock]",
        ),
    ]


# ── JARTIC WFS API 取得 ────────────────────────────────────────────────────────

_DEFAULT_JAPAN_BBOX = "128.0,30.0,148.0,46.0"  # 日本全域おおよそ

_ROAD_TYPE_LABEL: Dict[str, str] = {
    "1": "高速道路",
    "3": "一般国道",
}


def _build_wfs_url(base_url: str, bbox_str: str) -> str:
    """現在時刻から25分前の時間コードを使ったJARTIC WFS GetFeature URLを構築する。"""
    from urllib.parse import urlencode

    # 観測から約20分後に提供 → 25分前でリクエスト
    now = datetime.now(_JST)
    lag = now - timedelta(minutes=25)
    lag = lag.replace(second=0, microsecond=0, minute=(lag.minute // 5) * 5)
    time_code = lag.strftime("%Y%m%d%H%M")

    parts = [float(x) for x in bbox_str.split(",")]
    min_lng, min_lat, max_lng, max_lat = parts

    cql = (
        f"道路種別='3' AND 時間コード={time_code} AND "
        f"BBOX(ジオメトリ,{min_lng},{min_lat},{max_lng},{max_lat},'EPSG:4326')"
    )
    qs = urlencode({
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": "t_travospublic_measure_5m",
        "srsName": "EPSG:4326",
        "outputFormat": "application/json",
        "exceptions": "application/json",
        "cql_filter": cql,
    })
    return f"{base_url}?{qs}"


def _observed_at_from_jartic(date_int: int, time_hhmm: int) -> str:
    """観測年月日(YYYYMMDD) + 時間帯(hhmm) → JST ISO8601文字列。"""
    try:
        dt = datetime.strptime(f"{date_int}{str(time_hhmm).zfill(4)}", "%Y%m%d%H%M")
        return dt.replace(tzinfo=_JST).isoformat()
    except Exception:
        return datetime.now(_JST).isoformat()


def _normalize_jartic_feature(feature: Dict[str, Any]) -> List[RoadTrafficItem]:
    """
    JARTIC WFS GeoJSON Feature 1件から上り・下り 最大2件の RoadTrafficItem を生成する。

    フィールドマッピング（API仕様書 令和8年1月版）:
      coordinates[0] = [lng, lat]   ← MultiPoint
      常時観測点コード               → station_id
      上り・小型+大型+判別不能交通量  → volume_5min（上り）
      下り・小型+大型+判別不能交通量  → volume_5min（下り）
      観測年月日 + 時間帯            → observed_at
      上り・欠測 == "1"              → スキップ
    """
    props  = feature.get("properties", {})
    geom   = feature.get("geometry", {})
    coords = geom.get("coordinates", [])
    if not coords:
        return []
    try:
        lng = float(coords[0][0])
        lat = float(coords[0][1])
    except (IndexError, TypeError, ValueError):
        return []

    station_code = props.get("常時観測点コード")
    if station_code is None:
        return []
    station_id = str(station_code)

    road_type  = str(props.get("道路種別", ""))
    road_label = _ROAD_TYPE_LABEL.get(road_type, "道路")
    road_name  = f"{road_label} #{station_id}"

    observed_at = _observed_at_from_jartic(
        int(props.get("観測年月日", 0)),
        int(props.get("時間帯", 0)),
    )

    items: List[RoadTrafficItem] = []
    for direction, prefix in [("上り", "上り"), ("下り", "下り")]:
        if props.get(f"{prefix}・欠測") == "1":
            continue
        small = props.get(f"{prefix}・小型交通量")
        large = props.get(f"{prefix}・大型交通量")
        unkn  = props.get(f"{prefix}・車種判別不能交通量")
        if small is None and large is None:
            continue
        v5     = sum(v for v in [small, large, unkn] if v is not None)
        status = classify_volume(v5, None)
        items.append(RoadTrafficItem(
            station_id=f"{station_id}_{prefix}",
            road_name=road_name,
            direction=direction,
            lat=lat,
            lng=lng,
            volume_5min=v5,
            volume_1h=None,
            baseline_volume_1h=None,
            status=status,
            status_label=STATUS_LABEL[status],
            severity=SEVERITY[status],
            observed_at=observed_at,
            source="国土交通省 交通量API（JARTIC提供）",
        ))
    return items


def _fetch_raw(base_url: str, bbox_str: str = _DEFAULT_JAPAN_BBOX) -> List[Dict[str, Any]]:
    """JARTIC WFS API から GeoJSON Feature リストを取得する（APIキー不要）。"""
    url = _build_wfs_url(base_url, bbox_str)
    headers = {"User-Agent": "OnHighGround2/live-road-traffic-layer"}
    req = Request(url, headers=headers)
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    return data.get("features", [])


def normalize_raw_item(raw: Dict[str, Any]) -> Optional[RoadTrafficItem]:
    """
    外部APIの生データ1件をRoadTrafficItemに正規化する。

    フィールドマッピング（APIベンダーに応じて調整）:
      station_id    ← id / station_id
      road_name     ← road_name / route_name
      direction     ← direction / dir
      lat           ← lat / latitude
      lng           ← lng / longitude
      volume_5min   ← volume_5min / vol5
      volume_1h     ← volume_1h / vol60
      observed_at   ← observed_at / datetime
    """
    station_id = str(raw.get("station_id") or raw.get("id") or "")
    if not station_id:
        return None

    road_name   = str(raw.get("road_name") or raw.get("route_name") or "不明")
    direction   = str(raw.get("direction") or raw.get("dir") or "")
    lat         = raw.get("lat") if raw.get("lat") is not None else raw.get("latitude")
    lng         = raw.get("lng") if raw.get("lng") is not None else raw.get("longitude")
    observed_at = str(raw.get("observed_at") or raw.get("datetime") or "")

    if lat is None or lng is None:
        return None

    # 0 は「欠損」ではなく very_low 判定に必要な有効値。
    v5  = raw.get("volume_5min") if raw.get("volume_5min") is not None else raw.get("vol5")
    v1h = raw.get("volume_1h") if raw.get("volume_1h") is not None else raw.get("vol60")
    volume_5min = int(v5)  if v5  is not None else None
    volume_1h   = int(v1h) if v1h is not None else None

    status = classify_volume(volume_5min, volume_1h)

    return RoadTrafficItem(
        station_id=station_id,
        road_name=road_name,
        direction=direction,
        lat=float(lat),
        lng=float(lng),
        volume_5min=volume_5min,
        volume_1h=volume_1h,
        baseline_volume_1h=None,
        status=status,
        status_label=STATUS_LABEL[status],
        severity=SEVERITY[status],
        observed_at=observed_at,
        source="国土交通省 交通量API（JARTIC提供）",
    )


# ── 都道府県フィルター ─────────────────────────────────────────────────────────

def _nearest_prefecture_from_latlon(lat: float, lon: float) -> Optional[str]:
    try:
        from app.services.jma_weather_adapter import _PREF_CENTROIDS  # type: ignore[import]
        best_pref: Optional[str] = None
        best_dist = float("inf")
        for _code, info in _PREF_CENTROIDS.items():
            pref_name, c_lat, c_lon = info
            dist = math.sqrt((lat - c_lat) ** 2 + (lon - c_lon) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_pref = pref_name
        return best_pref
    except Exception:
        return None


def _pref_centroid(prefecture: str) -> Optional[Tuple[float, float]]:
    try:
        from app.services.jma_weather_adapter import _PREF_CENTROIDS  # type: ignore[import]
        for _code, info in _PREF_CENTROIDS.items():
            if info[0] == prefecture:
                return float(info[1]), float(info[2])
        return None
    except Exception:
        return None


def _bbox_from_prefecture(prefecture: str, margin: float = 1.5) -> Optional[Tuple[float, float, float, float]]:
    """都道府県中心座標からおおよそのbboxを返す（緯度経度各±1.5度）。"""
    centroid = _pref_centroid(prefecture)
    if centroid is None:
        return None
    c_lat, c_lng = centroid
    return c_lat - margin, c_lng - margin, c_lat + margin, c_lng + margin


def _item_in_bbox(item: RoadTrafficItem, bbox: Tuple[float, float, float, float]) -> bool:
    min_lat, min_lng, max_lat, max_lng = bbox
    return min_lat <= item["lat"] <= max_lat and min_lng <= item["lng"] <= max_lng


def _item_near_latlon(item: RoadTrafficItem, lat: float, lng: float, radius: float = 1.0) -> bool:
    """半径 radius 度（≒100km）以内のアイテムを返す。"""
    dlat = item["lat"] - lat
    dlng = item["lng"] - lng
    return math.sqrt(dlat * dlat + dlng * dlng) <= radius


# ── 内部取得 ──────────────────────────────────────────────────────────────────

async def _fetch_all_items() -> List[RoadTrafficItem]:
    """JARTIC WFS API から全観測地点データを取得・正規化して返す。"""
    import asyncio

    if _use_mock():
        logger.info("live road traffic: mock mode")
        return _mock_items()

    base_url = _base_url()
    raw_features: List[Dict[str, Any]] = await asyncio.to_thread(_fetch_raw, base_url)

    items: List[RoadTrafficItem] = []
    for feature in raw_features:
        items.extend(_normalize_jartic_feature(feature))

    items.sort(key=lambda x: x["severity"], reverse=True)
    logger.info("live road traffic: items=%d", len(items))
    return items


# ── キャッシュ ────────────────────────────────────────────────────────────────

def _monotonic() -> float:
    return time.monotonic()


def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


# ── scope フィルター ──────────────────────────────────────────────────────────

def _apply_scope(
    result: Dict[str, Any],
    lat: Optional[float],
    lng: Optional[float],
    prefecture: Optional[str],
    bbox: Optional[str],
) -> Dict[str, Any]:
    """
    bbox > prefecture > lat/lng の優先順でフィルターを適用する。
    フィルターなし: 全データを返す。
    """
    all_items: List[RoadTrafficItem] = result.get("items", [])

    # bbox: "min_lng,min_lat,max_lng,max_lat"
    if bbox:
        try:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) == 4:
                min_lng, min_lat, max_lng, max_lat = parts
                bbox_t = (min_lat, min_lng, max_lat, max_lng)
                filtered = [it for it in all_items if _item_in_bbox(it, bbox_t)]
                result["scope"] = {"mode": "bbox", "bbox": bbox}
                result["items"] = filtered
                return result
        except ValueError:
            pass

    # prefecture
    if prefecture:
        bbox_pref = _bbox_from_prefecture(prefecture)
        if bbox_pref:
            filtered = [it for it in all_items if _item_in_bbox(it, bbox_pref)]
        else:
            filtered = all_items
        result["scope"] = {"mode": "prefecture", "prefecture": prefecture}
        result["items"] = filtered
        return result

    # lat/lng
    if lat is not None and lng is not None:
        pref = _nearest_prefecture_from_latlon(lat, lng)
        if pref:
            bbox_pref = _bbox_from_prefecture(pref)
            filtered = [it for it in all_items if _item_in_bbox(it, bbox_pref)] if bbox_pref else all_items
            result["scope"] = {"mode": "location", "prefecture": pref}
            result["items"] = filtered
        else:
            filtered = [it for it in all_items if _item_near_latlon(it, lat, lng)]
            result["scope"] = {"mode": "location"}
            result["items"] = filtered
        return result

    result["scope"] = {"mode": "all"}
    return result


# ── 公開API ───────────────────────────────────────────────────────────────────

async def build_road_traffic_summary(
    lat:        Optional[float] = None,
    lng:        Optional[float] = None,
    prefecture: Optional[str]   = None,
    bbox:       Optional[str]   = None,
) -> Dict[str, Any]:
    """
    道路交通影響サマリーを返す。

    Args:
        lat:        緯度（現在地周辺モード）
        lng:        経度（現在地周辺モード）
        prefecture: 都道府県名（例: "東京都"）
        bbox:       バウンディングボックス "min_lng,min_lat,max_lng,max_lat"

    Returns:
        {
            "status": "ok" | "unavailable",
            "stale": bool,
            "scope": {...},
            "updated_at": str,
            "items": [RoadTrafficItem, ...]
        }
    """
    global _cache, _cache_at

    now = _monotonic()

    # キャッシュヒット
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        cached = dict(_cache)
        cached["items"] = list(cached.get("items", []))
        return _apply_scope(cached, lat, lng, prefecture, bbox)

    # 新規取得
    try:
        items = await _fetch_all_items()
        result = {
            "status":     "ok",
            "stale":      False,
            "scope":      {},
            "updated_at": _now_jst(),
            "items":      items,
        }
        _cache    = result
        _cache_at = now
        logger.info("live road traffic: ok items=%d", len(items))
        return _apply_scope(dict(result), lat, lng, prefecture, bbox)

    except URLError as exc:
        logger.warning("live road traffic: 取得失敗 (URLError): %s", exc)
    except Exception as exc:
        logger.warning("live road traffic: 取得失敗: %s", exc)

    # stale cache
    if _cache is not None:
        stale = dict(_cache)
        stale["stale"] = True
        stale["message"] = "最新の道路交通量情報を取得できません。前回取得情報を表示しています"
        logger.info("live road traffic: stale items=%d", len(stale.get("items", [])))
        return _apply_scope(stale, lat, lng, prefecture, bbox)

    # キャッシュなし → unavailable
    logger.warning("live road traffic: unavailable (no cache)")
    result = {
        "status":     "unavailable",
        "stale":      False,
        "message":    "道路交通量情報を取得できません",
        "scope":      {},
        "updated_at": _now_jst(),
        "items":      [],
    }
    return _apply_scope(result, lat, lng, prefecture, bbox)
