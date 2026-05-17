"""
weather_route_risk_service.py — ルート上の気象リスク分析 (Phase2-D)

POST /api/weather/risk/route のバックエンド実装。

ルート座標列をサンプリングし、各サンプル点で
降水強度（JMAタイル）× ハザードゾーン判定を実行。
ルート全体の気象リスクレベルと避難向けサマリーを返す。

重要方針:
  - サンプリング ~150m 間隔、最大12点（ブルートフォース禁止）
  - current_segment_index 未満の座標はスキップ（進行済み区間除外）
  - ルート全体サマリーは最高リスクセグメントを使用
  - unknown を none に倒さない（false-safe 防止）
  - ハザードサービス未起動時でも API を落とさない
"""
import hashlib
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from app.services.weather_alert_service import get_precipitation_summary
from app.services.weather_risk_context_service import (
    _fetch_hazard_assessment,
    _build_hazard_flags,
    _build_weather_summary,
    _build_combined_risks,
    _compute_risk_level,
)

logger = logging.getLogger(__name__)

_ROUTE_CACHE: dict = {}
_ROUTE_TTL         = 45.0

_SAMPLE_INTERVAL_M = 150
_MAX_SAMPLES       = 12

_RISK_RANK = {"emergency": 4, "warning": 3, "advisory": 2, "unknown": 1, "none": 0}
_RANK_LEVEL = {4: "emergency", 3: "warning", 2: "advisory", 1: "unknown", 0: "none"}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _normalize_coords(coordinates: list) -> list[tuple[float, float]]:
    """[[lon, lat], ...] → [(lat, lon), ...]"""
    result = []
    for c in coordinates:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            result.append((float(c[1]), float(c[0])))
        elif isinstance(c, dict):
            result.append((float(c.get("lat", 0)), float(c.get("lon", c.get("lng", 0)))))
    return result


def _sample_route(
    coords: list[tuple[float, float]],
    current_idx: int,
    interval_m: float = _SAMPLE_INTERVAL_M,
    max_samples: int = _MAX_SAMPLES,
) -> list[tuple[float, float]]:
    """current_idx 以降の座標から等間隔サンプリングしてリストを返す。"""
    if not coords:
        return []
    start     = max(0, current_idx)
    remaining = coords[start:]
    if not remaining:
        return []

    samples        = [remaining[0]]
    accum          = 0.0
    next_threshold = interval_m

    for i in range(1, len(remaining)):
        accum += _haversine_m(*remaining[i - 1], *remaining[i])
        if accum >= next_threshold:
            samples.append(remaining[i])
            next_threshold += interval_m
            if len(samples) >= max_samples:
                break

    return samples


def _route_cache_key(coords: list[tuple[float, float]], current_idx: int) -> str:
    n      = len(coords)
    pts    = [coords[0], coords[n // 2], coords[-1]] if n >= 2 else [coords[0]]
    p_str  = "_".join(f"{p[0]:.4f},{p[1]:.4f}" for p in pts)
    bucket = int(time.time() // 45)
    return hashlib.md5(f"{p_str}_{current_idx}_{bucket}".encode()).hexdigest()[:16]


def get_route_risk(coordinates: list, current_segment_index: int = 0) -> dict:
    """ルートの気象リスクを返す（TTLキャッシュ付き）。"""
    coords  = _normalize_coords(coordinates)
    now_iso = datetime.now(timezone.utc).isoformat()
    if not coords:
        return _empty_response(now_iso)

    cache_key = _route_cache_key(coords, current_segment_index)
    now_mono  = time.monotonic()

    cached = _ROUTE_CACHE.get(cache_key)
    if cached is not None:
        data, fetched_at = cached
        if now_mono - fetched_at < _ROUTE_TTL:
            return data

    try:
        data = _build_route_risk(coords, current_segment_index, now_iso)
    except Exception as exc:
        logger.warning("get_route_risk failed: %s", exc)
        data = _unavailable_response(now_iso)

    _ROUTE_CACHE[cache_key] = (data, now_mono)
    return data


def _empty_response(now_iso: str) -> dict:
    return {
        "status": "ok", "risk_level": "none",
        "segments": [], "summary": {"headline": None, "message": None},
        "updated_at": now_iso,
    }


def _unavailable_response(now_iso: str) -> dict:
    return {
        "status": "unavailable", "risk_level": "unknown",
        "segments": [], "summary": {"headline": None, "message": None},
        "updated_at": now_iso,
    }


def _assess_point(lat: float, lon: float) -> dict:
    """1点の降水＋ハザード複合リスクを返す。"""
    try:
        precip_data = get_precipitation_summary(lat, lon)
    except Exception as exc:
        logger.warning("route risk: precip failed lat=%s lon=%s: %s", lat, lon, exc)
        precip_data = {"status": "unavailable", "severity": "unknown", "current": {}, "forecast": []}

    hazard_raw = _fetch_hazard_assessment(lat, lon)
    hazards    = _build_hazard_flags(hazard_raw)
    weather    = _build_weather_summary(
        {"status": "ok", "severity": "none", "alerts": []},
        precip_data,
    )
    combined   = _build_combined_risks(weather, hazards)
    risk_level = _compute_risk_level(weather, hazards, combined)

    return {
        "lat": lat, "lon": lon,
        "risk_level": risk_level,
        "weather":  weather,
        "hazards":  hazards,
        "combined": combined,
    }


def _build_route_summary(segments: list) -> dict:
    """セグメント一覧からルート全体のサマリーを構築する。"""
    if not segments:
        return {"headline": None, "message": None}

    worst = max(segments, key=lambda s: _RISK_RANK.get(s["risk_level"], 0))
    level = worst["risk_level"]

    if level in ("emergency", "warning", "advisory"):
        combined = worst.get("combined") or []
        if combined:
            return {"headline": combined[0]["headline"], "message": combined[0]["message"]}

    _defaults = {
        "emergency": ("進行方向で危険な降水を検出",  "命を守る行動をとってください"),
        "warning":   ("進行方向で強雨リスク",        "安全な場所への移動を検討してください"),
        "advisory":  ("進行方向に雨域接近",           None),
    }
    if level in _defaults:
        return {"headline": _defaults[level][0], "message": _defaults[level][1]}
    return {"headline": None, "message": None}


def _build_route_risk(
    coords: list[tuple[float, float]],
    current_idx: int,
    now_iso: str,
) -> dict:
    sample_points = _sample_route(coords, current_idx)
    if not sample_points:
        return _empty_response(now_iso)

    segments: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_assess_point, lat, lon): (lat, lon)
                   for lat, lon in sample_points}
        for future in as_completed(futures, timeout=20):
            try:
                segments.append(future.result())
            except Exception as exc:
                lat, lon = futures[future]
                logger.warning("route risk: point failed lat=%s lon=%s: %s", lat, lon, exc)

    if not segments:
        return _unavailable_response(now_iso)

    max_rank   = max((_RISK_RANK.get(s["risk_level"], 0) for s in segments), default=0)
    risk_level = _RANK_LEVEL.get(max_rank, "none")
    summary    = _build_route_summary(segments)

    return {
        "status": "ok",
        "risk_level": risk_level,
        "segments": [
            {"lat": s["lat"], "lon": s["lon"],
             "risk_level": s["risk_level"],
             "combined": s.get("combined", [])}
            for s in segments
        ],
        "summary":    summary,
        "updated_at": now_iso,
    }
