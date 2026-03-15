"""
ハザード判定サービス

現在地・候補地点がハザードエリア内かを判定する。
v1 実装: flood (洪水浸水想定) のみ対応。
tsunami / storm_surge / urban_flood は load() を追加するだけで拡張可能。
"""
import json
import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


def _point_in_polygon(lat: float, lon: float, ring: List[List[float]]) -> bool:
    """
    Ray casting algorithm によるポイントインポリゴン判定。

    Args:
        lat: 緯度
        lon: 経度
        ring: [[lon, lat], ...] の座標リスト (GeoJSON 外環形式)

    Returns:
        True = ポリゴン内
    """
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]  # lon, lat
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            # 経度の交差判定
            x_intersect = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_intersect:
                inside = not inside
        j = i
    return inside


class HazardService:
    """
    ハザードデータによるリスク判定サービス。

    各ハザードタイプごとに GeoJSON ポリゴンを保持し、
    任意座標がハザードエリア内かを高速に判定する。

    使い方:
        service = HazardService()
        service.load("flood", Path("tokyo_flood_max.geojson"))
        result = service.check_hazards(35.63, 139.59)
        # -> {"is_danger": True, "hazards": ["flood"]}
    """

    def __init__(self) -> None:
        # hazard_type -> list of {"bbox": (s, w, n, e), "coords": [[lon, lat], ...]}
        self._polygons: Dict[str, List[dict]] = {}

    # ------------------------------------------------------------------
    # データ読み込み
    # ------------------------------------------------------------------

    def load(self, hazard_type: str, geojson_path: Path) -> None:
        """
        指定ハザードタイプの GeoJSON ポリゴンを読み込む。

        Polygon / MultiPolygon の外環のみを保持（穴は無視）。
        将来の拡張: tsunami / storm_surge / urban_flood も同じ I/F で追加可能。

        Args:
            hazard_type: ハザードタイプ識別子 ("flood", "tsunami" など)
            geojson_path: GeoJSON ファイルのパス
        """
        if not geojson_path.exists():
            logger.warning(
                "Hazard data not found: type=%s path=%s", hazard_type, geojson_path
            )
            return

        logger.info(
            "Loading hazard polygons: type=%s path=%s", hazard_type, geojson_path
        )
        polygons: List[dict] = []

        try:
            with geojson_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            for feature in data.get("features", []):
                geom = feature.get("geometry") or {}
                geom_type = geom.get("type")
                outer_rings: List[List] = []

                if geom_type == "Polygon":
                    coords = geom.get("coordinates", [])
                    if coords:
                        outer_rings = [coords[0]]  # 外環のみ
                elif geom_type == "MultiPolygon":
                    for poly in geom.get("coordinates", []):
                        if poly:
                            outer_rings.append(poly[0])  # 各ポリゴンの外環

                for ring in outer_rings:
                    if len(ring) < 3:
                        continue
                    lons = [c[0] for c in ring]
                    lats = [c[1] for c in ring]
                    bbox = (min(lats), min(lons), max(lats), max(lons))  # (s, w, n, e)
                    polygons.append({"bbox": bbox, "coords": ring})

            self._polygons[hazard_type] = polygons
            logger.info(
                "Loaded %d polygons for hazard type '%s'", len(polygons), hazard_type
            )

        except Exception as e:
            logger.error(
                "Failed to load hazard data: type=%s error=%s", hazard_type, e
            )

    # ------------------------------------------------------------------
    # 判定メソッド
    # ------------------------------------------------------------------

    def is_loaded(self, hazard_type: str) -> bool:
        """指定ハザードタイプのデータが読み込まれているか"""
        return bool(self._polygons.get(hazard_type))

    def check_point(self, lat: float, lon: float, hazard_type: str) -> bool:
        """
        指定座標が特定ハザードエリア内かを判定。

        バウンディングボックスで事前フィルタリングした後、
        Ray casting でポリゴン内外を判定する。

        Args:
            lat: 緯度
            lon: 経度
            hazard_type: ハザードタイプ ("flood" など)

        Returns:
            True = 危険エリア内
        """
        polygons = self._polygons.get(hazard_type, [])
        for poly in polygons:
            s, w, n, e = poly["bbox"]
            # バウンディングボックス事前フィルタ（高速）
            if not (s <= lat <= n and w <= lon <= e):
                continue
            if _point_in_polygon(lat, lon, poly["coords"]):
                return True
        return False

    def check_hazards(self, lat: float, lon: float) -> Dict:
        """
        現在地に対する全ハザード判定結果を返す。

        Args:
            lat: 緯度
            lon: 経度

        Returns:
            {
                "is_danger": bool,
                "hazards": list[str]  # 該当するハザードタイプ一覧
            }
        """
        hazards: List[str] = []
        for hazard_type, polygons in self._polygons.items():
            if polygons and self.check_point(lat, lon, hazard_type):
                hazards.append(hazard_type)

        return {
            "is_danger": len(hazards) > 0,
            "hazards": hazards,
        }
