#!/usr/bin/env python3
"""
洪水浸水想定区域 ハザード判定用フィルタスクリプト

入力: data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson (全ランク、666K フィーチャ)
出力: data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl (rank >= 2 のみ、GeoJSONL 形式)

GeoJSONL = 1行に1 Feature JSON。
バックエンドが load_geojsonl() で1行ずつストリーミング読み込みするため
大容量データでもピークメモリを最小限に抑えられる。

除外基準:
  rank 1 (0.5m未満) → ハザード判定から省略（軽微な浸水深）
  rank 2 (0.5〜3m)  → 含む
  rank 3 以上        → 含む
"""

import argparse
import json
import sys
import time
from pathlib import Path

IN_DEFAULT  = "data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson"
OUT_DEFAULT = "data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl"
MIN_RANK    = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="洪水 GeoJSON → ハザード判定用 GeoJSONL フィルタ")
    parser.add_argument("--input",    default=IN_DEFAULT,  help="入力 GeoJSON パス")
    parser.add_argument("--output",   default=OUT_DEFAULT, help="出力 GeoJSONL パス")
    parser.add_argument("--min-rank", type=int, default=MIN_RANK, help=f"最小ランク (デフォルト: {MIN_RANK})")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root   = Path(__file__).resolve().parent.parent.parent
    input_path  = Path(args.input)  if Path(args.input).is_absolute()  else repo_root / args.input
    output_path = Path(args.output) if Path(args.output).is_absolute() else repo_root / args.output

    if not input_path.exists():
        print(f"入力ファイルが見つかりません: {input_path}", file=sys.stderr)
        return 1

    print(f"読み込み中: {input_path}  ({input_path.stat().st_size / 1024 / 1024:.1f} MB)")
    t0 = time.time()

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    features_in = data.get("features", [])
    print(f"  入力フィーチャ数: {len(features_in):,}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    count_out  = 0
    count_skip = 0

    with output_path.open("w", encoding="utf-8") as f:
        for feat in features_in:
            props = feat.get("properties") or {}
            rank  = props.get("flood_rank", props.get("A31a_205", 0))
            if rank < args.min_rank:
                count_skip += 1
                continue
            f.write(json.dumps(feat, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            count_out += 1

    size_mb = output_path.stat().st_size / 1024 / 1024
    elapsed = time.time() - t0

    print(f"\n完了: {output_path}")
    print(f"  出力: {count_out:,} 件 (除外: {count_skip:,} 件、rank < {args.min_rank})")
    print(f"  ファイルサイズ: {size_mb:.1f} MB  処理時間: {elapsed:.1f}s")
    print(f"\n次のステップ:")
    print(f"  backend/app.properties で hazard.flood.enabled=true に変更してバックエンドを再起動")

    return 0


if __name__ == "__main__":
    sys.exit(main())
