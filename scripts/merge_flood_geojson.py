#!/usr/bin/env python3
"""
merge_flood_geojson.py — 洪水浸水想定 GeoJSON の結合

国土地理院「洪水浸水想定区域」河川別 GeoJSON を 1 つの FeatureCollection に結合します。
対象: 東京都（A31a-24_13_10_GeoJSON/20_想定最大規模/）

使い方:
    python scripts/merge_flood_geojson.py [options]

オプション:
    --input DIR    入力ディレクトリ（デフォルト: 国土地理院洪水予報河川データ/A31a-24_13_10_GeoJSON/20_想定最大規模）
    --output FILE  出力 GeoJSON ファイル（デフォルト: data/processed/hazard/tokyo_flood_max.geojson）
    --dry-run      ファイルを書き込まず件数のみ表示

プロパティについて:
    A31a_201  河川コード
    A31a_202  河川名
    A31a_203  都道府県コード
    A31a_204  都道府県名
    A31a_205  浸水深ランク（1〜5）
               1: 0.5m未満
               2: 0.5〜3m未満
               3: 3〜5m未満
               4: 5〜10m未満
               5: 10m以上

出力ファイルはタイル生成スクリプト（scripts/build_tiles.py）の入力として使用します:
    python scripts/build_tiles.py --input data/processed/hazard
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_INPUT = (
    ROOT
    / "国土地理院洪水予報河川データ"
    / "A31a-24_13_10_GeoJSON"
    / "20_想定最大規模"
)
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "hazard" / "tokyo_flood_max.geojson"


def merge(input_dir: Path, output_path: Path, dry_run: bool) -> None:
    geojson_files = sorted(input_dir.glob("*.geojson"))
    if not geojson_files:
        print(f"ERROR: .geojson ファイルが見つかりません: {input_dir}", file=sys.stderr)
        sys.exit(1)

    features = []
    for path in geojson_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        file_features = data.get("features", [])
        for feat in file_features:
            feat.setdefault("properties", {})
            feat["properties"]["source_file"] = path.name
            feat["properties"]["hazard_type"] = "flood"
            feat["properties"]["scenario"] = "max"
        features.extend(file_features)
        print(f"  {path.name}: {len(file_features)} features")

    print(f"\n合計: {len(features)} features ({len(geojson_files)} ファイル)")

    if dry_run:
        print("[dry-run] 書き込みをスキップしました")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    collection = {
        "type": "FeatureCollection",
        "features": features,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(collection, f, ensure_ascii=False)

    size_mb = output_path.stat().st_size / (1024 ** 2)
    print(f"出力: {output_path.relative_to(ROOT)}  ({size_mb:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="洪水浸水想定 GeoJSON を 1 ファイルに結合します。"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="入力ディレクトリ（デフォルト: 国土地理院洪水予報河川データ/A31a-24_13_10_GeoJSON/20_想定最大規模）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="出力 GeoJSON ファイル（デフォルト: data/processed/hazard/tokyo_flood_max.geojson）",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    input_dir = args.input.resolve()
    output_path = args.output.resolve()

    if not input_dir.exists():
        print(f"ERROR: 入力ディレクトリが見つかりません: {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"入力: {input_dir.relative_to(ROOT)}")
    print(f"出力: {output_path.relative_to(ROOT)}")
    print()

    merge(input_dir, output_path, args.dry_run)


if __name__ == "__main__":
    main()
