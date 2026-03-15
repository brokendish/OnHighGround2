#!/usr/bin/env python3
"""
洪水浸水想定区域（想定最大規模）GML → GeoJSON 変換スクリプト

入力:
  data_lake/raw/tokyo/flood/A31a-24_13_10_GML/20_想定最大規模/*.xml  (A31a: 都管理河川)
  data_lake/raw/tokyo/flood/A31a-24_13_20_GML/20_想定最大規模/*.xml  (A31a: 都管理河川)
  data_lake/raw/tokyo/flood/A31b-24_10_5339_GML/20_想定最大規模/*.xml (A31b: 国管理河川)

出力:
  data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson

GML 構造:
  gml:Curve  (gml:id="cvN_M") → gml:posList に lat lon 座標列
  gml:Surface (gml:id="sfN")  → curveMember xlink:href="#cvN_M" で Curve を参照
  ksj:MaximumScale             → bounds xlink:href="#sfN" で Surface を参照
    ksj:waterDepth   : 1〜6 (浸水深ランク)
    ksj:riverName    : 河川名 (A31a のみ)
    ksj:riverNumber  : 河川番号 (A31a のみ)
    ksj:riverManager : 管理者

waterDepth → A31a_205 ランク変換（フロントエンドの色分け凡例と対応）:
  1 → 1  (0.5m未満)
  2 → 2  (0.5〜3m)
  3 → 3  (3〜5m)
  4 → 4  (5〜10m)
  5 → 5  (10〜20m)
  6 → 5  (20m以上 → 最大ランクに統合)

座標系: JGD2011 (EPSG:6668) ≈ WGS84 / EPSG:4326
        GML は (lat, lon) 順 → GeoJSON 出力は (lon, lat) 順に変換

メモリ効率:
  iterparse を使ったストリーミング解析（2パス）。
  A31b のような 26M 行超の大容量 XML でもメモリを節約して処理可能。
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

# XML 名前空間
GML   = 'http://schemas.opengis.net/gml/3.2.1'
KSJ   = 'http://nlftp.mlit.go.jp/ksj/schemas/ksj-app'
XLINK = 'http://www.w3.org/1999/xlink'

# waterDepth(1-6) → A31a_205(1-5) 変換
DEPTH_TO_RANK = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 5}

RAW_DIR    = "data_lake/raw/tokyo/flood"
OUT_PATH   = "data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson"
TARGET_DIR = "20_想定最大規模"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="洪水浸水想定区域 GML → GeoJSON 変換")
    parser.add_argument("--raw-dir",  default=RAW_DIR,  help="raw フォルダのパス")
    parser.add_argument("--output",   default=OUT_PATH,  help="出力 GeoJSON パス")
    return parser.parse_args()


def parse_poslist(text: str) -> List[Tuple[float, float]]:
    """gml:posList テキスト (lat lon lat lon ...) → [(lon, lat), ...] に変換"""
    vals = text.split()
    coords = []
    for i in range(0, len(vals) - 1, 2):
        lat, lon = float(vals[i]), float(vals[i + 1])
        coords.append((lon, lat))  # GeoJSON は lon/lat 順
    return coords


def _collect_geometry(xml_path: Path) -> Tuple[
    Dict[str, List[Tuple[float, float]]],
    Dict[str, List[str]],
]:
    """
    パス1: iterparse で Curve と Surface の辞書を収集。

    Returns:
        curves:   {curve_id: [(lon, lat), ...]}
        surfaces: {surface_id: [curve_id, ...]}
    """
    curves:   Dict[str, List[Tuple[float, float]]] = {}
    surfaces: Dict[str, List[str]]                 = {}

    cur_curve_id:   Optional[str] = None
    cur_surf_id:    Optional[str] = None
    cur_surf_curves: List[str]    = []

    for event, elem in ET.iterparse(xml_path, events=('start', 'end')):
        tag = elem.tag

        if event == 'start':
            if tag == f'{{{GML}}}Curve':
                cur_curve_id    = elem.get(f'{{{GML}}}id')
            elif tag == f'{{{GML}}}Surface':
                cur_surf_id     = elem.get(f'{{{GML}}}id')
                cur_surf_curves = []

        else:  # end
            if tag == f'{{{GML}}}posList':
                if cur_curve_id and elem.text:
                    curves[cur_curve_id] = parse_poslist(elem.text)

            elif tag == f'{{{GML}}}Curve':
                cur_curve_id = None

            elif tag == f'{{{GML}}}curveMember':
                if cur_surf_id:
                    href = elem.get(f'{{{XLINK}}}href', '')
                    if href.startswith('#'):
                        cur_surf_curves.append(href[1:])

            elif tag == f'{{{GML}}}Surface':
                if cur_surf_id:
                    surfaces[cur_surf_id] = cur_surf_curves
                cur_surf_id     = None
                cur_surf_curves = []

            elem.clear()

    return curves, surfaces


def _build_features(
    xml_path: Path,
    curves:   Dict[str, List[Tuple[float, float]]],
    surfaces: Dict[str, List[str]],
    source_tag: str,
) -> Tuple[List[dict], int]:
    """
    パス2: iterparse で ksj:MaximumScale を走査し Feature を生成。

    Args:
        source_tag: ファイルの由来ラベル ('A31a' or 'A31b')
    """
    features: List[dict] = []
    skipped = 0

    in_ms   = False
    ms_data: dict = {}

    for event, elem in ET.iterparse(xml_path, events=('start', 'end')):
        tag = elem.tag

        if event == 'start':
            if tag == f'{{{KSJ}}}MaximumScale':
                in_ms   = True
                ms_data = {'river_name': '', 'river_number': ''}

        elif in_ms:
            # --- 子要素の収集（end イベント） ---
            if tag == f'{{{KSJ}}}bounds':
                href = elem.get(f'{{{XLINK}}}href', '')
                ms_data['sf_id'] = href.lstrip('#')

            elif tag == f'{{{KSJ}}}waterDepth':
                ms_data['water_depth'] = (elem.text or '').strip()

            elif tag == f'{{{KSJ}}}riverName':
                ms_data['river_name'] = (elem.text or '').strip()

            elif tag == f'{{{KSJ}}}riverNumber':
                ms_data['river_number'] = (elem.text or '').strip()

            elif tag == f'{{{KSJ}}}MaximumScale':
                # --- Feature 生成 ---
                sf_id     = ms_data.get('sf_id', '')
                curve_ids = surfaces.get(sf_id)
                if not curve_ids:
                    skipped += 1
                    in_ms = False
                    elem.clear()
                    continue

                # Curve 座標を結合してポリゴンリングを構築
                ring: List[Tuple[float, float]] = []
                for cv_id in curve_ids:
                    coords = curves.get(cv_id, [])
                    if ring and coords and ring[-1] == coords[0]:
                        ring.extend(coords[1:])
                    else:
                        ring.extend(coords)

                if len(ring) < 3:
                    skipped += 1
                    in_ms = False
                    elem.clear()
                    continue

                if ring[0] != ring[-1]:
                    ring.append(ring[0])

                try:
                    depth_int = int(ms_data.get('water_depth', '0'))
                except ValueError:
                    depth_int = 0
                rank = DEPTH_TO_RANK.get(depth_int, 1)

                features.append({
                    "type": "Feature",
                    "properties": {
                        "A31a_205":     rank,
                        "flood_rank":   rank,
                        "water_depth":  depth_int,
                        "river_name":   ms_data['river_name'],
                        "river_number": ms_data['river_number'],
                        "source":       source_tag,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[lon, lat] for lon, lat in ring]],
                    },
                })
                in_ms = False

            elem.clear()

    return features, skipped


def extract_features_from_xml(xml_path: Path) -> List[dict]:
    """
    1つの XML ファイルから GeoJSON Feature リストを抽出する（iterparse 2パス方式）。

    パス1: gml:Curve / gml:Surface の辞書を構築
    パス2: ksj:MaximumScale を走査し Feature を生成
    """
    t0 = time.time()
    size_mb = xml_path.stat().st_size / 1024 / 1024
    print(f"  解析中: {xml_path.name}  ({size_mb:.1f} MB)", flush=True)

    # A31a / A31b を判定（source 属性として記録）
    source_tag = 'A31b' if 'A31b' in xml_path.name else 'A31a'

    # パス1
    curves, surfaces = _collect_geometry(xml_path)
    print(f"    Curve: {len(curves):,}  Surface: {len(surfaces):,}", flush=True)

    # パス2
    features, skipped = _build_features(xml_path, curves, surfaces, source_tag)

    elapsed = time.time() - t0
    print(f"    → {len(features):,} フィーチャ (スキップ: {skipped})  [{elapsed:.1f}s]", flush=True)
    return features


def main() -> int:
    args = parse_args()
    repo_root   = Path(__file__).resolve().parent.parent.parent
    raw_dir     = Path(args.raw_dir) if Path(args.raw_dir).is_absolute() else repo_root / args.raw_dir
    output_path = Path(args.output)  if Path(args.output).is_absolute()  else repo_root / args.output

    # 対象 XML ファイルを収集（20_想定最大規模 のみ、A31a / A31b 両対応）
    xml_files = sorted(raw_dir.rglob(f"{TARGET_DIR}/*-20-*.xml"))
    if not xml_files:
        print(f"エラー: 対象 XML が見つかりません: {raw_dir}/**/{TARGET_DIR}/*-20-*.xml",
              file=sys.stderr)
        return 1

    print(f"対象ファイル: {len(xml_files)} 件")
    for f in xml_files:
        print(f"  {f.relative_to(repo_root)}")
    print()

    # 全ファイルを順番に変換してフィーチャを収集
    all_features: List[dict] = []
    total_t0 = time.time()

    for xml_path in xml_files:
        features = extract_features_from_xml(xml_path)
        all_features.extend(features)

    # 出力
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n書き込み中: {output_path} ({len(all_features):,} フィーチャ) ...", flush=True)
    result = {
        "type": "FeatureCollection",
        "name": "tokyo_flood_max",
        "features": all_features,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    size_mb = output_path.stat().st_size / 1024 / 1024
    elapsed = time.time() - total_t0
    print(f"完了: {size_mb:.1f} MB  総処理時間: {elapsed:.1f}s")

    # 集計
    from collections import Counter
    rank_counts: Counter = Counter(
        f["properties"]["A31a_205"] for f in all_features
    )
    depth_labels = {1: "0.5m未満", 2: "0.5〜3m", 3: "3〜5m", 4: "5〜10m", 5: "10m以上"}
    print("\nランク別フィーチャ数:")
    for r in sorted(rank_counts):
        print(f"  rank {r} ({depth_labels.get(r, '?')}): {rank_counts[r]:,} 件")

    source_counts: Counter = Counter(
        f["properties"]["source"] for f in all_features
    )
    print("\nソース別フィーチャ数:")
    for src, count in sorted(source_counts.items()):
        print(f"  {src}: {count:,} 件")

    river_counts: Counter = Counter(
        f["properties"]["river_name"] for f in all_features
    )
    print("\n河川別フィーチャ数:")
    for name, count in sorted(river_counts.items(), key=lambda x: -x[1]):
        label = f"  {name}: {count:,} 件" if name else f"  (名称なし/A31b): {count:,} 件"
        print(label)

    return 0


if __name__ == "__main__":
    sys.exit(main())
