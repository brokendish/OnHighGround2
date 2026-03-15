"""
Reachable Safe Area (RSA) 計算ユーティリティ

v1 モデル:
  到達可能円 (reachable circle) - ハザードポリゴン = Reachable Safe Area

  到達可能円:
    中心: ユーザー現在地
    半径: walking_speed_mps × tti_minutes × 60

  ハザードポリゴン:
    HazardService._polygons から取得（flood / tsunami など）

座標系:
  入力/出力: EPSG:4326 (lon/lat)
  バッファ計算: EPSG:3857 (Web Mercator, メートル単位)
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import pyproj
    from shapely.geometry import Point, Polygon, mapping
    from shapely.ops import transform, unary_union

    SHAPELY_AVAILABLE = True
    logger.info("geometry_utils: shapely/pyproj available — RSA calculation enabled")
except ImportError:
    SHAPELY_AVAILABLE = False
    logger.warning("geometry_utils: shapely/pyproj not available — RSA calculation disabled")


def _bbox_overlaps(
    s1: float, w1: float, n1: float, e1: float,
    s2: float, w2: float, n2: float, e2: float,
) -> bool:
    """2つのバウンディングボックスが重なるか判定する。"""
    return not (s1 > n2 or n1 < s2 or w1 > e2 or e1 < w2)


def calc_reachable_safe_area(
    user_lat: float,
    user_lon: float,
    radius_m: float,
    hazard_polygon_store: Dict[str, List[dict]],
    hazard_types: Optional[List[str]] = None,
) -> dict:
    """
    Reachable Safe Area (到達可能安全エリア) を計算する。

    到達可能円からハザードポリゴンを差し引き、
    安全に到達できるエリアを GeoJSON Geometry として返す。

    Args:
        user_lat: ユーザー緯度
        user_lon: ユーザー経度
        radius_m: 到達可能半径（メートル）
        hazard_polygon_store: HazardService.get_polygon_store() の戻り値
            {hazard_type: [{"bbox": (s,w,n,e), "coords": [[lon,lat],...]}]}
        hazard_types: 使用するハザードタイプ (None = 全タイプ)

    Returns:
        {
            "radius_m": float,
            "area_m2": float,
            "exists": bool,
            "geometry": dict | None   # GeoJSON Geometry (EPSG:4326)
        }
    """
    if not SHAPELY_AVAILABLE:
        return {
            "radius_m": round(radius_m, 1),
            "area_m2": 0.0,
            "exists": False,
            "geometry": None,
            "error": "shapely/pyproj not available",
        }

    # 座標変換器 (always_xy: lon/lat 順序を明示)
    to_3857 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    to_4326 = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

    # ユーザー位置を EPSG:3857 に変換 → 到達可能円を生成
    user_x, user_y = to_3857.transform(user_lon, user_lat)
    reachable_3857 = Point(user_x, user_y).buffer(radius_m, resolution=32)

    # 到達可能円の EPSG:4326 bbox を算出してハザードフィルタに使う
    bounds_3857 = reachable_3857.bounds  # (minx, miny, maxx, maxy)
    sw_lon, sw_lat = to_4326.transform(bounds_3857[0], bounds_3857[1])
    ne_lon, ne_lat = to_4326.transform(bounds_3857[2], bounds_3857[3])
    circle_bbox = (sw_lat, sw_lon, ne_lat, ne_lon)  # (s, w, n, e)

    # 使用するハザードタイプを決定
    if hazard_types is None:
        selected_types = list(hazard_polygon_store.keys())
    else:
        selected_types = [t for t in hazard_types if t in hazard_polygon_store]

    # bbox で絞り込んでハザードポリゴンを shapely Polygon (EPSG:4326) に変換
    hazard_geoms_4326: List[Polygon] = []
    for htype in selected_types:
        for poly in hazard_polygon_store.get(htype, []):
            s, w, n, e = poly["bbox"]
            if not _bbox_overlaps(s, w, n, e, *circle_bbox):
                continue
            coords = poly["coords"]
            if len(coords) < 3:
                continue
            try:
                shp = Polygon([(c[0], c[1]) for c in coords])
                if shp.is_valid and not shp.is_empty:
                    hazard_geoms_4326.append(shp)
            except Exception:
                pass

    logger.debug(
        "RSA: user=(%.5f,%.5f) radius=%.0fm hazard_polys_in_bbox=%d",
        user_lat, user_lon, radius_m, len(hazard_geoms_4326),
    )

    # 安全エリア = 到達可能円 - ハザード領域
    if hazard_geoms_4326:
        try:
            hazard_union_4326 = unary_union(hazard_geoms_4326)
            hazard_3857 = transform(to_3857.transform, hazard_union_4326)
            safe_3857 = reachable_3857.difference(hazard_3857)
        except Exception as e:
            logger.warning("RSA difference failed: %s — using full reachable circle", e)
            safe_3857 = reachable_3857
    else:
        safe_3857 = reachable_3857

    area_m2 = safe_3857.area

    # EPSG:4326 に戻して GeoJSON 化
    geojson = None
    if area_m2 > 0:
        try:
            safe_4326 = transform(to_4326.transform, safe_3857)
            geojson = mapping(safe_4326)
        except Exception as e:
            logger.warning("RSA GeoJSON conversion failed: %s", e)

    logger.info(
        "RSA computed: radius=%.0fm area=%.0fm2 exists=%s hazard_polys=%d",
        radius_m, area_m2, area_m2 > 0, len(hazard_geoms_4326),
    )

    return {
        "radius_m": round(radius_m, 1),
        "area_m2": round(area_m2, 0),
        "exists": area_m2 > 0,
        "geometry": geojson,
    }
