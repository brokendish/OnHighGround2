"""
route_comparison_service.py — ルート比較 × 気象＋ハザード統合リスク (Phase3-A)

POST /api/navigation/route/compare のバックエンド実装。

OSRM alternatives を取得し、各ルートを
降水強度 × ハザードゾーン通過率 で統合評価してランク付けする。

重要方針:
  - 自動 reroute 禁止（比較提示のみ）
  - OSRM weighting 非改変
  - unknown を none に倒さない（false-safe 防止）
  - unavailable を warning 扱いしない
  - route churn は frontend で threshold 管理
  - TTL キャッシュ 60秒
"""
import hashlib
import json
import logging
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

from app.services.weather_alert_service import get_precipitation_summary
from app.services.route_risk_scoring import calc_route_risk_score
from app.services.weather_risk_context_service import (
    _INTENSITY_RANK,
    _fetch_hazard_assessment,
    _build_hazard_flags,
)

logger = logging.getLogger(__name__)

# OSRM walking URL: Docker 内部では osrm-walking:5001（--port 5001 起動）
_OSRM_WALKING_URL = os.environ.get(
    "OSRM_WALKING_URL",
    "http://osrm-walking:5001/route/v1/walking",
)

_COMPARE_CACHE: dict = {}
_COMPARE_TTL = 60.0  # 秒

# 気象ペナルティ（safety_score 追加減点）
_WEATHER_PENALTY: dict[str, float] = {
    "severe":   30.0,
    "strong":   15.0,
    "moderate":  5.0,
    "weak":      2.0,
}

# 複合追加ペナルティ（max_intensity × ハザード）
_COMBINED_EXTRA: dict[str, float] = {
    "strong+flood":        15.0,
    "severe+flood":        30.0,
    "strong+landslide":    15.0,
    "severe+landslide":    25.0,
    "strong+inland_flood": 10.0,
    "severe+inland_flood": 15.0,
    "strong+storm_surge":  10.0,
    "severe+storm_surge":  20.0,
}

# route_risk_scoring のハザードキー ↔ build_hazard_flags のキー
_HAZARD_KEY_MAP: dict[str, str] = {
    "lowland":      "lowland_poor_drainage",
    "flood":        "flood",
    "inland_flood": "inland_flood",
    "landslide":    "landslide",
    "tsunami":      "tsunami",
    "storm_surge":  "storm_surge",
}

# weather risk_level → rank
_WR_RANK: dict[str, int] = {
    "emergency": 4, "warning": 3, "advisory": 2, "none": 0, "unknown": -1,
}

# サンプリング設定（/api/route-risk と同じ均等サンプリング・同点数に統一）
_MAX_SAMPLES = 30


def _cache_key(origin: list, destination: list) -> str:
    raw = (
        f"{round(origin[0], 4)},{round(origin[1], 4)}"
        f"_{round(destination[0], 4)},{round(destination[1], 4)}"
    )
    bucket = int(time.time() // 60)
    return hashlib.md5(f"{raw}_{bucket}".encode()).hexdigest()[:16]


# ── OSRM 呼び出し ──────────────────────────────────────────────────────────────

def _fetch_osrm_routes(
    origin_lonlat: list,
    dest_lonlat: list,
    alternatives: int = 3,
) -> list:
    """OSRM から alternatives ルートを取得する（同期）。"""
    coord_str = f"{origin_lonlat[0]},{origin_lonlat[1]};{dest_lonlat[0]},{dest_lonlat[1]}"
    url = (
        f"{_OSRM_WALKING_URL}/{coord_str}"
        f"?overview=full&geometries=geojson&alternatives={alternatives}&steps=false"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "OnHighGround2/Phase3-A"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("OSRM fetch failed url=%s: %s", url, exc)
        return []
    if data.get("code") != "Ok" or not isinstance(data.get("routes"), list):
        logger.warning("OSRM unexpected response code=%s", data.get("code"))
        return []
    return data["routes"]


def _osrm_coords(route: dict) -> list[tuple[float, float]]:
    """OSRM GeoJSON geometry から [(lat, lon), ...] を抽出する。"""
    raw = (route.get("geometry") or {}).get("coordinates") or []
    return [(float(c[1]), float(c[0])) for c in raw if len(c) >= 2]


# ── ルート評価 ────────────────────────────────────────────────────────────────

def _sample_uniform(
    coords: list[tuple[float, float]],
    max_samples: int = _MAX_SAMPLES,
) -> list[tuple[float, float]]:
    """均等サンプリング（/api/route-risk と同じ方式）。"""
    n = len(coords)
    if n == 0:
        return []
    if n <= max_samples:
        return list(coords)
    step = max(1, n // max_samples)
    sampled = list(coords[::step])
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    return sampled[:max_samples]


def _assess_route_hazard(
    coords: list[tuple[float, float]],
) -> dict:
    """
    サンプル点ごとにハザード判定し、
    - exposure_by_hazard: {hazard_key: exposure_ratio}
    - hazard_union:       {short_key: bool|None}
    を返す。
    """
    sample_points = _sample_uniform(coords)
    if not sample_points:
        return {"exposure": {}, "union": {}, "data_available": False}

    hazard_inside_counts: dict[str, int] = {}
    hazard_union: dict[str, Optional[bool]] = {}
    data_available = False

    for lat, lon in sample_points:
        raw = _fetch_hazard_assessment(lat, lon)
        if raw:
            data_available = True
        flags = _build_hazard_flags(raw)

        for short_key, val in flags.items():
            if short_key == "data_available":
                continue
            if val is True:
                long_key = _HAZARD_KEY_MAP.get(short_key, short_key)
                hazard_inside_counts[long_key] = hazard_inside_counts.get(long_key, 0) + 1
                hazard_union[short_key] = True
            elif val is False and hazard_union.get(short_key) is None:
                hazard_union[short_key] = False

    n = len(sample_points)
    exposure = {k: v / n for k, v in hazard_inside_counts.items()}
    return {"exposure": exposure, "union": hazard_union, "data_available": data_available}


def _assess_route_weather(
    coords: list[tuple[float, float]],
) -> dict:
    """
    ルート代表点（中間点）の降水予測を取得し、
    - max_intensity: 最大降水強度文字列
    - weather_risk:  none/advisory/warning/emergency
    を返す。
    """
    if not coords:
        return {"max_intensity": "unknown", "weather_risk": "unknown"}
    mid = coords[len(coords) // 2]
    try:
        precip = get_precipitation_summary(mid[0], mid[1])
    except Exception as exc:
        logger.warning("route compare: precip failed lat=%s lon=%s: %s", mid[0], mid[1], exc)
        return {"max_intensity": "unknown", "weather_risk": "unknown"}

    if (precip or {}).get("status") == "unavailable":
        return {"max_intensity": "unknown", "weather_risk": "unavailable"}

    severity = (precip or {}).get("severity", "none") or "none"
    max_intensity = ((precip or {}).get("current") or {}).get("intensity", "unknown") or "unknown"
    forecast = (precip or {}).get("forecast") or []
    max_rank  = _INTENSITY_RANK.get(max_intensity, -1)
    for f in forecast:
        fi   = f.get("intensity", "unknown")
        rank = _INTENSITY_RANK.get(fi, -1)
        if rank > max_rank:
            max_rank = rank
            max_intensity = fi

    _SEV_TO_RISK = {
        "emergency": "emergency", "warning": "warning",
        "advisory": "advisory", "none": "none", "unknown": "unknown",
    }
    return {
        "max_intensity": max_intensity,
        "weather_risk":  _SEV_TO_RISK.get(severity, "unknown"),
    }


def _calc_weather_penalty(max_intensity: str, hazard_union: dict) -> float:
    """気象ペナルティを計算する（base + combined extra）。"""
    base = _WEATHER_PENALTY.get(max_intensity, 0.0)
    extra = 0.0
    for short_key, val in hazard_union.items():
        if val is not True:
            continue
        combo = f"{max_intensity}+{short_key}"
        extra += _COMBINED_EXTRA.get(combo, 0.0)
    return base + extra


def _to_risk_level(safety_score: float, weather_risk: str) -> str:
    """統合 safety_score と weather_risk から route risk_level を決定する。
    既知ハザードが advisory/warning/emergency を引き起こす場合はそれを優先。
    既知リスクなし + weather_risk unknown → unknown を保持（false-safe 防止）。
    """
    wr = _WR_RANK.get(weather_risk, 0)
    if safety_score < 30 or wr >= 4:
        return "emergency"
    if safety_score < 50 or wr >= 3:
        return "warning"
    if safety_score < 75 or wr >= 2:
        return "advisory"
    if weather_risk == "unknown":
        return "unknown"
    return "none"


def _build_risk_summary(
    hazard_notes: list[str],
    max_intensity: str,
    hazard_union: dict,
) -> list[str]:
    """risk_summary テキストリストを生成する（最大 3 件）。"""
    summary = []

    INTENSITY_LABEL = {
        "severe":   "非常に激しい雨域通過予測",
        "strong":   "強雨域接近",
        "moderate": "雨域を通過",
        "weak":     "弱い雨域通過予測",
        "unknown":  "気象リスク判定不能",
    }
    HAZARD_LABEL = {
        "flood":        "洪水想定区域",
        "inland_flood": "内水氾濫想定区域",
        "landslide":    "土砂災害警戒区域",
        "lowland":      "低地・排水困難エリア",
        "tsunami":      "津波想定区域",
        "storm_surge":  "高潮想定区域",
    }

    if lbl := INTENSITY_LABEL.get(max_intensity):
        summary.append(lbl)
    for key, val in hazard_union.items():
        if val is True:
            if lbl := HAZARD_LABEL.get(key):
                if lbl not in summary:
                    summary.append(lbl)

    return summary[:3]


def _assess_route(route_idx: int, route_dict: dict, now_iso: str) -> dict:
    """1ルートを評価してスコアとリスクサマリーを返す。"""
    coords     = _osrm_coords(route_dict)
    distance_m = round(route_dict.get("distance", 0))
    duration_s = round(route_dict.get("duration", 0))

    if len(coords) < 2:
        return {
            "index":        route_idx,
            "distance_m":   distance_m,
            "duration_s":   duration_s,
            "risk_level":   "unknown",
            "safety_score": 50.0,
            "risk_summary": ["ルートデータ不足"],
            "hazards":      {},
            "weather":      {"forecast_max_intensity": "unknown"},
            "status":       "unavailable",
        }

    # ハザード評価（並列、各点でポリゴン在外判定）
    hazard_result  = _assess_route_hazard(coords)
    exposure       = hazard_result["exposure"]
    hazard_union   = hazard_result["union"]

    # ハザードスコア（既存 route_risk_scoring を再利用）
    scoring_result = calc_route_risk_score(exposure)
    hazard_safety  = scoring_result["safety_score"]
    hazard_notes   = scoring_result["risk_summary"]["notes"]

    # 気象評価（代表点1点）
    weather_result  = _assess_route_weather(coords)
    max_intensity   = weather_result["max_intensity"]
    weather_risk    = weather_result["weather_risk"]

    # 気象ペナルティを適用
    weather_penalty  = _calc_weather_penalty(max_intensity, hazard_union)
    combined_safety  = max(0.0, min(100.0, hazard_safety - weather_penalty))
    risk_level       = _to_risk_level(combined_safety, weather_risk)

    risk_summary = _build_risk_summary(hazard_notes, max_intensity, hazard_union)

    # 公開ハザードフラグ（data_available 除外）
    public_hazards = {k: v for k, v in hazard_union.items()}

    return {
        "index":        route_idx,
        "distance_m":   distance_m,
        "duration_s":   duration_s,
        "risk_level":   risk_level,
        "safety_score": round(combined_safety, 1),
        "risk_summary": risk_summary,
        "hazards":      public_hazards,
        "weather":      {"forecast_max_intensity": max_intensity},
        "status":       "ok",
    }


# ── ランキング ────────────────────────────────────────────────────────────────

_LEVEL_RANK: dict[str, int] = {
    "none": 4, "advisory": 3, "warning": 2, "emergency": 1, "unknown": 0,
}


def _rank_routes(assessed: list[dict]) -> int:
    """推奨ルートのインデックスを返す。

    優先度: risk_level > safety_score > distance > duration
    """
    def sort_key(r: dict) -> tuple:
        level = _LEVEL_RANK.get(r["risk_level"], 0)
        return (level, r["safety_score"], -r["distance_m"], -r["duration_s"])

    best = max(assessed, key=sort_key)
    return best["index"]


# ── メインエントリ ────────────────────────────────────────────────────────────

def get_route_comparison(origin: list[float], destination: list[float]) -> dict:
    """ルート比較を返す（TTLキャッシュ付き）。"""
    key      = _cache_key(origin, destination)
    now_mono = time.monotonic()
    now_iso  = datetime.now(timezone.utc).isoformat()

    cached = _COMPARE_CACHE.get(key)
    if cached is not None:
        data, fetched_at = cached
        if now_mono - fetched_at < _COMPARE_TTL:
            return data

    try:
        data = _build_comparison(origin, destination, now_iso)
    except Exception as exc:
        logger.warning("get_route_comparison failed: %s", exc)
        data = {
            "status":                  "unavailable",
            "recommended_route_index": 0,
            "routes":                  [],
            "updated_at":              now_iso,
        }

    _COMPARE_CACHE[key] = (data, now_mono)
    return data


def _build_comparison(origin: list[float], destination: list[float], now_iso: str) -> dict:
    """OSRM からルートを取得し、気象×ハザード統合スコアで比較する。"""
    # OSRM alternatives を同期で取得（ブロッキング）
    raw_routes = _fetch_osrm_routes(origin, destination, alternatives=3)
    if not raw_routes:
        return {
            "status":                  "unavailable",
            "recommended_route_index": 0,
            "routes":                  [],
            "updated_at":              now_iso,
        }

    # 各ルートを並列評価（最大3ルート）
    assessed: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_assess_route, idx, r, now_iso): idx
            for idx, r in enumerate(raw_routes[:3])
        }
        for future in as_completed(futures, timeout=25):
            idx = futures[future]
            try:
                assessed.append(future.result())
            except Exception as exc:
                logger.warning("route compare: route %d failed: %s", idx, exc)

    if not assessed:
        return {
            "status":                  "unavailable",
            "recommended_route_index": 0,
            "routes":                  [],
            "updated_at":              now_iso,
        }

    assessed.sort(key=lambda r: r["index"])
    recommended_idx = _rank_routes(assessed)

    return {
        "status":                  "ok",
        "recommended_route_index": recommended_idx,
        "routes":                  assessed,
        "updated_at":              now_iso,
    }
