"""
基盤地図情報（数値標高モデル）変換スクリプト
JPGIS形式のXMLファイルをGeoTIFF形式に変換
"""
import xml.etree.ElementTree as ET
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from pathlib import Path
import sys
from typing import List, Tuple


class DEMConverter:
    """数値標高モデル変換クラス"""
    
    def __init__(self):
        self.namespaces = {
            'gml': 'http://www.opengis.net/gml/3.2',
            'ns': 'http://fgd.gsi.go.jp/spec/2008/FGD_GMLSchema'
        }
    
    def parse_jpgis_xml(self, xml_path: str) -> Tuple[np.ndarray, dict]:
        """
        JPGIS形式のXMLファイルをパース
        
        Args:
            xml_path: XMLファイルのパス
            
        Returns:
            (標高データ配列, メタデータ辞書)
        """
        print(f"XMLファイルをパース中: {xml_path}")
        
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # DEM（数値標高モデル）要素を検索
        dem_elements = root.findall('.//ns:DEM', self.namespaces)
        
        if not dem_elements:
            raise ValueError("DEM要素が見つかりません")
        
        # 複数のDEM要素がある場合は結合
        all_data = []
        bounds = None
        mesh_size = None
        
        for dem in dem_elements:
            # メッシュ範囲を取得
            coverage = dem.find('.//ns:coverage', self.namespaces)
            if coverage is None:
                continue
            
            # 境界座標を取得
            lower_corner = coverage.find('.//gml:lowerCorner', self.namespaces)
            upper_corner = coverage.find('.//gml:upperCorner', self.namespaces)
            
            if lower_corner is None or upper_corner is None:
                continue
            
            lower = [float(x) for x in lower_corner.text.split()]
            upper = [float(x) for x in upper_corner.text.split()]
            
            # 低い座標と高い座標から境界を設定
            west, south = min(lower[0], upper[0]), min(lower[1], upper[1])
            east, north = max(lower[0], upper[0]), max(lower[1], upper[1])
            
            if bounds is None:
                bounds = [west, south, east, north]
            else:
                bounds = [
                    min(bounds[0], west),
                    min(bounds[1], south),
                    max(bounds[2], east),
                    max(bounds[3], north)
                ]
            
            # グリッドサイズを取得
            high = coverage.find('.//gml:high', self.namespaces)
            if high is not None:
                mesh_size = [int(x) + 1 for x in high.text.split()]
            
            # 標高データを取得
            tuple_list = coverage.find('.//gml:tupleList', self.namespaces)
            if tuple_list is not None:
                data_text = tuple_list.text.strip()
                # カンマ区切りのデータをパース
                data_values = []
                for line in data_text.split('\n'):
                    line = line.strip()
                    if line:
                        # 各行は "種別,標高,..." の形式
                        parts = line.split(',')
                        if len(parts) >= 2:
                            try:
                                # 2番目の値が標高
                                elevation = float(parts[1])
                                data_values.append(elevation)
                            except ValueError:
                                data_values.append(np.nan)
                
                all_data.extend(data_values)
        
        if not all_data or bounds is None or mesh_size is None:
            raise ValueError("必要なデータが取得できませんでした")
        
        # NumPy配列に変換
        elevation_array = np.array(all_data, dtype=np.float32)
        elevation_array = elevation_array.reshape(mesh_size[1], mesh_size[0])
        
        # メタデータ
        metadata = {
            'bounds': bounds,  # [west, south, east, north]
            'width': mesh_size[0],
            'height': mesh_size[1],
            'crs': 'EPSG:6668'  # 日本測地系2011（JGD2011）
        }
        
        print(f"データ取得完了: {metadata['width']}x{metadata['height']} ピクセル")
        print(f"範囲: {bounds}")
        
        return elevation_array, metadata
    
    def save_as_geotiff(
        self, 
        elevation_data: np.ndarray, 
        metadata: dict, 
        output_path: str
    ):
        """
        標高データをGeoTIFF形式で保存
        
        Args:
            elevation_data: 標高データ配列
            metadata: メタデータ
            output_path: 出力ファイルパス
        """
        print(f"GeoTIFFファイルを作成中: {output_path}")
        
        bounds = metadata['bounds']
        transform = from_bounds(
            bounds[0], bounds[1], bounds[2], bounds[3],
            metadata['width'], metadata['height']
        )
        
        # GeoTIFFとして保存
        with rasterio.open(
            output_path,
            'w',
            driver='GTiff',
            height=metadata['height'],
            width=metadata['width'],
            count=1,
            dtype=elevation_data.dtype,
            crs=metadata['crs'],
            transform=transform,
            compress='lzw'  # 圧縮を有効化
        ) as dst:
            dst.write(elevation_data, 1)
        
        print(f"GeoTIFF作成完了: {output_path}")
    
    def convert(self, input_xml: str, output_tif: str):
        """
        JPGIS XMLからGeoTIFFへ変換
        
        Args:
            input_xml: 入力XMLファイルパス
            output_tif: 出力GeoTIFFファイルパス
        """
        try:
            # XMLをパース
            elevation_data, metadata = self.parse_jpgis_xml(input_xml)
            
            # GeoTIFFとして保存
            self.save_as_geotiff(elevation_data, metadata, output_tif)
            
            # 統計情報を表示
            valid_data = elevation_data[~np.isnan(elevation_data)]
            print("\n=== 統計情報 ===")
            print(f"最小標高: {valid_data.min():.2f} m")
            print(f"最大標高: {valid_data.max():.2f} m")
            print(f"平均標高: {valid_data.mean():.2f} m")
            
        except Exception as e:
            print(f"エラー: {e}", file=sys.stderr)
            raise


def merge_geotiffs(input_files: List[str], output_file: str):
    """
    複数のGeoTIFFファイルを結合
    
    Args:
        input_files: 入力GeoTIFFファイルのリスト
        output_file: 出力GeoTIFFファイルパス
    """
    from rasterio.merge import merge
    
    print(f"{len(input_files)}個のGeoTIFFファイルを結合中...")
    
    # ファイルを開く
    src_files = [rasterio.open(f) for f in input_files]
    
    # 結合
    mosaic, transform = merge(src_files)
    
    # メタデータをコピー
    meta = src_files[0].meta.copy()
    meta.update({
        'height': mosaic.shape[1],
        'width': mosaic.shape[2],
        'transform': transform,
        'compress': 'lzw'
    })
    
    # 保存
    with rasterio.open(output_file, 'w', **meta) as dst:
        dst.write(mosaic)
    
    # クローズ
    for src in src_files:
        src.close()
    
    print(f"結合完了: {output_file}")


def main():
    """メイン処理"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='基盤地図情報（数値標高モデル）の変換'
    )
    parser.add_argument(
        'input',
        help='入力XMLファイルまたはディレクトリ'
    )
    parser.add_argument(
        'output',
        help='出力GeoTIFFファイル'
    )
    parser.add_argument(
        '--merge',
        action='store_true',
        help='複数のXMLファイルを結合'
    )
    
    args = parser.parse_args()
    
    converter = DEMConverter()
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    if input_path.is_dir() or args.merge:
        # ディレクトリ内の全XMLファイルを変換して結合
        if input_path.is_dir():
            xml_files = list(input_path.glob('*.xml'))
        else:
            xml_files = [input_path]
        
        if not xml_files:
            print("XMLファイルが見つかりません", file=sys.stderr)
            sys.exit(1)
        
        print(f"{len(xml_files)}個のXMLファイルを処理します")
        
        # 一時ファイルに変換
        temp_tiffs = []
        for i, xml_file in enumerate(xml_files):
            temp_tif = output_path.parent / f"temp_{i}.tif"
            print(f"\n[{i+1}/{len(xml_files)}] {xml_file.name}")
            converter.convert(str(xml_file), str(temp_tif))
            temp_tiffs.append(str(temp_tif))
        
        # 結合
        if len(temp_tiffs) > 1:
            print("\n結合処理を開始")
            merge_geotiffs(temp_tiffs, str(output_path))
            
            # 一時ファイルを削除
            for temp_tif in temp_tiffs:
                Path(temp_tif).unlink()
        else:
            # 1ファイルのみの場合はリネーム
            Path(temp_tiffs[0]).rename(output_path)
    else:
        # 単一ファイルの変換
        converter.convert(str(input_path), str(output_path))
    
    print("\n完了！")


if __name__ == "__main__":
    main()
