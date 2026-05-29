"""
live_rain_tile_scan_service.py — 雨雲面スキャンサービス (Phase 2-D.1)

JMA nowcast タイルをグリッドスキャンし、strong/severe ピクセルを「面」として検出する。
地点サンプリングでは取り逃す帯状・局地的強雨（例: 千葉県沿岸）に対応する。

方式: タイル単位クラスタ
  各タイルで strong/severe ピクセルが閾値以上 → そのタイルを 1 area とする
  area の lat/lng は strong/severe ピクセルの重心（Phase 2-D.1 変更）
  prefecture / label は重心座標から最近傍の都道府県代表点で推定

設定:
  SCAN_ZOOM         = 6  （JMA nowcast は偶数ズームのみ有効）
  SCAN_BBOX         = 日本周辺 (lat 24〜46.5, lng 122〜146.5)
  MAX_SCAN_TILES    = 64 （超過時は too_many_tiles で evaluated=False）
  PIXEL_STRIDE      = 2  （Phase 2-D.1: stride4 → stride2 で千葉沿岸強雨を捕捉）
  STRONG_PIXEL_THRESHOLD = 3
"""
from __future__ import annotations

import io
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCAN_ZOOM = 6
SCAN_BBOX = (24.0, 122.0, 46.5, 146.5)   # (lat_min, lng_min, lat_max, lng_max)
MAX_SCAN_TILES = 64
PIXEL_STRIDE = 2
STRONG_PIXEL_THRESHOLD = 3               # タイル内 strong+severe の最小ピクセル数
_MAX_SCAN_WORKERS = 8
_SCAN_TIMEOUT = 30.0                     # 全タイル取得の最大待ち時間（秒）
_TILE_SIZE = 256


# ── タイル座標計算 ────────────────────────────────────────────────────────────

def _lng_to_tile_x(lng: float, zoom: int) -> int:
    return int((lng + 180.0) / 360.0 * (2 ** zoom))


def _lat_to_tile_y(lat: float, zoom: int) -> int:
    lat_rad = math.radians(lat)
    y_frac = (
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * (2 ** zoom)
    )
    return int(y_frac)


def get_tile_coords(
    lat_min: float, lng_min: float, lat_max: float, lng_max: float, zoom: int
) -> List[Tuple[int, int]]:
    """bbox 内の全タイル座標リストを返す。WebMercator: Y は北ほど小さい。"""
    x_min = _lng_to_tile_x(lng_min, zoom)
    x_max = _lng_to_tile_x(lng_max, zoom)
    y_min = _lat_to_tile_y(lat_max, zoom)   # 北限 → 小さい Y
    y_max = _lat_to_tile_y(lat_min, zoom)   # 南限 → 大きい Y
    return [(tx, ty) for tx in range(x_min, x_max + 1) for ty in range(y_min, y_max + 1)]


def tile_center_lat_lng(tx: int, ty: int, zoom: int) -> Tuple[float, float]:
    """タイル中心の lat/lng を返す。"""
    n = 2 ** zoom
    lng = (tx + 0.5) / n * 360.0 - 180.0
    y_frac = (ty + 0.5) / n
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y_frac))))
    return lat, lng


def pixel_to_lat_lng(tx: int, ty: int, px: float, py: float, zoom: int) -> Tuple[float, float]:
    """タイル内のピクセル座標 (px, py) を lat/lng に変換する。重心計算に使用。"""
    n = 2 ** zoom
    x_frac = (tx + px / _TILE_SIZE) / n
    y_frac = (ty + py / _TILE_SIZE) / n
    lng = x_frac * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y_frac))))
    return lat, lng


# ── 都道府県推定（最近傍） ─────────────────────────────────────────────────────

def nearest_prefecture(
    lat: float, lng: float, sample_points: List[Dict[str, Any]]
) -> Dict[str, str]:
    """最近傍の代表点から prefecture / label を推定する。"""
    if not sample_points:
        return {"prefecture": "日本周辺", "label": "日本周辺"}
    best = min(sample_points, key=lambda p: (p["lat"] - lat) ** 2 + (p["lng"] - lng) ** 2)
    return {"prefecture": best["prefecture"], "label": best["label"]}


# ── タイル 1 枚スキャン（同期・ThreadPoolExecutor から呼ぶ） ──────────────────

def _scan_one_tile(
    tile_url_template: str,
    zoom: int,
    tx: int,
    ty: int,
    stride: int,
) -> Dict[str, Any]:
    """
    1 タイルをスキャンしてピクセル統計と strong/severe ピクセルの重心を返す。

    Returns:
        {
            "tx", "ty",
            "strong_count", "severe_count", "moderate_count",
            "unknown_count", "total_sampled",
            "fetch_failed": bool,
            "strong_x_sum": float,   # 重心算出用 X 座標の合計
            "strong_y_sum": float,   # 重心算出用 Y 座標の合計
            "strong_severe_count": int,  # 重心算出対象ピクセル数
        }
    """
    failed_result = {
        "tx": tx, "ty": ty,
        "strong_count": 0, "severe_count": 0,
        "moderate_count": 0, "unknown_count": 0,
        "total_sampled": 0, "fetch_failed": True,
        "strong_x_sum": 0.0, "strong_y_sum": 0.0, "strong_severe_count": 0,
    }

    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow not installed — cannot scan rain tile pixels")
        return failed_result

    try:
        from services.jma_rain_tile_service import _fetch_tile_png, _rgba_to_intensity
    except ImportError:
        logger.error("jma_rain_tile_service import failed")
        return failed_result

    url = (
        tile_url_template
        .replace("{z}", str(zoom))
        .replace("{x}", str(tx))
        .replace("{y}", str(ty))
    )

    raw = _fetch_tile_png(url)
    if raw is None:
        return failed_result

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        pixels = img.load()
        width, height = img.size

        strong = severe = moderate = unknown = total = 0
        strong_x_sum = strong_y_sum = 0.0
        strong_severe_count = 0

        for py in range(0, height, stride):
            for px in range(0, width, stride):
                rgba = pixels[px, py]
                r, g, b = rgba[0], rgba[1], rgba[2]
                a = rgba[3] if len(rgba) > 3 else 255
                intensity, _, _ = _rgba_to_intensity(r, g, b, a)
                total += 1
                if intensity == "strong":
                    strong += 1
                    strong_x_sum += px
                    strong_y_sum += py
                    strong_severe_count += 1
                elif intensity == "severe":
                    severe += 1
                    strong_x_sum += px
                    strong_y_sum += py
                    strong_severe_count += 1
                elif intensity == "moderate":
                    moderate += 1
                elif intensity == "unknown":
                    unknown += 1

        return {
            "tx": tx, "ty": ty,
            "strong_count": strong,
            "severe_count": severe,
            "moderate_count": moderate,
            "unknown_count": unknown,
            "total_sampled": total,
            "fetch_failed": False,
            "strong_x_sum": strong_x_sum,
            "strong_y_sum": strong_y_sum,
            "strong_severe_count": strong_severe_count,
        }
    except Exception as exc:
        logger.warning("_scan_one_tile parse failed tx=%d ty=%d: %s", tx, ty, exc)
        return failed_result


# ── メインスキャン関数 ────────────────────────────────────────────────────────

def scan_rain_tiles(
    tile_url_template: str,
    sample_points: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    日本周辺の雨雲タイルをグリッドスキャンして強雨域を検出する（同期版）。

    sample_points: 都道府県推定用の代表点リスト（None なら prefecture 推定なし）

    Returns:
        {
            "status":           "ok" | "too_many_tiles",
            "scan_tile_count":  int,
            "scan_pixel_stride": int,
            "tile_results":     [...],
            "areas":            [...],   # 全検出エリア（MAX_AREAS 制限前）
            "warning_area_count": int,
            "danger_area_count":  int,
            "unknown_count":    int,
        }
    """
    if sample_points is None:
        sample_points = []

    lat_min, lng_min, lat_max, lng_max = SCAN_BBOX
    tiles = get_tile_coords(lat_min, lng_min, lat_max, lng_max, SCAN_ZOOM)

    if len(tiles) > MAX_SCAN_TILES:
        logger.warning("scan_rain_tiles: too many tiles %d > %d", len(tiles), MAX_SCAN_TILES)
        return {
            "status":            "too_many_tiles",
            "scan_tile_count":   len(tiles),
            "scan_pixel_stride": PIXEL_STRIDE,
            "tile_results":      [],
            "areas":             [],
            "warning_area_count": None,
            "danger_area_count":  None,
            "unknown_count":     None,
        }

    tile_results: List[Dict[str, Any]] = []
    completed_futures: set = set()

    executor = ThreadPoolExecutor(max_workers=_MAX_SCAN_WORKERS)
    try:
        future_map = {
            executor.submit(_scan_one_tile, tile_url_template, SCAN_ZOOM, tx, ty, PIXEL_STRIDE): (tx, ty)
            for tx, ty in tiles
        }
        try:
            for future in as_completed(future_map, timeout=_SCAN_TIMEOUT):
                completed_futures.add(future)
                tx, ty = future_map[future]
                try:
                    tile_results.append(future.result())
                except Exception as exc:
                    logger.warning("scan tile future error tx=%d ty=%d: %s", tx, ty, exc)
                    tile_results.append({
                        "tx": tx, "ty": ty,
                        "strong_count": 0, "severe_count": 0,
                        "moderate_count": 0, "unknown_count": 0,
                        "total_sampled": 0, "fetch_failed": True,
                    })
        except Exception:
            logger.warning("scan_rain_tiles: timeout reached after %.1fs", _SCAN_TIMEOUT)

        # タイムアウトで未完了のタイルを failed として追加
        for future, (tx, ty) in future_map.items():
            if future not in completed_futures:
                tile_results.append({
                    "tx": tx, "ty": ty,
                    "strong_count": 0, "severe_count": 0,
                    "moderate_count": 0, "unknown_count": 0,
                    "total_sampled": 0, "fetch_failed": True,
                })
                future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # クラスタリング: strong+severe >= 閾値のタイルをエリアとして抽出
    all_areas: List[Dict[str, Any]] = []
    total_unknown = 0

    for res in tile_results:
        total_unknown += res.get("unknown_count", 0)
        strong = res.get("strong_count", 0)
        severe = res.get("severe_count", 0)

        if strong + severe < STRONG_PIXEL_THRESHOLD:
            continue

        # 重心座標で位置を決定（タイル中心より精度が高い）
        ss_count = res.get("strong_severe_count", 0)
        if ss_count > 0:
            centroid_px = res.get("strong_x_sum", 0.0) / ss_count
            centroid_py = res.get("strong_y_sum", 0.0) / ss_count
            lat, lng = pixel_to_lat_lng(res["tx"], res["ty"], centroid_px, centroid_py, SCAN_ZOOM)
        else:
            lat, lng = tile_center_lat_lng(res["tx"], res["ty"], SCAN_ZOOM)

        pref_info = nearest_prefecture(lat, lng, sample_points)
        level = "danger" if severe > 0 else "warning"

        logger.debug(
            "rain_scan candidate: tile=(%d,%d) strong=%d severe=%d centroid=(%.4f,%.4f) prefecture=%s",
            res["tx"], res["ty"], strong, severe, lat, lng, pref_info["prefecture"],
        )

        all_areas.append({
            "tx":          res["tx"],
            "ty":          res["ty"],
            "lat":         round(lat, 4),
            "lng":         round(lng, 4),
            "level":       level,
            "prefecture":  pref_info["prefecture"],
            "label":       f"{pref_info['prefecture']}付近",
            "strong_count": strong,
            "severe_count": severe,
        })

    warning_count = sum(1 for a in all_areas if a["level"] == "warning")
    danger_count  = sum(1 for a in all_areas if a["level"] == "danger")

    return {
        "status":             "ok",
        "scan_tile_count":    len(tiles),
        "scan_pixel_stride":  PIXEL_STRIDE,
        "tile_results":       tile_results,
        "areas":              all_areas,
        "warning_area_count": warning_count,
        "danger_area_count":  danger_count,
        "unknown_count":      total_unknown,
    }
