#!/usr/bin/env python3
"""
normalize_shelter_gsi_prefecture.py — GSI都道府県別指定緊急避難場所データの決定的再生成
（Phase 2-D Round 2、P2D-HAZARD-PROVENANCE / HAZ-SHELTER対応）

対象: 国土地理院「指定緊急避難場所・指定避難所データダウンロードサイト」
      （https://hinanmap.gsi.go.jp/）が配布する都道府県別GeoJSON
      （例: https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/geoJSON/13000_1.geojson）

`backend/app/services/shelter_service.py`は「施設・場所名」「住所」「洪水」等の
GSI生フィールド名をそのまま読む設計であるため、本scriptはスキーマ変換を行わず、
決定的な再シリアライズ（feature順のNO昇順ソート、JSON鍵順の維持、
indent=2・ensure_ascii=Falseでの整形）のみを行う「最小修正版normalizer」である。

使い方:
    python3 scripts/normalize/normalize_shelter_gsi_prefecture.py \\
        --input /path/to/13000_1.geojson \\
        --output data_runtime/backend/shelters/tokyo_emergency_evacuation_sites.geojson

同一入力に対して2回実行した出力のSHA-256が一致すること（決定的生成）を
`tools/public_release/phase2d_shelter_reacquisition.py`が検証する。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def normalize(input_path: Path) -> dict:
    with input_path.open(encoding="utf-8") as f:
        data = json.load(f)

    if data.get("type") != "FeatureCollection":
        raise ValueError(f"unexpected GeoJSON type: {data.get('type')!r} (expected FeatureCollection)")

    features = data.get("features", [])
    if not features:
        raise ValueError("input contains 0 features — refusing to generate an empty shelter dataset")

    def _sort_key(feature: dict):
        no = feature.get("properties", {}).get("NO")
        try:
            return (0, int(no))
        except (TypeError, ValueError):
            return (1, str(no))

    features_sorted = sorted(features, key=_sort_key)

    return {
        "type": "FeatureCollection",
        "name": data.get("name", ""),
        "features": features_sorted,
    }


def write_deterministic(output_data: dict, output_path: Path) -> str:
    text = json.dumps(output_data, ensure_ascii=False, indent=2)
    text += "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="GSI都道府県別raw GeoJSON")
    parser.add_argument("--output", required=True, type=Path, help="出力先GeoJSONパス")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    try:
        normalized = normalize(args.input)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: normalize failed (fail-closed, no output written): {exc}", file=sys.stderr)
        return 1

    output_sha256 = write_deterministic(normalized, args.output)
    print(f"features={len(normalized['features'])} output_sha256={output_sha256}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
