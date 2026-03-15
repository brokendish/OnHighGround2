"""
ハザード判定サービス

現在地・候補地点がハザードエリア内かを判定する。
v1.2 実装: multi-hazard 構造。flood をデフォルトロード。
tsunami / storm_surge / urban_flood は load() で追加可能。

判定値:
  "inside"  : ハザードエリア内
  "outside" : ハザードエリア外
  "unknown" : データ未ロード（判定不能）

hazard_safe 決定ルール:
  - いずれかの hazard が "inside"      → False
  - すべてのロード済み hazard が "outside" → True
  - "inside" は無いが 1つ以上 "unknown"  → None
  - ロード済み hazard が 0件             → None
"""
import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

HazardResult = Literal["inside", "outside", "unknown"]

# 既知のハザードタイプ一覧（拡張時はここに追加）
KNOWN_HAZARD_TYPES: List[str] = ["flood", "tsunami", "storm_surge", "urban_flood"]


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
            x_intersect = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_intersect:
                inside = not inside
        j = i
    return inside


def _centroid_of_ring(ring: List[List[float]]) -> Tuple[float, float]:
    """
    GeoJSON 外環 [[lon, lat], ...] の算術重心 (centroid_lat, centroid_lon) を返す。

    閉じたリング（最終点 == 先頭点）を想定し、重複する末尾点を除いて計算する。
    """
    n = len(ring) - 1  # 末尾の重複点を除く
    if n <= 0:
        return ring[0][1], ring[0][0]
    centroid_lon = sum(c[0] for c in ring[:n]) / n
    centroid_lat = sum(c[1] for c in ring[:n]) / n
    return centroid_lat, centroid_lon


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の球面距離をメートルで返す（Haversine 公式）。"""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def derive_hazard_safe(assessment: Dict[str, HazardResult]) -> Optional[bool]:
    """
    hazard_assessment dict から hazard_safe (Optional[bool]) を決定する。

    ルール:
      - いずれかが "inside"       → False
      - 1つ以上 "unknown" がある   → None  (inside がない場合)
      - すべて "outside"          → True
      - assessment が空           → None  (データなし)

    Args:
        assessment: {"flood": "inside"|"outside"|"unknown", ...}

    Returns:
        True / False / None
    """
    if not assessment:
        return None

    values = list(assessment.values())

    if "inside" in values:
        return False

    if "unknown" in values:
        return None

    # 全件 "outside"
    return True


class HazardService:
    """
    ハザードデータによるリスク判定サービス。

    各ハザードタイプごとに GeoJSON ポリゴンを保持し、
    任意座標のハザード評価を返す。

    使い方:
        service = HazardService()
        service.load("flood", Path("tokyo_flood_max.geojson"))

        # 現在地判定（後方互換）
        result = service.check_hazards(35.63, 139.59)
        # -> {"is_danger": True, "hazards": ["flood"]}

        # 候補地点の multi-hazard 評価
        assessment = service.assess_candidate(35.65, 139.61)
        # -> {"flood": "outside"}
        hazard_safe = derive_hazard_safe(assessment)
        # -> True
    """

    # 洪水浸水想定データはシミュレーション格子（約50m）ごとのポリゴンで構成されており、
    # 隣接格子間に小さなギャップが生じる。マップ表示（ベクタータイル）は
    # 隣接ポリゴンを結合して描画するため、格子間のギャップでも視覚的に浸水域に見える。
    # 判定時にギャップを埋めるバッファを設定する（単位: 度、約25m）。
    DEFAULT_FLOOD_PROXIMITY_BUFFER_DEG: float = 0.000225

    def __init__(self, flood_proximity_buffer_deg: Optional[float] = None) -> None:
        # hazard_type -> list of {"bbox": (s, w, n, e), "coords": [[lon, lat], ...]}
        self._polygons: Dict[str, List[dict]] = {}
        # hazard_type -> list of loaded file stems (e.g. ["tsunami_tokyo", "tsunami_kanagawa"])
        self._sources: Dict[str, List[str]] = {}
        self._flood_proximity_buffer_deg = max(
            0.0,
            flood_proximity_buffer_deg
            if flood_proximity_buffer_deg is not None
            else self.DEFAULT_FLOOD_PROXIMITY_BUFFER_DEG,
        )

    # ------------------------------------------------------------------
    # データ読み込み
    # ------------------------------------------------------------------

    def load(self, hazard_type: str, geojson_path: Path) -> None:
        """
        指定ハザードタイプの GeoJSON ポリゴンを読み込む（累積式）。

        同じ hazard_type に対して複数回呼び出すと、ポリゴンが累積される。
        例: 都県別に分かれた tsunami ファイルを順次ロードできる。

        Polygon / MultiPolygon の外環のみを保持（穴は無視）。

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
        new_polygons: List[dict] = []

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
                        outer_rings = [coords[0]]
                elif geom_type == "MultiPolygon":
                    for poly in geom.get("coordinates", []):
                        if poly:
                            outer_rings.append(poly[0])

                for ring in outer_rings:
                    if len(ring) < 3:
                        continue
                    lons = [c[0] for c in ring]
                    lats = [c[1] for c in ring]
                    bbox = (min(lats), min(lons), max(lats), max(lons))  # (s, w, n, e)
                    new_polygons.append({"bbox": bbox, "coords": ring})

            # 累積: 同じハザードタイプへの複数ファイルロードをサポート
            existing = self._polygons.get(hazard_type, [])
            existing.extend(new_polygons)
            self._polygons[hazard_type] = existing

            # ソース追跡（/health で何をロードしたか分かるようにする）
            existing_sources = self._sources.get(hazard_type, [])
            existing_sources.append(geojson_path.stem)
            self._sources[hazard_type] = existing_sources

            logger.info(
                "Loaded %d polygons from '%s' (total for '%s': %d)",
                len(new_polygons), geojson_path.name, hazard_type,
                len(self._polygons[hazard_type]),
            )

        except Exception as e:
            logger.error(
                "Failed to load hazard data: type=%s path=%s error=%s",
                hazard_type, geojson_path, e,
            )

    def load_geojsonl(
        self,
        hazard_type: str,
        geojsonl_path: Path,
        min_rank_prop: str = "",
        min_rank: int = 0,
    ) -> None:
        """
        GeoJSONL（1行1フィーチャ）をストリーミングで読み込む。

        通常の load() と異なり json.load() を使わず1行ずつ処理するため、
        大容量ファイル（数百MB超）でもピークメモリを最小限に抑えられる。

        Args:
            hazard_type:   ハザードタイプ識別子
            geojsonl_path: GeoJSONL ファイルのパス（.geojsonl）
            min_rank_prop: ランクフィルタに使うプロパティ名（空文字でフィルタなし）
            min_rank:      このランク以上のフィーチャのみロード（0でフィルタなし）
        """
        if not geojsonl_path.exists():
            logger.warning(
                "Hazard data not found: type=%s path=%s", hazard_type, geojsonl_path
            )
            return

        logger.info(
            "Loading hazard polygons (streaming): type=%s path=%s", hazard_type, geojsonl_path
        )
        new_polygons: List[dict] = []
        skipped = 0

        try:
            with geojsonl_path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        feature = json.loads(line)
                    except json.JSONDecodeError as e:
                        logger.warning("GeoJSONL parse error at line %d: %s", line_no, e)
                        continue

                    # ランクフィルタ
                    if min_rank_prop and min_rank > 0:
                        props = feature.get("properties") or {}
                        if props.get(min_rank_prop, 0) < min_rank:
                            skipped += 1
                            continue

                    geom = feature.get("geometry") or {}
                    geom_type = geom.get("type")
                    outer_rings: List[List] = []

                    if geom_type == "Polygon":
                        coords = geom.get("coordinates", [])
                        if coords:
                            outer_rings = [coords[0]]
                    elif geom_type == "MultiPolygon":
                        for poly in geom.get("coordinates", []):
                            if poly:
                                outer_rings.append(poly[0])

                    for ring in outer_rings:
                        if len(ring) < 3:
                            continue
                        lons = [c[0] for c in ring]
                        lats = [c[1] for c in ring]
                        bbox = (min(lats), min(lons), max(lats), max(lons))
                        new_polygons.append({"bbox": bbox, "coords": ring})

            existing = self._polygons.get(hazard_type, [])
            existing.extend(new_polygons)
            self._polygons[hazard_type] = existing

            existing_sources = self._sources.get(hazard_type, [])
            existing_sources.append(geojsonl_path.stem)
            self._sources[hazard_type] = existing_sources

            logger.info(
                "Loaded %d polygons from '%s' (skipped: %d, total for '%s': %d)",
                len(new_polygons), geojsonl_path.name, skipped,
                hazard_type, len(self._polygons[hazard_type]),
            )

        except Exception as e:
            logger.error(
                "Failed to load hazard data: type=%s path=%s error=%s",
                hazard_type, geojsonl_path, e,
            )

    def load_dir(
        self,
        hazard_type: str,
        dir_path: Path,
        pattern: str = "*.geojson",
    ) -> None:
        """
        ディレクトリ内のすべての GeoJSON ファイルを指定ハザードタイプとしてロードする。

        複数都県に分割されたデータ（tsunami など）を一括ロードするために使用する。

        Args:
            hazard_type: ハザードタイプ識別子 ("tsunami" など)
            dir_path: GeoJSON ファイルが格納されたディレクトリ
            pattern: glob パターン (デフォルト "*.geojson")
        """
        if not dir_path.is_dir():
            logger.warning(
                "Hazard directory not found: type=%s dir=%s", hazard_type, dir_path
            )
            return

        files = sorted(dir_path.glob(pattern))
        if not files:
            logger.warning(
                "No files matching '%s' in hazard dir: type=%s dir=%s",
                pattern, hazard_type, dir_path,
            )
            return

        logger.info(
            "Loading %d files for hazard type '%s' from %s",
            len(files), hazard_type, dir_path,
        )
        for f in files:
            self.load(hazard_type, f)

    # ------------------------------------------------------------------
    # 判定メソッド
    # ------------------------------------------------------------------

    def is_loaded(self, hazard_type: str) -> bool:
        """指定ハザードタイプのデータが読み込まれているか"""
        return bool(self._polygons.get(hazard_type))

    def loaded_hazard_types(self) -> List[str]:
        """ロード済みのハザードタイプ一覧"""
        return [k for k, v in self._polygons.items() if v]

    def get_polygon_store(self) -> Dict[str, List[dict]]:
        """内部ポリゴンストア全体を返す（RSA 計算などで使用）。"""
        return self._polygons

    def loaded_sources(self, hazard_type: str) -> List[str]:
        """指定ハザードタイプにロードされたファイルのステム一覧 (例: ["tsunami_tokyo"])"""
        return list(self._sources.get(hazard_type, []))

    def polygon_count(self, hazard_type: str) -> int:
        """指定ハザードタイプのポリゴン数"""
        return len(self._polygons.get(hazard_type, []))

    def check_point(self, lat: float, lon: float, hazard_type: str) -> bool:
        """
        指定座標が特定ハザードエリア内かを判定（後方互換メソッド）。

        バウンディングボックスで事前フィルタリング後、
        Ray casting でポリゴン内外を判定する。

        Args:
            lat: 緯度
            lon: 経度
            hazard_type: ハザードタイプ ("flood" など)

        Returns:
            True = 危険エリア内 / False = 範囲外 or データ未ロード
        """
        polygons = self._polygons.get(hazard_type, [])

        # --- 1次判定: 厳密なポリゴン内外判定 ---
        for poly in polygons:
            s, w, n, e = poly["bbox"]
            if not (s <= lat <= n and w <= lon <= e):
                continue
            if _point_in_polygon(lat, lon, poly["coords"]):
                return True

        # --- 2次判定（flood のみ）: 近傍バッファ判定 ---
        # 洪水浸水想定データは約50m格子単位のポリゴンで構成されており、
        # 隣接格子間に小さなギャップが生じる。ベクタータイル表示では隣接
        # ポリゴンを結合して描画するため、格子間でも視覚的に浸水域に見える。
        # ギャップを埋めるため、bbox を FLOOD_PROXIMITY_BUFFER_DEG だけ
        # 拡張してバッファ判定を行う（1次判定でヒットしなかった場合のみ）。
        if hazard_type == "flood":
            buf = self._flood_proximity_buffer_deg
            if buf > 0:
                for poly in polygons:
                    s, w, n, e = poly["bbox"]
                    if s - buf <= lat <= n + buf and w - buf <= lon <= e + buf:
                        # 点は bbox バッファ内（厳密な polygon 外）→ 近傍と判定
                        return True

        return False

    def check_point_assessment(
        self, lat: float, lon: float, hazard_type: str
    ) -> HazardResult:
        """
        指定座標の特定ハザードに対する3値評価を返す。

        Args:
            lat: 緯度
            lon: 経度
            hazard_type: ハザードタイプ

        Returns:
            "inside" / "outside" / "unknown"
        """
        if not self.is_loaded(hazard_type):
            return "unknown"
        return "inside" if self.check_point(lat, lon, hazard_type) else "outside"

    def assess_candidate(self, lat: float, lon: float) -> Dict[str, HazardResult]:
        """
        候補地点の全ロード済みハザードに対する評価 dict を返す。

        ロードされていないハザードタイプは "unknown" として含める。
        現時点でロード済みタイプが 0件なら空 dict を返す。

        Returns:
            {
                "flood": "inside" | "outside" | "unknown",
                "tsunami": "unknown",   # 未ロード時
                ...
            }
            ※ 返却される key はロード済みタイプのみ（"unknown" は含めない）
            ※ ただし将来の拡張に備え、ロード済みタイプに対して値を保証する
        """
        loaded = self.loaded_hazard_types()
        if not loaded:
            return {}

        assessment: Dict[str, HazardResult] = {}
        for hazard_type in loaded:
            assessment[hazard_type] = self.check_point_assessment(lat, lon, hazard_type)
        return assessment

    def get_tsunami_centroid_distance_m(
        self, lat: float, lon: float
    ) -> Optional[float]:
        """
        現在地が津波浸水想定ポリゴン内にある場合、
        そのポリゴン重心までの距離をメートルで返す。

        用途:
            Time Margin v1 の TTI（津波到達時間）近似計算の入力。
            距離 / 津波速度 ≈ 到達時間の近似値として使う。

        採用方式（v1 案A）:
            現在地が入っているポリゴンの算術重心を「津波の起点」とみなし、
            そこまでの距離を TTI の入力値とする。
            ポリゴン外縁に近いほど距離が大きく（余裕あり）、
            重心に近いほど距離が小さい（余裕なし）という性質を持つ。

        Returns:
            float: 重心までの距離（m）。現在地がポリゴン外 / データ未ロードの場合は None。
        """
        polygons = self._polygons.get("tsunami", [])
        for poly in polygons:
            s, w, n, e = poly["bbox"]
            if not (s <= lat <= n and w <= lon <= e):
                continue
            if _point_in_polygon(lat, lon, poly["coords"]):
                centroid_lat, centroid_lon = _centroid_of_ring(poly["coords"])
                return _haversine_m(lat, lon, centroid_lat, centroid_lon)
        return None

    def check_hazards(self, lat: float, lon: float) -> Dict:
        """
        現在地に対する全ハザード判定結果を返す（後方互換）。

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
