"""
Reachable Safe Area (RSA) 計算ユーティリティ

v1 モデル:
  到達可能円 (reachable circle) - ハザードポリゴン = Reachable Safe Area

  到達可能円:
    中心: ユーザー現在地
    半径: walking_speed_mps × tti_minutes × 60

  ハザードポリゴン:
    ロード済みの全 hazard（flood / tsunami / storm_surge / landslide / inland_flood /
    lowland_poor_drainage）の外周 ring。HazardService.hazard_rings_in_bbox() から取得する。

安全契約（EVACUATION-HAZARD-GEOMETRY-SAFETY、2026-10-12）:
  円に掛かる hazard の形状を 1 件でも取得できない、または形状演算に失敗した場合は、
  安全範囲を出さず status="unavailable"（exists=None）を返す。polygon を黙って捨てたり、
  差し引かずに円全体を安全範囲として返したりしない（危険区域の見落とし = 安全範囲の過大評価）。
  外周 ring だけを使い穴は無視する（穴の部分も危険側に数える）。

座標系:
  入力/出力: EPSG:4326 (lon/lat)
  バッファ計算: EPSG:3857 (Web Mercator, メートル単位)
"""

import logging
from typing import Callable, List, Sequence, Tuple

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import pyproj
    import shapely
    from shapely.geometry import Point, Polygon, mapping

    SHAPELY_AVAILABLE = True
    logger.info("geometry_utils: shapely/pyproj available — RSA calculation enabled")
except ImportError:
    SHAPELY_AVAILABLE = False
    logger.warning("geometry_utils: shapely/pyproj not available — RSA calculation disabled")

_CLIP_MARGIN_DEG = 1e-4  # 約 10m。円の接点で切り口が掛からず、float32 の bbox 丸めで候補を落とさない余白

# (s, w, n, e) → (外周 ring の list [(n, 2) lon/lat], 形状を取得できなかった hazard type の list)
HazardRingProvider = Callable[[float, float, float, float], Tuple[Sequence, List[str]]]


def _vectorized(transformer):
    """pyproj Transformer を shapely.transform 用（(N, 2) 配列 → (N, 2) 配列）にする。"""
    def _apply(xy):
        x, y = transformer.transform(xy[:, 0], xy[:, 1])
        return np.column_stack([x, y])
    return _apply


def _unavailable(radius_m: float, reason: str, hazard_types: List[str] = ()) -> dict:
    return {
        "status": "unavailable",
        "reason": reason,
        "unavailable_hazard_types": sorted(hazard_types),
        "radius_m": round(radius_m, 1),
        "area_m2": None,
        "exists": None,
        "geometry": None,
    }


def calc_reachable_safe_area(
    user_lat: float,
    user_lon: float,
    radius_m: float,
    hazard_rings: HazardRingProvider,
) -> dict:
    """
    Reachable Safe Area (到達可能安全エリア) を計算する。

    到達可能円からハザードポリゴンを差し引き、
    安全に到達できるエリアを GeoJSON Geometry として返す。

    Args:
        user_lat: ユーザー緯度
        user_lon: ユーザー経度
        radius_m: 到達可能半径（メートル）
        hazard_rings: HazardService.hazard_rings_in_bbox（bbox → (rings, unavailable_types)）

    Returns:
        {
            "status": "computed" | "unavailable",
            "reason": str | None,
            "unavailable_hazard_types": list[str],
            "radius_m": float,
            "area_m2": float | None,   # unavailable のとき None
            "exists": bool | None,     # unavailable のとき None（安全とも危険とも言わない）
            "geometry": dict | None    # GeoJSON Geometry (EPSG:4326)
        }
    """
    if not SHAPELY_AVAILABLE:
        return _unavailable(radius_m, "shapely_unavailable")

    # 座標変換器 (always_xy: lon/lat 順序を明示)
    to_3857 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    to_4326 = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

    # ユーザー位置を EPSG:3857 に変換 → 到達可能円を生成
    user_x, user_y = to_3857.transform(user_lon, user_lat)
    reachable_3857 = Point(user_x, user_y).buffer(radius_m, resolution=32)

    # 到達可能円の EPSG:4326 bbox を算出してハザードの候補を絞る
    bounds_3857 = reachable_3857.bounds  # (minx, miny, maxx, maxy)
    sw_lon, sw_lat = to_4326.transform(bounds_3857[0], bounds_3857[1])
    ne_lon, ne_lat = to_4326.transform(bounds_3857[2], bounds_3857[3])

    try:
        # 候補の bbox は float32 で保持されている（端が約 1m 内側へ丸まりうる）ので、少し広く問い合わせる
        rings, unavailable = hazard_rings(sw_lat - _CLIP_MARGIN_DEG, sw_lon - _CLIP_MARGIN_DEG,
                                          ne_lat + _CLIP_MARGIN_DEG, ne_lon + _CLIP_MARGIN_DEG)
    except Exception:
        logger.exception(
            "RSA unavailable: hazard geometry lookup failed user=(%.5f,%.5f) radius=%.0fm",
            user_lat, user_lon, radius_m,
        )
        return _unavailable(radius_m, "hazard_geometry_error")
    if unavailable:
        logger.warning(
            "RSA unavailable: user=(%.5f,%.5f) radius=%.0fm hazard geometry unavailable for %s",
            user_lat, user_lon, radius_m, sorted(unavailable),
        )
        return _unavailable(radius_m, "hazard_geometry_unavailable", unavailable)

    clip_rect = (sw_lon - _CLIP_MARGIN_DEG, sw_lat - _CLIP_MARGIN_DEG,
                 ne_lon + _CLIP_MARGIN_DEG, ne_lat + _CLIP_MARGIN_DEG)
    try:
        hazard_geoms_4326 = []
        for ring in rings:
            if len(ring) < 3:
                continue  # 面積を持たない（危険区域としての広がりが無い）
            shp = Polygon(ring)
            # 円の bbox の外側は結果に影響しないので先に切り落とし（巨大な ring の演算量を抑える）、
            # 自己交差等の不正な形は切った後で修正して使う（捨てない）。切り取りに失敗したら全体を修正してから切る。
            try:
                part = shapely.clip_by_rect(shp, *clip_rect)
            except shapely.errors.GEOSException:
                part = shapely.clip_by_rect(shapely.make_valid(shp), *clip_rect)
            shp = part if part.is_valid else shapely.make_valid(part)
            if not shp.is_empty:
                hazard_geoms_4326.append(shp)

        # 安全エリア = 到達可能円 - ハザード領域
        if hazard_geoms_4326:
            hazard_union_4326 = shapely.union_all(hazard_geoms_4326)
            hazard_3857 = shapely.transform(hazard_union_4326, _vectorized(to_3857))
            safe_3857 = reachable_3857.difference(hazard_3857)
        else:
            safe_3857 = reachable_3857
        area_m2 = safe_3857.area
        geojson = mapping(shapely.transform(safe_3857, _vectorized(to_4326))) if area_m2 > 0 else None
    except Exception:
        # 差し引けなかった円を安全範囲として返さない（以前は円全体へ fallback していた）
        logger.exception(
            "RSA unavailable: hazard geometry operation failed user=(%.5f,%.5f) radius=%.0fm polygons=%d",
            user_lat, user_lon, radius_m, len(rings),
        )
        return _unavailable(radius_m, "hazard_geometry_error")

    logger.info(
        "RSA computed: radius=%.0fm area=%.0fm2 exists=%s hazard_polys=%d",
        radius_m, area_m2, area_m2 > 0, len(hazard_geoms_4326),
    )

    return {
        "status": "computed",
        "reason": None,
        "unavailable_hazard_types": [],
        "radius_m": round(radius_m, 1),
        "area_m2": round(area_m2, 0),
        "exists": area_m2 > 0,
        "geometry": geojson,
    }
