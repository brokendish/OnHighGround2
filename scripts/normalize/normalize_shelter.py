#!/usr/bin/env python3
"""
normalize_shelter.py — 指定緊急避難場所 GeoJSON 正規化スクリプト

使用方法:
  python3 normalize_shelter.py --input <input.geojson> --output <output.geojson>
  python3 normalize_shelter.py --input <input.geojson> --output <output.geojson> \
      --dataset-id KANAGAWA-SHELTER-001

--dataset-id が省略された場合は入力パスから推定する。
"""
import argparse
import json
import re
import sys
from pathlib import Path


# 都道府県コード（JIS X 0401）マッピング
# dataset_id のプレフィックス → 都道府県コード
_REGION_CODE_MAP: dict[str, str] = {
    "tokyo": "13",
    "kanagawa": "14",
    "saitama": "11",
    "chiba": "12",
    "osaka": "27",
    "aichi": "23",
}

# dataset_id プレフィックス → region キー
_DATASET_PREFIX_MAP: dict[str, str] = {
    "TOKYO": "tokyo",
    "KANAGAWA": "kanagawa",
    "SAITAMA": "saitama",
    "CHIBA": "chiba",
    "OSAKA": "osaka",
    "AICHI": "aichi",
}


def _infer_region(dataset_id: str) -> str:
    """dataset_id プレフィックスから region キーを推定する。"""
    prefix = dataset_id.split("-")[0].upper()
    return _DATASET_PREFIX_MAP.get(prefix, "unknown")


def _infer_region_from_path(path: Path) -> str:
    """パス文字列から region キーを推定する（フォールバック用）。"""
    parts = str(path).lower().split("/")
    for p in parts:
        if p in _REGION_CODE_MAP:
            return p
    return "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize shelter GeoJSON for any region.")
    parser.add_argument(
        "--input",
        required=True,
        help="Input raw GeoJSON path.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output normalized GeoJSON path.",
    )
    parser.add_argument(
        "--dataset-id",
        default=None,
        help="Dataset ID (e.g. KANAGAWA-SHELTER-001). Used to set metadata fields.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    # dataset_id と region の決定
    dataset_id = args.dataset_id
    if dataset_id:
        region = _infer_region(dataset_id)
    else:
        # パスから推定（後方互換）
        region = _infer_region_from_path(input_path)
        # output パスに dataset_id に近い情報が含まれる場合は取り出す
        stem = output_path.stem.upper().replace("_NORMALIZED", "").replace("-", "_")
        # 一致するプレフィックスを探す
        for prefix in _DATASET_PREFIX_MAP:
            if stem.startswith(prefix):
                region = _DATASET_PREFIX_MAP[prefix]
                break

    region_code = _REGION_CODE_MAP.get(region, "00")
    source_dataset = dataset_id or f"{region.upper()}-SHELTER-001"

    with input_path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("type") != "FeatureCollection":
        print("Input is not a FeatureCollection.", file=sys.stderr)
        return 1

    normalized_features = []
    for feature in data.get("features", []):
        properties = dict(feature.get("properties", {}))
        properties.setdefault("source_dataset", source_dataset)
        properties.setdefault("normalized_region_code", region_code)
        normalized_features.append(
            {
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": properties,
            }
        )

    normalized = {
        "type": "FeatureCollection",
        "name": f"{region}_shelter_normalized",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": normalized_features,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(normalized_features)} features to {output_path}")
    print(f"  source_dataset={source_dataset}  region={region}  region_code={region_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
