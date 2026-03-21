#!/usr/bin/env python3
"""
内水浸水想定区域データ正規化スクリプト（国土数値情報 A51）

入力: data_lake/raw/tokyo/inland_flood/ 以下の全 *.geojson（サブディレクトリ含む）
出力: data_lake/normalized/tokyo/inland_flood/tokyo_inland_flood_A51.geojson

処理内容:
  - A51 属性を標準プロパティに変換
      A51_003 (市区町村名) → zone_name
      A51_004 (市区町村コード) → city_code
      A51_005 (浸水深区分テキスト) → depth_label / depth_min_m / depth_max_m / depth_rank
  - 複数市区町村ファイルを 1 ファイルにマージ
  - CRS 宣言を除去（EPSG:6668 JGD2011 は EPSG:4326 と実質同一）

浸水深ランク対応 (depth_rank):
  1: 0.3m未満
  2: 0.3m以上0.5m未満
  3: 0.5m以上1m未満
  4: 1m以上3m未満
  5: 3m以上5m未満
  6: 5m以上10m未満
  7: 10m以上20m未満

使い方:
  python scripts/normalize/normalize_inland_flood.py
  python scripts/normalize/normalize_inland_flood.py --input-dir data_lake/raw/tokyo/inland_flood/ --output data_lake/normalized/tokyo/inland_flood/tokyo_inland_flood_A51.geojson
"""

import argparse
import json
import sys
from pathlib import Path

# (depth_label, depth_min_m, depth_max_m, depth_rank)
_DEPTH_TABLE: list[tuple[str, float, float, int]] = [
    ("0.3m未満",         0.0,  0.3,  1),
    ("0.3m以上0.5m未満", 0.3,  0.5,  2),
    ("0.5m以上1m未満",   0.5,  1.0,  3),
    ("1m以上3m未満",     1.0,  3.0,  4),
    ("3m以上5m未満",     3.0,  5.0,  5),
    ("5m以上10m未満",    5.0, 10.0,  6),
    ("10m以上20m未満",  10.0, 20.0,  7),
]

_DEPTH_MAP: dict[str, tuple[float, float, int]] = {
    label: (dmin, dmax, rank)
    for label, dmin, dmax, rank in _DEPTH_TABLE
}

RAW_DEFAULT = "data_lake/raw/tokyo/inland_flood"
OUT_DEFAULT = "data_lake/normalized/tokyo/inland_flood/tokyo_inland_flood_A51.geojson"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="内水浸水想定区域データ正規化 (A51)")
    parser.add_argument(
        "--input-dir",
        default=RAW_DEFAULT,
        help="A51 GeoJSON が格納されたディレクトリ（サブディレクトリ含む）",
    )
    parser.add_argument("--output", default=OUT_DEFAULT, help="出力 GeoJSON パス")
    return parser.parse_args()


def normalize(input_dir: Path, output_path: Path) -> int:
    geojson_files = sorted(input_dir.rglob("*.geojson"))
    if not geojson_files:
        print(f"GeoJSON ファイルが見つかりません: {input_dir}", file=sys.stderr)
        return 1

    print(f"入力ファイル数: {len(geojson_files)}")
    for p in geojson_files:
        print(f"  {p.relative_to(input_dir.parent.parent.parent.parent) if input_dir.is_relative_to(input_dir.parent.parent.parent.parent) else p}")

    features_out: list[dict] = []
    skipped = 0
    unknown_labels: set[str] = set()

    for src in geojson_files:
        with src.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            geom = feat.get("geometry")

            if not geom:
                skipped += 1
                continue

            depth_label = props.get("A51_005", "")
            depth_info = _DEPTH_MAP.get(depth_label)
            if depth_info is None:
                unknown_labels.add(depth_label)
                depth_min_m, depth_max_m, depth_rank = 0.0, None, 0
            else:
                depth_min_m, depth_max_m, depth_rank = depth_info

            features_out.append({
                "type": "Feature",
                "properties": {
                    "depth_rank":  depth_rank,
                    "depth_min_m": depth_min_m,
                    "depth_max_m": depth_max_m,
                    "depth_label": depth_label,
                    "zone_name":   props.get("A51_003", ""),
                    "city_code":   props.get("A51_004", ""),
                    "source":      "A51-24",
                },
                "geometry": geom,
            })

    if unknown_labels:
        print(f"  警告: 未知の浸水深区分 (depth_rank=0 として出力): {unknown_labels}", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "type": "FeatureCollection",
        "name": "tokyo_inland_flood_A51",
        "features": features_out,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"完了: {output_path}")
    print(f"  フィーチャ数: {len(features_out)} (スキップ: {skipped})")
    print(f"  ファイルサイズ: {size_mb:.2f} MB")

    rank_counts: dict[int, int] = {}
    for feat in features_out:
        r = feat["properties"]["depth_rank"]
        rank_counts[r] = rank_counts.get(r, 0) + 1
    print("  ランク別件数:")
    for r in sorted(rank_counts):
        label = next((la for la, _, _, rk in _DEPTH_TABLE if rk == r), "未知")
        print(f"    rank {r} ({label}): {rank_counts[r]}件")

    return 0


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent.parent
    input_dir = Path(args.input_dir)
    output_path = Path(args.output)
    if not input_dir.is_absolute():
        input_dir = repo_root / input_dir
    if not output_path.is_absolute():
        output_path = repo_root / output_path

    if not input_dir.is_dir():
        print(f"入力ディレクトリが見つかりません: {input_dir}", file=sys.stderr)
        return 1

    return normalize(input_dir, output_path)


if __name__ == "__main__":
    sys.exit(main())
