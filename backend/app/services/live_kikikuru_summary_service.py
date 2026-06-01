"""
live_kikikuru_summary_service.py — キキクル危険度集計サービス (Phase 3-B)

JMA キキクル（危険度分布）タイルを代表点サンプリングし、
/api/live/summary の kikikuru セクションを返す。

対象 hazard: land（土砂）/ inund（浸水）/ flood_mesh（洪水）

判定方式:
  いずれかの hazard が warning / danger → danger_detected=True
  全地点で全 hazard が unknown >= 50% かつ warning/danger なし → evaluated=False
  JMA 取得失敗 → status=offline, evaluated=False

キャッシュ TTL: 120 秒（雨雲キャッシュとは別）
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import io
import json
import logging
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JST = timezone(timedelta(hours=9))
_CACHE_TTL = 120.0
_MAX_WORKERS = 8
_TOTAL_SAMPLING_TIMEOUT = 30.0
_MAX_AREAS = 5
_ZOOM = 8          # 偶数ズームを使用（JMA kikikuru タイルは偶数ズームが有効）
_SAMPLE_RADIUS_PX = 2
_UNKNOWN_RATE_THRESHOLD = 0.5

_KIKIKURU_TIMES_URL = "https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json"
_KIKIKURU_TILE_BASE = "https://www.jma.go.jp/bosai/jmatile/data/risk"

# Phase 3-B: land（土砂）/ inund（浸水）/ flood_mesh（洪水）を集計
_KIKI_ELEMENTS: List[str] = ["land", "inund", "flood_mesh"]
HAZARD_LABEL: Dict[str, str] = {
    "land":       "土砂",
    "inund":      "浸水",
    "flood_mesh": "洪水",
}

_kikikuru_summary_cache: Optional[tuple[dict, float]] = None
_times_cache: Optional[tuple[dict, float]] = None
_tile_png_cache: dict[str, tuple[bytes, float]] = {}
_TILE_SIZE_PX = 256
_PNG_CACHE_MAX = 300
_PNG_TTL = 120.0

# キキクル危険度カラーテーブル（JMA 危険度分布タイル近似色）
# (R, G, B, level, risk_class)
_KIKI_COLOR_TABLE: List[tuple] = [
    # 注意 (watch) — 黄色系
    (255, 242,   0, "watch",   1),
    (255, 255,   0, "watch",   1),
    (248, 230,   0, "watch",   1),
    # 警戒 (warning) — 橙色系
    (255, 128,   0, "warning", 2),
    (255, 153,   0, "warning", 2),
    (255, 100,   0, "warning", 2),
    # 危険 (danger) — 赤色系
    (255,   0,   0, "danger",  3),
    (230,   0,   0, "danger",  3),
    (255,  40,   0, "danger",  3),
    # 災害切迫 (danger) — 紫系
    (165,   0, 165, "danger",  4),
    (130,   0, 130, "danger",  4),
    (180,   0, 104, "danger",  4),
    (100,   0, 100, "danger",  4),
]
_KIKI_DIST_THRESHOLD_SQ = 50 ** 2
_ALPHA_TRANSPARENT_MAX = 50
_BG_RGB_MIN = 220  # R/G/B すべてこれ以上 → 背景（なし）

_LEVEL_ORDER: Dict[str, int] = {
    "danger": 3, "warning": 2, "watch": 1, "normal": 0, "unknown": -1,
}


# ── タイル取得ユーティリティ ─────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 8) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OnHighGround2/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _fetch_tile_png(url: str) -> Optional[bytes]:
    now = time.monotonic()
    if url in _tile_png_cache:
        data, fetched_at = _tile_png_cache[url]
        if now - fetched_at < _PNG_TTL:
            return data

    if len(_tile_png_cache) >= _PNG_CACHE_MAX:
        oldest = min(_tile_png_cache, key=lambda k: _tile_png_cache[k][1])
        del _tile_png_cache[oldest]

    try:
        raw = _http_get(url)
        _tile_png_cache[url] = (raw, now)
        return raw
    except Exception as exc:
        logger.debug("kiki tile fetch failed %s: %s", url, exc)
        return None


def _lat_lon_to_tile_pixel(lat: float, lon: float, zoom: int) -> tuple[int, int, int, int]:
    n = 2 ** zoom
    x_frac = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y_frac = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    tile_x = int(x_frac)
    tile_y = int(y_frac)
    px = min(int((x_frac - tile_x) * _TILE_SIZE_PX), _TILE_SIZE_PX - 1)
    py = min(int((y_frac - tile_y) * _TILE_SIZE_PX), _TILE_SIZE_PX - 1)
    return tile_x, tile_y, px, py


# ── カラー判定 ───────────────────────────────────────────────────────────────

def _rgba_to_kiki_level(r: int, g: int, b: int, a: int) -> str:
    if a < _ALPHA_TRANSPARENT_MAX:
        return "normal"
    if r >= _BG_RGB_MIN and g >= _BG_RGB_MIN and b >= _BG_RGB_MIN:
        return "normal"

    best_level = "unknown"
    best_dist_sq = float("inf")
    for tr, tg, tb, level, _ in _KIKI_COLOR_TABLE:
        d = (r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2
        if d < best_dist_sq:
            best_dist_sq = d
            best_level = level

    if best_dist_sq > _KIKI_DIST_THRESHOLD_SQ:
        return "unknown"
    return best_level


def _sample_max_level(pixels: Any, px: int, py: int, radius: int, width: int, height: int) -> str:
    """(px, py) 中心の (2*radius+1)^2 画素の最大危険度を返す。"""
    best_level = "normal"
    has_unknown_opaque = False

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x = max(0, min(width - 1, px + dx))
            y = max(0, min(height - 1, py + dy))
            rgba = pixels[x, y]
            r, g, b = rgba[0], rgba[1], rgba[2]
            a = rgba[3] if len(rgba) > 3 else 255
            level = _rgba_to_kiki_level(r, g, b, a)
            if level == "unknown":
                has_unknown_opaque = True
            elif _LEVEL_ORDER.get(level, 0) > _LEVEL_ORDER.get(best_level, 0):
                best_level = level

    if best_level == "normal" and has_unknown_opaque:
        return "unknown"
    return best_level


def _get_kiki_level_at(lat: float, lon: float, tile_url_template: str) -> Dict[str, Any]:
    """lat/lon 地点のキキクル危険度レベルを返す。"""
    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow not installed — cannot analyze kikikuru tile pixels")
        return {"level": "unknown", "source": "no_pillow"}

    try:
        zoom = _ZOOM if _ZOOM % 2 == 0 else _ZOOM - 1
        tile_x, tile_y, px, py = _lat_lon_to_tile_pixel(lat, lon, zoom)
        url = (
            tile_url_template
            .replace("{z}", str(zoom))
            .replace("{x}", str(tile_x))
            .replace("{y}", str(tile_y))
        )

        raw = _fetch_tile_png(url)
        if raw is None:
            return {"level": "unknown", "source": "fetch_failed"}

        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        width, height = img.size
        pixels = img.load()
        level = _sample_max_level(pixels, px, py, _SAMPLE_RADIUS_PX, width, height)
        return {"level": level, "source": "jma_kikikuru_tile"}

    except Exception as exc:
        logger.warning("_get_kiki_level_at failed lat=%s lon=%s: %s", lat, lon, exc)
        return {"level": "unknown", "source": "error"}


# ── targetTimes 取得 ──────────────────────────────────────────────────────────

def _fetch_kiki_times() -> Optional[Dict[str, Any]]:
    global _times_cache
    now = time.monotonic()

    if _times_cache is not None:
        entry, fetched_at = _times_cache
        if now - fetched_at < _CACHE_TTL:
            return entry

    raw = _http_get(_KIKIKURU_TIMES_URL, timeout=10)
    entries = json.loads(raw)
    if not isinstance(entries, list) or not entries:
        raise ValueError("kikikuru targetTimes empty or invalid")

    entry = entries[0]
    _times_cache = (entry, now)
    return entry


def _build_kiki_tile_url(entry: Dict[str, Any], elem: str) -> str:
    basetime  = entry["basetime"]
    member    = entry.get("member", "immed0")
    validtime = entry.get("validtime", basetime)
    return f"{_KIKIKURU_TILE_BASE}/{basetime}/{member}/{validtime}/surf/{elem}/{{z}}/{{x}}/{{y}}.png"


# ── サンプリング（同期・内部用）──────────────────────────────────────────────

def _sample_all_hazards_sync(hazard_urls: Dict[str, str]) -> List[Dict[str, Any]]:
    """全代表点 × 全 hazard の危険度を並列取得する（同期版、asyncio.to_thread から呼ぶ）。

    hazard_urls: {hazard_name: tile_url_template, ...}
    returns: flat list of {**pt, hazard, level, source}
    """
    from app.services.live_rain_summary_service import LIVE_RAIN_SAMPLE_POINTS as _SAMPLE_POINTS

    results: List[Dict[str, Any]] = []
    tasks: List[tuple] = [
        (pt, url, hazard)
        for hazard, url in hazard_urls.items()
        for pt in _SAMPLE_POINTS
    ]

    def _fetch_one(pt: Dict[str, Any], url: str, hazard: str) -> Dict[str, Any]:
        res = _get_kiki_level_at(pt["lat"], pt["lng"], url)
        return {**pt, "hazard": hazard, **res}

    def _unknown_entry(pt: Dict[str, Any], hazard: str, source: str = "error") -> Dict[str, Any]:
        return {**pt, "hazard": hazard, "level": "unknown", "source": source}

    completed: set = set()

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        future_map = {executor.submit(_fetch_one, pt, url, h): (pt, h) for pt, url, h in tasks}
        try:
            for future in as_completed(future_map, timeout=_TOTAL_SAMPLING_TIMEOUT):
                pt, hazard = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.warning("kiki sample failed %s/%s: %s", pt["id"], hazard, exc)
                    results.append(_unknown_entry(pt, hazard))
                completed.add(future)
        except concurrent.futures.TimeoutError:
            logger.warning("kiki sampling timed out after %.1fs", _TOTAL_SAMPLING_TIMEOUT)

        for future, (pt, hazard) in future_map.items():
            if future not in completed:
                results.append(_unknown_entry(pt, hazard, source="timeout"))
                future.cancel()

    return results


# ── セクション構築（純粋関数・テスト容易）────────────────────────────────────

def build_kikikuru_section_from_samples(
    samples: List[Dict[str, Any]],
    observed_at: str,
) -> Dict[str, Any]:
    """
    サンプル結果リストから kikikuru セクション辞書を構築する。

    samples の各要素は LIVE_RAIN_SAMPLE_POINTS の地点属性 +
    level / hazard / source を持つ。
    1地点に複数 hazard のサンプルがある場合も地点数ベースで集計する。
    """
    if not samples:
        return _offline_kikikuru_section()

    # 地点 ID でグループ化（複数 hazard を1地点として扱う）
    point_samples: Dict[str, List] = {}
    for s in samples:
        point_samples.setdefault(s["id"], []).append(s)

    sample_count = len(point_samples)

    # 地点全体の unknown 判定: その地点の全 hazard が unknown の場合のみカウント
    unknown_count = sum(
        1 for pt_s in point_samples.values()
        if all(s.get("level") == "unknown" for s in pt_s)
    )

    obs_tag = observed_at.replace(":", "").replace("-", "").replace("+", "")[:13]

    # watch 集計（危険地域には入れない）
    watch_count = sum(1 for s in samples if s.get("level") == "watch")

    # warning / danger 地点を抽出して areas 候補を構築
    all_qualifying: List[Dict[str, Any]] = []
    for s in samples:
        level = s.get("level", "normal")
        if level not in ("warning", "danger"):
            continue
        hazard = s.get("hazard", "land")
        all_qualifying.append({
            "id":          f"kikikuru-{s['id']}-{hazard}-{obs_tag}",
            "label":       f"{s['prefecture']}付近",
            "prefecture":  s["prefecture"],
            "area_name":   s["label"],
            "level":       level,
            "type":        "kikikuru",
            "hazard":      hazard,
            "source":      "jma_kikikuru",
            "lat":         s["lat"],
            "lng":         s["lng"],
            "observed_at": observed_at,
            "description": "キキクル危険度を検出",
        })

    danger_detected = len(all_qualifying) > 0

    # Phase 3-C: 観察ログ（hazard 種別ごとの件数）
    land_count  = sum(1 for a in all_qualifying if a.get("hazard") == "land")
    inund_count = sum(1 for a in all_qualifying if a.get("hazard") == "inund")
    flood_count = sum(1 for a in all_qualifying if a.get("hazard") == "flood_mesh")
    logger.info(
        "live kikikuru observation: landslide=%d flood=%d inundation=%d areas=%d",
        land_count, flood_count, inund_count, len(all_qualifying),
    )

    # unknown 率が高い かつ 危険未検出 → 評価不能（false-safe 防止）
    if not danger_detected and unknown_count / sample_count >= _UNKNOWN_RATE_THRESHOLD:
        return {
            "status":    "unknown",
            "evaluated": False,
            "reason":    "too_many_unknown_samples",
            "summary": {
                "danger_detected":    None,
                "watch_area_count":   None,
                "warning_area_count": None,
                "danger_area_count":  None,
                "sample_count":       sample_count,
                "unknown_count":      unknown_count,
            },
            "areas": [],
        }

    # 全検出件数を集計（areas 上限適用前）
    warning_count = sum(1 for a in all_qualifying if a["level"] == "warning")
    danger_count  = sum(1 for a in all_qualifying if a["level"] == "danger")

    # danger 優先で最大 _MAX_AREAS 件に絞る
    all_qualifying.sort(key=lambda a: 0 if a["level"] == "danger" else 1)
    areas = all_qualifying[:_MAX_AREAS]

    logger.info(
        "live kikikuru summary: areas=%d danger=%d warning=%d",
        len(areas), danger_count, warning_count,
    )

    return {
        "status":    "ok",
        "evaluated": True,
        "reason":    "sampled_kikikuru",
        "summary": {
            "danger_detected":    danger_detected,
            "watch_area_count":   watch_count,
            "warning_area_count": warning_count,
            "danger_area_count":  danger_count,
            "sample_count":       sample_count,
            "unknown_count":      unknown_count,
        },
        "areas": areas,
    }


# ── パブリック API（async）────────────────────────────────────────────────────

async def build_live_kikikuru_summary() -> Dict[str, Any]:
    """
    キキクル危険度サマリーを返す（120 秒キャッシュ）。

    失敗時は status=offline, evaluated=False (danger_detected=null)。
    """
    global _kikikuru_summary_cache

    now_mono = time.monotonic()
    if _kikikuru_summary_cache is not None:
        cached, fetched_at = _kikikuru_summary_cache
        if now_mono - fetched_at < _CACHE_TTL:
            return cached

    try:
        entry = await asyncio.to_thread(_fetch_kiki_times)
        if entry is None:
            logger.warning("live_kikikuru_summary: targetTimes 取得失敗")
            return _offline_kikikuru_section()

        observed_at = datetime.now(_JST).isoformat()

        # Phase 3-B: 全 hazard を一括サンプリング
        hazard_urls = {h: _build_kiki_tile_url(entry, h) for h in _KIKI_ELEMENTS}
        samples = await asyncio.to_thread(_sample_all_hazards_sync, hazard_urls)

        result = build_kikikuru_section_from_samples(samples, observed_at)
        _kikikuru_summary_cache = (result, now_mono)

        logger.info(
            "live_kikikuru_summary: evaluated=%s detected=%s samples=%d unknown=%d",
            result.get("evaluated"),
            result.get("summary", {}).get("danger_detected"),
            result.get("summary", {}).get("sample_count", 0),
            result.get("summary", {}).get("unknown_count", 0),
        )
        return result

    except Exception as exc:
        logger.warning("live_kikikuru_summary: 集計失敗: %s", exc)
        return _offline_kikikuru_section()


def _offline_kikikuru_section() -> Dict[str, Any]:
    from app.services.live_rain_summary_service import LIVE_RAIN_SAMPLE_POINTS
    n = len(LIVE_RAIN_SAMPLE_POINTS)
    return {
        "status":    "offline",
        "evaluated": False,
        "reason":    "source_unavailable",
        "summary": {
            "danger_detected":    None,
            "watch_area_count":   None,
            "warning_area_count": None,
            "danger_area_count":  None,
            "sample_count":       n,
            "unknown_count":      n,
        },
        "areas": [],
    }
