#!/usr/bin/env python3
"""
高潮浸水想定区域データ正規化スクリプト

入力: data_lake/raw/tokyo/storm_surge/A49-20_13.geojson
出力: data_lake/normalized/tokyo/storm_surge/tokyo_storm_surge.geojson

処理内容:
  - 不要属性を削除 (A49_001, A49_002)
  - 浸水深区分テキスト (A49_003) をランク整数 (storm_surge_rank: 1-7) に変換
  - CRS 宣言を EPSG:4326 に統一 (EPSG:6668 は JGD2011 で実質同一)
  - FeatureCollection として出力

浸水深ランク対応:
  1: 0.3m未満
  2: 0.3m以上0.5m未満
  3: 0.5m以上1m未満
  4: 1m以上3m未満
  5: 3m以上5m未満
  6: 5m以上10m未満
  7: 10m以上20m未満
"""

import argparse
import json
import sys
from pathlib import Path

DEPTH_TO_RANK = {
    "0.3m未満":         1,
    "0.3m以上0.5m未満": 2,
    "0.5m以上1m未満":   3,
    "1m以上3m未満":     4,
    "3m以上5m未満":     5,
    "5m以上10m未満":    6,
    "10m以上20m未満":   7,
}

RAW_DEFAULT  = "data_lake/raw/tokyo/storm_surge/A49-20_13.geojson"
OUT_DEFAULT  = "data_lake/normalized/tokyo/storm_surge/tokyo_storm_surge.geojson"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="高潮浸水想定区域データ正規化")
    parser.add_argument("--input",  default=RAW_DEFAULT, help="入力 GeoJSON パス")
    parser.add_argument("--output", default=OUT_DEFAULT,  help="出力 GeoJSON パス")
    return parser.parse_args()


def normalize(input_path: Path, output_path: Path) -> int:
    print(f"読み込み中: {input_path}")
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    features_in  = data.get("features", [])
    features_out = []
    skipped      = 0

    for feat in features_in:
        props = feat.get("properties") or {}
        geom  = feat.get("geometry")

        if not geom:
            skipped += 1
            continue

        depth_label = props.get("A49_003", "")
        rank = DEPTH_TO_RANK.get(depth_label, 0)

        features_out.append({
            "type": "Feature",
            "properties": {
                "storm_surge_rank":  rank,       # 整数ランク (1-7)
                "depth_label":       depth_label, # 元テキスト保持
            },
            "geometry": geom,
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "type": "FeatureCollection",
        "name": "tokyo_storm_surge",
        "features": features_out,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"完了: {output_path}")
    print(f"  フィーチャ数: {len(features_out)} (スキップ: {skipped})")
    print(f"  ファイルサイズ: {size_mb:.1f} MB")

    rank_counts: dict = {}
    for feat in features_out:
        r = feat["properties"]["storm_surge_rank"]
        rank_counts[r] = rank_counts.get(r, 0) + 1
    print("  ランク別件数:")
    for r in sorted(rank_counts):
        label = next((k for k, v in DEPTH_TO_RANK.items() if v == r), "?")
        print(f"    rank {r} ({label}): {rank_counts[r]}件")

    return 0


def main() -> int:
    args  = parse_args()
    repo_root = Path(__file__).resolve().parent.parent.parent
    input_path  = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_absolute():
        input_path = repo_root / input_path
    if not output_path.is_absolute():
        output_path = repo_root / output_path

    if not input_path.exists():
        print(f"入力ファイルが見つかりません: {input_path}", file=sys.stderr)
        return 1

    return normalize(input_path, output_path)


if __name__ == "__main__":
    sys.exit(main())
