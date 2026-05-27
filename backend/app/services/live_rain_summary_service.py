"""
live_rain_summary_service.py — 雨雲危険度集計サービス (Phase 2-A)

全国サンプリング地点で JMA nowcast タイルの降水強度を取得し、
/api/live/summary の rain セクションを返す。

判定方式: サンプリングポイントの最大強度をカラーテーブルで判定
  strong / severe が 1 地点以上 → strong_rain_detected=True
  unknown が 50% 以上 → evaluated=False (too_many_unknown_samples)
  JMA 取得失敗 → status=offline, evaluated=False

キャッシュ TTL: 120 秒（JMA nowcast への過剰アクセスを防ぐ）
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JST = timezone(timedelta(hours=9))
_CACHE_TTL = 120.0  # 秒

_rain_summary_cache: Optional[tuple[dict, float]] = None

# ── サンプリング地点（Phase 2-A MVP: 全国 11 地点）────────────────────────────

LIVE_RAIN_SAMPLE_POINTS: List[Dict[str, Any]] = [
    {"id": "sapporo",   "label": "札幌",   "prefecture": "北海道",   "lat": 43.0618, "lng": 141.3545},
    {"id": "sendai",    "label": "仙台",   "prefecture": "宮城県",   "lat": 38.2682, "lng": 140.8694},
    {"id": "tokyo",     "label": "東京",   "prefecture": "東京都",   "lat": 35.6812, "lng": 139.7671},
    {"id": "niigata",   "label": "新潟",   "prefecture": "新潟県",   "lat": 37.9161, "lng": 139.0365},
    {"id": "nagoya",    "label": "名古屋", "prefecture": "愛知県",   "lat": 35.1709, "lng": 136.8815},
    {"id": "osaka",     "label": "大阪",   "prefecture": "大阪府",   "lat": 34.6937, "lng": 135.5023},
    {"id": "hiroshima", "label": "広島",   "prefecture": "広島県",   "lat": 34.3853, "lng": 132.4553},
    {"id": "kochi",     "label": "高知",   "prefecture": "高知県",   "lat": 33.5597, "lng": 133.5311},
    {"id": "fukuoka",   "label": "福岡",   "prefecture": "福岡県",   "lat": 33.5902, "lng": 130.4017},
    {"id": "kagoshima", "label": "鹿児島", "prefecture": "鹿児島県", "lat": 31.5966, "lng": 130.5571},
    {"id": "naha",      "label": "那覇",   "prefecture": "沖縄県",   "lat": 26.2124, "lng": 127.6792},
]

# 強度 → dangerous_areas level 変換（warning 以上のみ追加）
_INTENSITY_TO_LEVEL: Dict[str, Optional[str]] = {
    "none":     None,
    "weak":     None,
    "moderate": "watch",
    "strong":   "warning",
    "severe":   "danger",
    "unknown":  None,
}

# unknown 率のしきい値（これ以上なら評価不能）
_UNKNOWN_RATE_THRESHOLD = 0.5


def _intensity_qualifies_as_strong(intensity: str) -> bool:
    return intensity in ("strong", "severe")


# ── サンプリング（同期・内部用）──────────────────────────────────────────────

def _sample_all_points_sync(tile_url_template: str) -> List[Dict[str, Any]]:
    """全サンプリング地点の降水強度を並列取得する（同期版、asyncio.to_thread から呼ぶ）。"""
    from services.jma_rain_tile_service import get_precip_intensity_at

    results: List[Dict[str, Any]] = []

    def _fetch_one(pt: Dict[str, Any]) -> Dict[str, Any]:
        res = get_precip_intensity_at(pt["lat"], pt["lng"], tile_url_template)
        return {**pt, **res}

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_fetch_one, pt): pt for pt in LIVE_RAIN_SAMPLE_POINTS}
        for future in as_completed(futures, timeout=25):
            try:
                results.append(future.result())
            except Exception as exc:
                pt = futures[future]
                logger.warning("rain sample failed %s: %s", pt["id"], exc)
                results.append({
                    **pt,
                    "intensity":  "unknown",
                    "label":      "判定不能",
                    "rain_class": -1,
                    "source":     "error",
                })

    return results


# ── セクション構築（純粋関数・テスト容易）────────────────────────────────────

def build_rain_section_from_samples(
    samples: List[Dict[str, Any]],
    observed_at: str,
) -> Dict[str, Any]:
    """
    サンプル結果リストから rain セクション辞書を構築する。

    samples の各要素は LIVE_RAIN_SAMPLE_POINTS の各地点属性 +
    get_precip_intensity_at の返り値 (intensity, rain_class, source) を持つ。
    """
    sample_count = len(samples)
    if sample_count == 0:
        return _offline_rain_section()

    unknown_count = sum(1 for s in samples if s.get("intensity") == "unknown")

    # unknown 率が高すぎる → 評価不能（false-safe 防止）
    if unknown_count / sample_count >= _UNKNOWN_RATE_THRESHOLD:
        return {
            "status":    "unknown",
            "evaluated": False,
            "reason":    "too_many_unknown_samples",
            "summary": {
                "strong_rain_detected": None,
                "warning_area_count":   None,
                "danger_area_count":    None,
                "sample_count":         sample_count,
                "unknown_count":        unknown_count,
            },
            "areas": [],
        }

    # 強雨地点を抽出して areas 構築
    areas: List[Dict[str, Any]] = []
    warning_count = 0
    danger_count = 0

    obs_tag = observed_at.replace(":", "").replace("-", "").replace("+", "")[:13]

    for s in samples:
        intensity = s.get("intensity", "none")
        if not _intensity_qualifies_as_strong(intensity):
            continue
        level = _INTENSITY_TO_LEVEL.get(intensity)
        if level not in ("warning", "danger"):
            continue
        if level == "warning":
            warning_count += 1
        else:
            danger_count += 1
        areas.append({
            "id":          f"rain-{s['id']}-{obs_tag}",
            "label":       f"{s['prefecture']}付近",
            "prefecture":  s["prefecture"],
            "area_name":   s["label"],
            "level":       level,
            "type":        "rain",
            "source":      "jma_nowcast",
            "lat":         s["lat"],
            "lng":         s["lng"],
            "observed_at": observed_at,
            "description": "強雨域を検出",
        })

    strong_rain_detected = len(areas) > 0 or any(
        _intensity_qualifies_as_strong(s.get("intensity", "none")) for s in samples
    )

    return {
        "status":    "ok",
        "evaluated": True,
        "reason":    "sampled_nowcast",
        "summary": {
            "strong_rain_detected": strong_rain_detected,
            "warning_area_count":   warning_count,
            "danger_area_count":    danger_count,
            "sample_count":         sample_count,
            "unknown_count":        unknown_count,
        },
        "areas": areas,
    }


# ── パブリック API（async）────────────────────────────────────────────────────

async def build_live_rain_summary() -> Dict[str, Any]:
    """
    雨雲危険度サマリーを返す（120 秒キャッシュ）。

    失敗時は status=offline, evaluated=False (strong_rain_detected=null)。
    """
    global _rain_summary_cache

    now_mono = time.monotonic()
    if _rain_summary_cache is not None:
        cached, fetched_at = _rain_summary_cache
        if now_mono - fetched_at < _CACHE_TTL:
            return cached

    try:
        from services.jma_rain_tile_service import get_rain_tile_latest

        tile_info = await asyncio.to_thread(get_rain_tile_latest)
        if tile_info is None:
            logger.warning("live_rain_summary: タイル情報取得失敗")
            return _offline_rain_section()

        tile_url = tile_info["tile_url_template"]
        observed_at = datetime.now(_JST).isoformat()

        samples = await asyncio.to_thread(_sample_all_points_sync, tile_url)
        result = build_rain_section_from_samples(samples, observed_at)
        _rain_summary_cache = (result, now_mono)

        logger.info(
            "live_rain_summary: evaluated=%s detected=%s samples=%d unknown=%d",
            result.get("evaluated"),
            result.get("summary", {}).get("strong_rain_detected"),
            result.get("summary", {}).get("sample_count", 0),
            result.get("summary", {}).get("unknown_count", 0),
        )
        return result

    except Exception as exc:
        logger.warning("live_rain_summary: 集計失敗: %s", exc)
        return _offline_rain_section()


def _offline_rain_section() -> Dict[str, Any]:
    return {
        "status":    "offline",
        "evaluated": False,
        "reason":    "source_unavailable",
        "summary": {
            "strong_rain_detected": None,
            "warning_area_count":   None,
            "danger_area_count":    None,
            "sample_count":         0,
            "unknown_count":        None,
        },
        "areas": [],
    }
