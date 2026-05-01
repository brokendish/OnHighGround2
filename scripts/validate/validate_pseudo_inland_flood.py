#!/usr/bin/env python3
"""
validate_pseudo_inland_flood.py

pseudo_inland_flood GeoJSON の最低品質基準を確認する。

Usage:
  python scripts/validate/validate_pseudo_inland_flood.py [--input PATH]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_INPUT = (
    ROOT / "data_lake" / "validated" / "tokyo" / "pseudo_inland_flood"
    / "pseudo_inland_flood.geojson"
)

VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}


def validate(geojson_path: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if not geojson_path.exists():
        return False, [f"ファイルが存在しません: {geojson_path}"]

    size_bytes = geojson_path.stat().st_size
    if size_bytes == 0:
        return False, ["ファイルが空です"]

    try:
        with open(geojson_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"JSON パースエラー: {e}"]

    if data.get("type") != "FeatureCollection":
        errors.append(f"type が FeatureCollection ではありません: {data.get('type')}")

    features = data.get("features", [])
    if len(features) == 0:
        errors.append("features が 0 件です")
        return False, errors

    print(f"  Features    : {len(features):,}")
    print(f"  File size   : {size_bytes / (1024 ** 2):.1f} MB")

    risk_counts: dict[str, int] = {}
    sample_errors: list[str] = []
    MAX_SAMPLE_ERRORS = 5

    for i, feat in enumerate(features):
        if len(sample_errors) >= MAX_SAMPLE_ERRORS:
            break

        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}

        # risk_level
        level = props.get("risk_level")
        if level not in VALID_RISK_LEVELS:
            sample_errors.append(
                f"feature[{i}]: 不正な risk_level={level!r}"
            )
        else:
            risk_counts[level] = risk_counts.get(level, 0) + 1

        # risk_score
        score = props.get("risk_score")
        if not isinstance(score, (int, float)):
            sample_errors.append(
                f"feature[{i}]: risk_score が数値ではありません: {score!r}"
            )

        # official
        official = props.get("official")
        if official is not False:
            sample_errors.append(
                f"feature[{i}]: official が false ではありません: {official!r}"
            )

        # geometry type
        gtype = geom.get("type")
        if gtype not in VALID_GEOMETRY_TYPES:
            sample_errors.append(
                f"feature[{i}]: geometry.type が不正: {gtype!r}"
            )

    errors.extend(sample_errors)

    print(f"  Risk levels : {risk_counts}")

    # 全 risk_level に何らかのデータがあることを確認（最低限 1 レベル）
    if not risk_counts:
        errors.append("有効な risk_level を持つ feature が存在しません")

    return len(errors) == 0, errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="pseudo_inland_flood GeoJSON を検証する"
    )
    parser.add_argument(
        "--input", help=f"GeoJSON パス（デフォルト: {DEFAULT_INPUT}）"
    )
    parser.add_argument(
        "--output",
        help="既存 pipeline 互換用。pseudo_inland_flood 検証では出力を生成しないため無視します。",
    )
    args = parser.parse_args()

    geojson_path = Path(args.input) if args.input else DEFAULT_INPUT

    print(f"Validating: {geojson_path}")
    ok, errors = validate(geojson_path)

    if ok:
        print("✓ 検証 OK")
        return 0
    else:
        print("✗ 検証 NG:")
        for err in errors:
            print(f"  - {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
