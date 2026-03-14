"""
標高データ処理サービス
基盤地図情報（数値標高モデル）から標高を取得し、避難目的地を検索
"""
import numpy as np
import rasterio
from rasterio.warp import transform
from typing import List, Tuple, Optional, Dict
import math
from pathlib import Path


class ElevationService:
    """標高データを管理し、避難目的地を検索するサービス"""
    
    def __init__(self, dem_path: str):
        """
        Args:
            dem_path: GeoTIFF形式の数値標高モデルのパス
        """
        self.dem_path = Path(dem_path)
        self.dataset = None
        self.elevation_data = None
        self.transform_matrix = None
        
        if self.dem_path.exists():
            self._load_dem()

    def is_loaded(self) -> bool:
        """DEM がロード済みか返す"""
        return self.dataset is not None and self.elevation_data is not None
    
    def _load_dem(self):
        """標高データを読み込む"""
        try:
            self.dataset = rasterio.open(self.dem_path)
            self.elevation_data = self.dataset.read(1)  # 最初のバンドを読み込み
            self.transform_matrix = self.dataset.transform
            print(f"標高データ読み込み完了: {self.dem_path}")
            print(f"データ範囲: {self.dataset.bounds}")
        except Exception as e:
            print(f"標高データ読み込みエラー: {e}")

    def _is_nodata(self, elevation: float) -> bool:
        """値がNoDataに該当するか判定"""
        if np.isnan(elevation):
            return True

        nodata = self.dataset.nodata if self.dataset is not None else None
        if nodata is None:
            return elevation < -9999

        if np.isnan(nodata):
            return np.isnan(elevation)

        return bool(np.isclose(elevation, nodata))

    def _coord_in_bounds(self, x: float, y: float) -> bool:
        """座標がラスタ範囲内にあるか判定"""
        bounds = self.dataset.bounds
        return bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top

    def contains(self, lat: float, lon: float) -> bool:
        """WGS84 座標が DEM 範囲内にあるか判定"""
        if self.dataset is None:
            return False

        x, y = self._to_dataset_xy(lat, lon)
        return self._coord_in_bounds(x, y)

    def _to_dataset_xy(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        WGS84緯度経度をDEMの座標系に変換し、必要に応じて軸入れ替えを補正
        """
        if self.dataset is None:
            return lon, lat

        x, y = lon, lat
        try:
            if self.dataset.crs is not None:
                xs, ys = transform("EPSG:4326", self.dataset.crs, [lon], [lat])
                x, y = xs[0], ys[0]
        except Exception:
            # 変換に失敗した場合は入力値をそのまま使う
            pass

        candidates = [(x, y), (y, x)]
        for cx, cy in candidates:
            if self._coord_in_bounds(cx, cy):
                return cx, cy

        return x, y
    
    def get_elevation(self, lat: float, lon: float) -> Optional[float]:
        """
        指定座標の標高を取得
        
        Args:
            lat: 緯度
            lon: 経度
            
        Returns:
            標高（メートル）、データ範囲外の場合はNone
        """
        if self.dataset is None:
            return None
        
        try:
            x, y = self._to_dataset_xy(lat, lon)

            # 緯度経度をピクセル座標に変換
            py, px = rasterio.transform.rowcol(
                self.transform_matrix, x, y
            )
            
            # データ範囲チェック
            if (0 <= py < self.elevation_data.shape[0] and 
                0 <= px < self.elevation_data.shape[1]):
                
                elevation = float(self.elevation_data[py, px])
                
                # NoData値のチェック
                if self._is_nodata(elevation):
                    return None
                    
                return elevation
            else:
                return None
                
        except Exception as e:
            print(f"標高取得エラー: {e}")
            return None
    
    def get_elevation_interpolated(self, lat: float, lon: float) -> Optional[float]:
        """
        双線形補間により精度の高い標高を取得
        
        Args:
            lat: 緯度
            lon: 経度
            
        Returns:
            補間された標高（メートル）
        """
        if self.dataset is None:
            return None
        
        try:
            x, y = self._to_dataset_xy(lat, lon)

            # 座標を浮動小数点のピクセル位置に変換
            px_float, py_float = ~self.transform_matrix * (x, y)
            
            # 整数部分と小数部分を取得
            py = int(math.floor(py_float))
            px = int(math.floor(px_float))
            dy = py_float - py
            dx = px_float - px
            
            # データ範囲チェック
            if (0 <= py < self.elevation_data.shape[0] - 1 and 
                0 <= px < self.elevation_data.shape[1] - 1):
                
                # 4隅の標高値を取得
                e00 = self.elevation_data[py, px]
                e10 = self.elevation_data[py, px + 1]
                e01 = self.elevation_data[py + 1, px]
                e11 = self.elevation_data[py + 1, px + 1]
                
                # NoData値チェック
                if any(self._is_nodata(float(e)) for e in [e00, e10, e01, e11]):
                    return self.get_elevation(lat, lon)
                
                # 双線形補間
                e0 = e00 * (1 - dx) + e10 * dx
                e1 = e01 * (1 - dx) + e11 * dx
                elevation = e0 * (1 - dy) + e1 * dy
                
                return float(elevation)
            else:
                return self.get_elevation(lat, lon)
                
        except Exception as e:
            print(f"補間標高取得エラー: {e}")
            return self.get_elevation(lat, lon)
    
    def calculate_distance(self, lat1: float, lon1: float, 
                          lat2: float, lon2: float) -> float:
        """
        2点間の距離を計算（ヒュベニの公式）
        
        Args:
            lat1, lon1: 地点1の緯度経度
            lat2, lon2: 地点2の緯度経度
            
        Returns:
            距離（メートル）
        """
        # 緯度経度をラジアンに変換
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        lon1_rad = math.radians(lon1)
        lon2_rad = math.radians(lon2)
        
        # 緯度差・経度差
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        # 平均緯度
        lat_avg = (lat1_rad + lat2_rad) / 2
        
        # 地球の半径（メートル）
        R = 6378137.0
        e2 = 0.00669438  # 地球の離心率の2乗
        
        # 子午線曲率半径
        M = R * (1 - e2) / math.pow(1 - e2 * math.sin(lat_avg) ** 2, 1.5)
        
        # 卯酉線曲率半径
        N = R / math.sqrt(1 - e2 * math.sin(lat_avg) ** 2)
        
        # 距離計算
        distance = math.sqrt((M * dlat) ** 2 + (N * math.cos(lat_avg) * dlon) ** 2)
        
        return distance
    
    def find_evacuation_destinations(
        self,
        current_lat: float,
        current_lon: float,
        min_elevation_gain: float = 10.0,
        max_distance: float = 2000.0,
        grid_size: int = 50,
        transport_mode: str = "walking"
    ) -> List[Dict]:
        """
        避難目的地候補を検索
        
        Args:
            current_lat: 現在地の緯度
            current_lon: 現在地の経度
            min_elevation_gain: 最低必要標高差（メートル）
            max_distance: 最大移動距離（メートル）
            grid_size: 検索グリッドのサイズ
            transport_mode: 移動手段（"walking" or "driving"）
            
        Returns:
            避難目的地候補のリスト
        """
        if self.dataset is None:
            return []
        
        # 現在地の標高
        current_elevation = self.get_elevation_interpolated(current_lat, current_lon)
        if current_elevation is None:
            return []
        
        # 目標標高
        target_elevation = current_elevation + min_elevation_gain
        
        # 検索範囲を計算（緯度経度の概算）
        # 1度あたりの距離（概算）
        lat_per_meter = 1.0 / 111000.0
        lon_per_meter = 1.0 / (111000.0 * math.cos(math.radians(current_lat)))
        
        search_radius_lat = max_distance * lat_per_meter
        search_radius_lon = max_distance * lon_per_meter
        
        candidates = []
        
        # グリッド検索
        for i in range(grid_size):
            for j in range(grid_size):
                # グリッド上の座標
                lat = current_lat + (i - grid_size/2) * (2 * search_radius_lat / grid_size)
                lon = current_lon + (j - grid_size/2) * (2 * search_radius_lon / grid_size)
                
                # 標高取得
                elevation = self.get_elevation(lat, lon)
                if elevation is None:
                    continue
                
                # 条件チェック
                if elevation >= target_elevation:
                    distance = self.calculate_distance(
                        current_lat, current_lon, lat, lon
                    )
                    
                    if distance <= max_distance:
                        # 移動手段による最大距離の調整
                        time_factor = 1.0 if transport_mode == "driving" else 1.5
                        estimated_time = (distance / 1000.0) * time_factor  # 徒歩時速4km想定
                        
                        candidates.append({
                            "lat": lat,
                            "lon": lon,
                            "elevation": elevation,
                            "elevation_gain": elevation - current_elevation,
                            "distance": distance,
                            "estimated_time_minutes": estimated_time * 15,  # 分に変換
                            "safety_score": self._calculate_safety_score(
                                elevation - current_elevation, distance
                            )
                        })
        
        # 安全性スコアでソート
        candidates.sort(key=lambda x: x["safety_score"], reverse=True)
        
        # 重複を除去（近接地点）
        filtered_candidates = self._remove_nearby_duplicates(candidates, 100.0)
        
        return filtered_candidates[:10]  # 上位10件
    
    def _calculate_safety_score(self, elevation_gain: float, distance: float) -> float:
        """
        避難地点の安全性スコアを計算
        
        Args:
            elevation_gain: 標高差
            distance: 距離
            
        Returns:
            安全性スコア（0-100）
        """
        # 標高差が大きいほど高スコア（最大50点）
        elevation_score = min(elevation_gain / 30.0 * 50, 50)
        
        # 距離が近いほど高スコア（最大50点）
        distance_score = max(50 - (distance / 2000.0 * 50), 0)
        
        return elevation_score + distance_score
    
    def _remove_nearby_duplicates(
        self, 
        candidates: List[Dict], 
        min_distance: float
    ) -> List[Dict]:
        """
        近接する候補地点を除去
        
        Args:
            candidates: 候補地点リスト
            min_distance: 最小距離（メートル）
            
        Returns:
            フィルタリングされた候補地点
        """
        filtered = []
        
        for candidate in candidates:
            is_duplicate = False
            
            for existing in filtered:
                distance = self.calculate_distance(
                    candidate["lat"], candidate["lon"],
                    existing["lat"], existing["lon"]
                )
                
                if distance < min_distance:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                filtered.append(candidate)
        
        return filtered
    
    def get_elevation_profile(
        self, 
        start_lat: float, 
        start_lon: float,
        end_lat: float, 
        end_lon: float,
        num_points: int = 50
    ) -> List[Dict]:
        """
        2点間の標高プロファイルを取得
        
        Args:
            start_lat, start_lon: 始点の緯度経度
            end_lat, end_lon: 終点の緯度経度
            num_points: サンプリングポイント数
            
        Returns:
            標高プロファイルのリスト
        """
        profile = []
        
        for i in range(num_points):
            t = i / (num_points - 1)
            lat = start_lat + t * (end_lat - start_lat)
            lon = start_lon + t * (end_lon - start_lon)
            
            elevation = self.get_elevation_interpolated(lat, lon)
            if elevation is not None:
                distance = self.calculate_distance(start_lat, start_lon, lat, lon)
                profile.append({
                    "distance": distance,
                    "elevation": elevation,
                    "lat": lat,
                    "lon": lon
                })
        
        return profile
