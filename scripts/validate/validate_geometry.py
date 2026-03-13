#!/usr/bin/env python3
import argparse
import json
import shutil
import sys
from pathlib import Path


VALID_GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate basic GeoJSON geometry structure.")
    parser.add_argument("--input", required=True, help="Input GeoJSON path.")
    parser.add_argument(
        "--output",
        help="Optional validated output path. If provided, the validated input is copied there.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    with input_path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("type") != "FeatureCollection":
        print("GeoJSON root type must be FeatureCollection.", file=sys.stderr)
        return 1

    features = data.get("features")
    if not isinstance(features, list) or not features:
        print("GeoJSON must contain at least one feature.", file=sys.stderr)
        return 1

    for index, feature in enumerate(features):
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            print(f"Feature {index} is missing geometry.", file=sys.stderr)
            return 1
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type not in VALID_GEOMETRY_TYPES:
            print(f"Feature {index} has invalid geometry type: {geometry_type}", file=sys.stderr)
            return 1
        if geometry_type != "GeometryCollection" and coordinates is None:
            print(f"Feature {index} has no coordinates.", file=sys.stderr)
            return 1

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(input_path, output_path)
        print(f"Geometry validation passed and copied to {output_path}")
    else:
        print(f"Geometry validation passed: {input_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
