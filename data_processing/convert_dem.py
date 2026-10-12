"""
基盤地図情報（数値標高モデル）変換スクリプト
JPGIS形式のXMLファイルをGeoTIFF形式に変換

座標契約（DEM-RUNTIME-REPAIR、2026-10-12）:
  - gml:lowerCorner / upperCorner は「緯度 経度」の順。west/east = 経度、south/north = 緯度として
    標準的な GeoTIFF（x = 経度、y = 緯度、行 = 北→南、列 = 西→東）を作る。
    以前は緯度を west/east に渡していたため、merge で 3 次メッシュの配置だけが転置されていた
    （docs/audits/dem_elevation_integrity_20261012.md）。
  - 3 次メッシュ内の配列（sequenceRule +x-y、行 = 北→南、列 = 西→東）は以前から正しい。
  - データの無い cell・原本 tile の無い範囲は NODATA（-9999）。以前は merge が 0 で埋めていた（海 ≠ 標高 0 m）。
  - 入力 XML は path の昇順で処理する。同じ範囲の XML が複数あれば結合しない（fail closed）。
"""
import xml.etree.ElementTree as ET
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from pathlib import Path
import sys
from typing import List, Tuple

NODATA = -9999.0  # 基盤地図情報 DEM の欠測値と同じ。backend（elevation_service）も -9999 以下を欠測として扱う

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
        
        # 複数のDEM要素がある場合は、範囲情報だけ統合（標高配列は最初の有効DEMを使用）
        elevation_array = None
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
            
            # lowerCorner / upperCorner は「緯度 経度」の順（JPGIS 2008 / FGD GML）
            south, west = min(lower[0], upper[0]), min(lower[1], upper[1])
            north, east = max(lower[0], upper[0]), max(lower[1], upper[1])
            
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
            low = coverage.find('.//gml:low', self.namespaces)
            high = coverage.find('.//gml:high', self.namespaces)
            if low is None or high is None:
                continue

            low_xy = [int(x) for x in low.text.split()]
            high_xy = [int(x) for x in high.text.split()]
            width = high_xy[0] - low_xy[0] + 1
            height = high_xy[1] - low_xy[1] + 1
            mesh_size = [width, height]
            
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

                expected_size = width * height

                # GridFunction の startPoint を考慮:
                # tupleListが(0,0)から始まらないXMLでは先頭セルが省略される
                start_point = coverage.find('.//gml:startPoint', self.namespaces)
                if start_point is not None and start_point.text:
                    sx, sy = [int(x) for x in start_point.text.split()]
                else:
                    sx, sy = 0, 0

                start_index = (sy - low_xy[1]) * width + (sx - low_xy[0])
                if start_index < 0 or start_index >= expected_size:
                    raise ValueError(
                        f"startPointがグリッド範囲外です: startPoint=({sx},{sy}), "
                        f"grid_low=({low_xy[0]},{low_xy[1]}), grid_high=({high_xy[0]},{high_xy[1]})"
                    )

                if len(data_values) > expected_size:
                    raise ValueError(
                        f"tupleList件数がグリッドサイズを超えています: "
                        f"count={len(data_values)}, expected={expected_size}"
                    )

                flat = np.full(expected_size, np.nan, dtype=np.float32)

                # startPoint起点の線形配列として格納。終端を超える場合は先頭にラップ。
                for i, val in enumerate(data_values):
                    flat[(start_index + i) % expected_size] = val

                # 行 = 北→南（緯度）、列 = 西→東（経度）。読めなかった cell・tupleList に無い cell は NODATA
                elevation_array = np.where(np.isnan(flat), NODATA, flat).astype(np.float32).reshape(height, width)
                break
        
        if elevation_array is None or bounds is None or mesh_size is None:
            raise ValueError("必要なデータが取得できませんでした")
        
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
            nodata=NODATA,
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
        # XMLをパース
        elevation_data, metadata = self.parse_jpgis_xml(input_xml)
        
        # GeoTIFFとして保存
        self.save_as_geotiff(elevation_data, metadata, output_tif)
        
        # 統計情報を表示
        valid_data = elevation_data[
            (~np.isnan(elevation_data)) & (elevation_data > NODATA)
        ]
        print("\n=== 統計情報 ===")
        if valid_data.size == 0:
            print("有効標高データがありません")
        else:
            print(f"最小標高: {valid_data.min():.2f} m")
            print(f"最大標高: {valid_data.max():.2f} m")
            print(f"平均標高: {valid_data.mean():.2f} m")


def _merge_group(input_files: List[str], output_file: str):
    """
    指定グループのGeoTIFFを1つに結合
    """
    from rasterio.merge import merge

    src_files = []
    try:
        src_files = [rasterio.open(f) for f in input_files]
        # 原本 tile の無い範囲は NODATA で埋める（nodata 未指定だと 0 で埋まり、海が標高 0 m になる）
        mosaic, transform = merge(src_files, nodata=NODATA)

        meta = src_files[0].meta.copy()
        meta.update({
            'height': mosaic.shape[1],
            'width': mosaic.shape[2],
            'transform': transform,
            'nodata': NODATA,
            'compress': 'lzw'
        })

        with rasterio.open(output_file, 'w', **meta) as dst:
            dst.write(mosaic)
    finally:
        for src in src_files:
            src.close()


def merge_geotiffs(input_files: List[str], output_file: str, max_open_files: int = 128):
    """
    複数のGeoTIFFファイルを結合
    
    Args:
        input_files: 入力GeoTIFFファイルのリスト
        output_file: 出力GeoTIFFファイルパス
    """
    if max_open_files < 2:
        raise ValueError("max_open_files は2以上を指定してください")

    print(f"{len(input_files)}個のGeoTIFFファイルを結合中...")

    output_path = Path(output_file)
    round_paths = [Path(f) for f in input_files]
    created_intermediates = []
    round_index = 0

    while len(round_paths) > 1:
        next_round = []
        group_count = (len(round_paths) + max_open_files - 1) // max_open_files
        print(f" - ラウンド{round_index + 1}: {len(round_paths)}ファイルを{group_count}グループで結合")

        for group_index in range(0, len(round_paths), max_open_files):
            group = round_paths[group_index:group_index + max_open_files]
            if len(group) == 1:
                next_round.append(group[0])
                continue

            intermediate = (
                output_path.parent
                / f".merge_round_{round_index}_{group_index // max_open_files}.tif"
            )
            _merge_group([str(p) for p in group], str(intermediate))
            created_intermediates.append(intermediate)
            next_round.append(intermediate)

        round_paths = next_round
        round_index += 1

    final_path = round_paths[0]
    if final_path != output_path:
        if output_path.exists():
            output_path.unlink()
        final_path.rename(output_path)

    # 中間ファイルを削除（最終出力を除く）
    for p in created_intermediates:
        if p != output_path and p.exists():
            p.unlink()

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
            # 決定的な順序（file system の列挙順に依存しない）
            xml_files = sorted(input_path.glob('*.xml'))
        else:
            xml_files = [input_path]
        
        if not xml_files:
            print("XMLファイルが見つかりません", file=sys.stderr)
            sys.exit(1)
        
        print(f"{len(xml_files)}個のXMLファイルを処理します")
        
        # 一時ファイルに変換
        temp_tiffs = []
        failed_files = []
        seen_bounds = {}
        for i, xml_file in enumerate(xml_files):
            temp_tif = output_path.parent / f"temp_{i}.tif"
            print(f"\n[{i+1}/{len(xml_files)}] {xml_file.name}")
            try:
                converter.convert(str(xml_file), str(temp_tif))
                temp_tiffs.append(str(temp_tif))
            except Exception as e:
                print(f"警告: {xml_file.name} をスキップします ({e})", file=sys.stderr)
                failed_files.append(xml_file.name)
                continue
            with rasterio.open(temp_tif) as src:
                key = tuple(round(v, 9) for v in src.bounds)
            if key in seen_bounds:
                # 同じメッシュの XML が複数ある（DEM5A と 5B 等）。どちらを使うかを黙って決めない
                for t in temp_tiffs:
                    Path(t).unlink(missing_ok=True)
                print(f"エラー: 同じ範囲の XML が複数あります: {seen_bounds[key]} と {xml_file.name}"
                      "（どちらを使うか決めてから入力を 1 つにしてください）", file=sys.stderr)
                sys.exit(2)
            seen_bounds[key] = xml_file.name
        
        if not temp_tiffs:
            print("変換に成功したXMLファイルがありません", file=sys.stderr)
            sys.exit(1)
        
        # 結合
        if len(temp_tiffs) > 1:
            print("\n結合処理を開始")
            merge_geotiffs(temp_tiffs, str(output_path))
            
            # 一時ファイルを削除
            for temp_tif in temp_tiffs:
                Path(temp_tif).unlink(missing_ok=True)
        else:
            # 1ファイルのみの場合はリネーム
            Path(temp_tiffs[0]).rename(output_path)

        if failed_files:
            print(f"\n警告: {len(failed_files)}ファイルをスキップしました")
            for name in failed_files[:20]:
                print(f" - {name}")
            if len(failed_files) > 20:
                print(f" ... 他 {len(failed_files) - 20} 件")
    else:
        # 単一ファイルの変換
        try:
            converter.convert(str(input_path), str(output_path))
        except Exception as e:
            print(f"エラー: {e}", file=sys.stderr)
            sys.exit(1)
    
    print("\n完了！")


if __name__ == "__main__":
    main()
