#!/usr/bin/env python3
import argparse
import shutil
import sys
from pathlib import Path

import ijson
from decimal import Decimal


VALID_GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


def _iter_points(coords):
    """座標ネスト構造を再帰的に展開して (x, y) を yield。ijson は Decimal を返すため対応済み"""
    if isinstance(coords, (list, tuple)):
        if len(coords) >= 2 and isinstance(coords[0], (int, float, Decimal)):
            yield float(coords[0]), float(coords[1])
            return
        for item in coords:
            yield from _iter_points(item)


def validate_stream(input_path: Path, output_path, allowed_types, require_bbox: bool) -> int:
    feature_count = 0
    error_count = 0

    minx = float("inf")
    miny = float("inf")
    maxx = float("-inf")
    maxy = float("-inf")

    with input_path.open("rb") as f:
        features = ijson.items(f, "features.item")

        for index, feature in enumerate(features):
            feature_count += 1

            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                print(f"Feature {index} is missing geometry.", file=sys.stderr)
                error_count += 1
                continue

            geometry_type = geometry.get("type")
            coordinates = geometry.get("coordinates")

            if geometry_type not in VALID_GEOMETRY_TYPES:
                print(f"Feature {index} has invalid geometry type: {geometry_type}", file=sys.stderr)
                error_count += 1
                continue

            if allowed_types and geometry_type not in allowed_types:
                print(
                    f"Feature {index} has disallowed geometry type: {geometry_type} "
                    f"(allowed={sorted(allowed_types)})",
                    file=sys.stderr,
                )
                error_count += 1
                continue

            if geometry_type != "GeometryCollection" and coordinates is None:
                print(f"Feature {index} has no coordinates.", file=sys.stderr)
                error_count += 1
                continue

            if coordinates is not None:
                feature_has_coords = False
                for x, y in _iter_points(coordinates):
                    feature_has_coords = True
                    if x < minx:
                        minx = x
                    if y < miny:
                        miny = y
                    if x > maxx:
                        maxx = x
                    if y > maxy:
                        maxy = y

                if require_bbox and not feature_has_coords:
                    print(f"Feature {index} has invalid bbox.", file=sys.stderr)
                    error_count += 1
                    continue

            if feature_count % 10000 == 0:
                print(f"[validate] processed: {feature_count}", flush=True)

    if feature_count == 0:
        print("GeoJSON must contain at least one feature.", file=sys.stderr)
        return 1

    if error_count > 0:
        print(f"[ERROR] invalid features detected: {error_count}", file=sys.stderr)
        return 1

    bbox_str = f"({minx},{miny},{maxx},{maxy})" if minx != float("inf") else "n/a"
    print(f"[validate] total: {feature_count}, bbox={bbox_str}", flush=True)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(input_path, out)
        print(f"validate success: {out}")
    else:
        print(f"Geometry validation passed: {input_path}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate basic GeoJSON geometry structure (streaming).")
    parser.add_argument("--input", required=True, help="Input GeoJSON path.")
    parser.add_argument("--output", help="Optional validated output path.")
    parser.add_argument("--allowed-geometry-types", help="Comma-separated geometry types allowed.")
    parser.add_argument("--require-bbox", action="store_true", help="Require valid bbox per feature.")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    allowed_types = None
    if args.allowed_geometry_types:
        allowed_types = {t.strip() for t in args.allowed_geometry_types.split(",") if t.strip()}

    try:
        return validate_stream(input_path, args.output, allowed_types, args.require_bbox)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
