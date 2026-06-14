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




def _cache_key(south: float, west: float, north: float, east: float) -> str:
    return ",".join(f"{v:.2f}" for v in (south, west, north, east))



def _fallback_response(reason: str) -> Dict[str, Any]:
    # Overpass 不到達時は空を返す。偽の路線形状は表示しない。
    return {
        "version": 0.6,
        "generator": "OnHighGround2 live_train_osm",
        "source": "unavailable",
        "fallback": True,
        "reason": reason,
        "elements": [],
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
        return _fallback_response("invalid_bbox")

    # フロントは zoom>=8 で呼ぶが、API側でも大きすぎる範囲を抑止する。
    if (north - south) > 4.0 or (east - west) > 4.0:
        return _fallback_response("bbox_too_large")

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
        result = _fallback_response("overpass_unavailable")
        result["cached"] = False

    _cache[key] = (now, result)
    logger.info(
        "live train osm: source=%s fallback=%s elements=%d",
        result.get("source"),
        result.get("fallback"),
        len(result.get("elements", [])),
    )
    return result
