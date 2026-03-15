#!/usr/bin/env python3
"""
洪水浸水想定区域（想定最大規模）GML → GeoJSON 変換スクリプト

入力:
  data_lake/raw/tokyo/flood/A31a-24_13_10_GML/20_想定最大規模/*.xml
  data_lake/raw/tokyo/flood/A31a-24_13_20_GML/20_想定最大規模/*.xml

出力:
  data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson

GML 構造:
  gml:Curve  (gml:id="cvN_M") → gml:posList に lat lon 座標列
  gml:Surface (gml:id="sfN")  → curveMember xlink:href="#cvN_M" で Curve を参照
  ksj:MaximumScale             → bounds xlink:href="#sfN" で Surface を参照
    ksj:waterDepth   : 1〜6 (浸水深ランク)
    ksj:riverName    : 河川名
    ksj:riverNumber  : 河川番号
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
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

# XML 名前空間
NS = {
    'gml':   'http://schemas.opengis.net/gml/3.2.1',
    'ksj':   'http://nlftp.mlit.go.jp/ksj/schemas/ksj-app',
    'xlink': 'http://www.w3.org/1999/xlink',
}
GML  = 'http://schemas.opengis.net/gml/3.2.1'
KSJ  = 'http://nlftp.mlit.go.jp/ksj/schemas/ksj-app'
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


def extract_features_from_xml(xml_path: Path) -> List[dict]:
    """
    1つの XML ファイルから GeoJSON Feature リストを抽出する。

    ステップ:
      1. gml:Curve id → 座標リスト のマップを構築
      2. gml:Surface id → Curve id リスト のマップを構築
      3. ksj:MaximumScale を走査し Surface → Curve → 座標を解決
    """
    t0 = time.time()
    print(f"  解析中: {xml_path.name}", flush=True)

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # --- ① Curve id → 座標 ---
    curves: Dict[str, List[Tuple[float, float]]] = {}
    for curve in root.iter(f'{{{GML}}}Curve'):
        gml_id = curve.get(f'{{{GML}}}id')
        pos_el = curve.find(f'.//{{{GML}}}posList')
        if gml_id and pos_el is not None and pos_el.text:
            curves[gml_id] = parse_poslist(pos_el.text)

    # --- ② Surface id → [Curve id, ...] ---
    surfaces: Dict[str, List[str]] = {}
    for surface in root.iter(f'{{{GML}}}Surface'):
        gml_id = surface.get(f'{{{GML}}}id')
        if not gml_id:
            continue
        curve_ids = []
        for member in surface.iter(f'{{{GML}}}curveMember'):
            href = member.get(f'{{{XLINK}}}href', '')
            if href.startswith('#'):
                curve_ids.append(href[1:])
        surfaces[gml_id] = curve_ids

    # --- ③ MaximumScale → Feature ---
    features: List[dict] = []
    skipped = 0

    for record in root.iter(f'{{{KSJ}}}MaximumScale'):
        bounds_el = record.find(f'{{{KSJ}}}bounds')
        if bounds_el is None:
            skipped += 1
            continue

        sf_href = bounds_el.get(f'{{{XLINK}}}href', '')
        sf_id = sf_href.lstrip('#')
        curve_ids = surfaces.get(sf_id)
        if not curve_ids:
            skipped += 1
            continue

        # Curve の座標を順番に結合してポリゴンリングを構築
        ring: List[Tuple[float, float]] = []
        for cv_id in curve_ids:
            coords = curves.get(cv_id, [])
            if ring and coords and ring[-1] == coords[0]:
                ring.extend(coords[1:])  # 重複点を除いて接続
            else:
                ring.extend(coords)

        if len(ring) < 3:
            skipped += 1
            continue

        # 閉じたリングにする
        if ring[0] != ring[-1]:
            ring.append(ring[0])

        depth_text = record.findtext(f'{{{KSJ}}}waterDepth', '').strip()
        try:
            depth_int = int(depth_text)
        except ValueError:
            depth_int = 0
        rank = DEPTH_TO_RANK.get(depth_int, 1)

        river_name   = (record.findtext(f'{{{KSJ}}}riverName',   '') or '').strip()
        river_number = (record.findtext(f'{{{KSJ}}}riverNumber', '') or '').strip()

        features.append({
            "type": "Feature",
            "properties": {
                "A31a_205":     rank,         # 既存フロントエンドと互換
                "flood_rank":   rank,         # 明示的エイリアス
                "water_depth":  depth_int,    # 元の waterDepth 値
                "river_name":   river_name,
                "river_number": river_number,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[lon, lat] for lon, lat in ring]],
            },
        })

    elapsed = time.time() - t0
    print(f"    → {len(features)} フィーチャ (スキップ: {skipped})  [{elapsed:.1f}s]", flush=True)
    return features


def main() -> int:
    args = parse_args()
    repo_root   = Path(__file__).resolve().parent.parent.parent
    raw_dir     = Path(args.raw_dir) if Path(args.raw_dir).is_absolute() else repo_root / args.raw_dir
    output_path = Path(args.output)  if Path(args.output).is_absolute()  else repo_root / args.output

    # 対象 XML ファイルを収集（20_想定最大規模 のみ）
    xml_files = sorted(raw_dir.rglob(f"{TARGET_DIR}/A31a-20-*.xml"))
    if not xml_files:
        print(f"エラー: 対象 XML が見つかりません: {raw_dir}/**/{TARGET_DIR}/A31a-20-*.xml",
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

    river_counts: Counter = Counter(
        f["properties"]["river_name"] for f in all_features
    )
    print("\n河川別フィーチャ数:")
    for name, count in sorted(river_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count:,} 件")

    return 0


if __name__ == "__main__":
    sys.exit(main())
