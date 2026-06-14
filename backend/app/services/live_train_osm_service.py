"""
live_train_osm_service.py — /live 鉄道路線オーバーレイ用 OSM 取得サービス

表示範囲 bbox の鉄道路線だけを返す。Overpass が利用できない場合でも
主要路線の軽量フォールバックを返し、/live の操作性を保つ。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Tuple
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_CACHE_TTL = 300.0
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


_FALLBACK_ELEMENTS: List[Dict[str, Any]] = [
    {
        "type": "way",
        "id": 9001001,
        "tags": {"railway": "subway", "name": "銀座線", "name:en": "Ginza Line"},
        "geometry": [
            {"lat": 35.7100, "lon": 139.8107},
            {"lat": 35.6938, "lon": 139.7831},
            {"lat": 35.6812, "lon": 139.7671},
            {"lat": 35.6719, "lon": 139.7639},
            {"lat": 35.6580, "lon": 139.7016},
        ],
    },
    {
        "type": "way",
        "id": 9001002,
        "tags": {"railway": "rail", "name": "山手線", "name:en": "Yamanote Line"},
        "geometry": [
            {"lat": 35.6812, "lon": 139.7671},
            {"lat": 35.7295, "lon": 139.7109},
            {"lat": 35.6909, "lon": 139.7003},
            {"lat": 35.6285, "lon": 139.7388},
            {"lat": 35.6812, "lon": 139.7671},
        ],
    },
    {
        "type": "way",
        "id": 9001003,
        "tags": {"railway": "rail", "name": "中央線", "name:en": "Chuo Line"},
        "geometry": [
            {"lat": 35.7060, "lon": 139.6657},
            {"lat": 35.7006, "lon": 139.4805},
            {"lat": 35.6840, "lon": 139.7746},
        ],
    },
    {
        "type": "way",
        "id": 9001004,
        "tags": {"railway": "rail", "name": "小田急小田原線", "name:en": "Odakyu Odawara Line"},
        "geometry": [
            {"lat": 35.6909, "lon": 139.7003},
            {"lat": 35.6310, "lon": 139.5860},
            {"lat": 35.3293, "lon": 139.1550},
        ],
    },
    {
        "type": "way",
        "id": 9001005,
        "tags": {"railway": "rail", "name": "京王線", "name:en": "Keio Line"},
        "geometry": [
            {"lat": 35.6909, "lon": 139.7003},
            {"lat": 35.6689, "lon": 139.4776},
            {"lat": 35.6550, "lon": 139.3389},
        ],
    },
]


def _cache_key(south: float, west: float, north: float, east: float) -> str:
    return ",".join(f"{v:.2f}" for v in (south, west, north, east))


def _intersects_bbox(element: Dict[str, Any], south: float, west: float, north: float, east: float) -> bool:
    for node in element.get("geometry", []):
        lat = node.get("lat")
        lon = node.get("lon")
        if lat is None or lon is None:
            continue
        if south <= float(lat) <= north and west <= float(lon) <= east:
            return True
    return False


def _fallback_response(south: float, west: float, north: float, east: float, reason: str) -> Dict[str, Any]:
    elements = [el for el in _FALLBACK_ELEMENTS if _intersects_bbox(el, south, west, north, east)]
    return {
        "version": 0.6,
        "generator": "OnHighGround2 live_train_osm fallback",
        "source": "fallback",
        "fallback": True,
        "reason": reason,
        "elements": elements,
    }


def _fetch_overpass(south: float, west: float, north: float, east: float) -> Dict[str, Any]:
    query = (
        f"[out:json][timeout:25][bbox:{south:.4f},{west:.4f},{north:.4f},{east:.4f}];"
        '(way["railway"~"^(rail|subway|light_rail|monorail)$"][!"service"];);'
        "out geom;"
    )
    body = urlencode({"data": query}).encode("utf-8")
    req = Request(
        _OVERPASS_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "OnHighGround2/live-railway-overlay",
        },
        method="POST",
    )
    with urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    data["source"] = "overpass"
    data["fallback"] = False
    return data


def get_osm_railways(south: float, west: float, north: float, east: float) -> Dict[str, Any]:
    if south >= north or west >= east:
        return _fallback_response(south, west, north, east, "invalid_bbox")

    # フロントは zoom>=8 で呼ぶが、API側でも大きすぎる範囲を抑止する。
    if (north - south) > 4.0 or (east - west) > 4.0:
        return _fallback_response(south, west, north, east, "bbox_too_large")

    key = _cache_key(south, west, north, east)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        result = dict(cached[1])
        result["cached"] = True
        return result

    try:
        result = _fetch_overpass(south, west, north, east)
        result["cached"] = False
    except (URLError, TimeoutError, json.JSONDecodeError, Exception) as exc:
        logger.warning("live train osm: overpass unavailable: %s", exc)
        result = _fallback_response(south, west, north, east, "overpass_unavailable")
        result["cached"] = False

    _cache[key] = (now, result)
    logger.info(
        "live train osm: source=%s fallback=%s elements=%d",
        result.get("source"),
        result.get("fallback"),
        len(result.get("elements", [])),
    )
    return result
