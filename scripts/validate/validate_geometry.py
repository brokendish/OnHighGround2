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
    parser.add_argument(
        "--allowed-geometry-types",
        help="Comma-separated geometry types allowed for every feature.",
    )
    parser.add_argument(
        "--require-bbox",
        action="store_true",
        help="Require every feature geometry to produce a valid bbox.",
    )
    return parser.parse_args()


def _iter_points(coords):
    if isinstance(coords, (list, tuple)):
        if len(coords) >= 2 and all(isinstance(v, (int, float)) for v in coords[:2]):
            yield float(coords[0]), float(coords[1])
            return
        for item in coords:
            yield from _iter_points(item)


def _compute_bbox(geometry):
    coords = geometry.get("coordinates")
    points = list(_iter_points(coords))
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def main() -> int:
    args = parse_args()
    allowed_types = None
    if args.allowed_geometry_types:
        allowed_types = {t.strip() for t in args.allowed_geometry_types.split(",") if t.strip()}
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
        if allowed_types and geometry_type not in allowed_types:
            print(
                f"Feature {index} has disallowed geometry type: {geometry_type} "
                f"(allowed={sorted(allowed_types)})",
                file=sys.stderr,
            )
            return 1
        if geometry_type != "GeometryCollection" and coordinates is None:
            print(f"Feature {index} has no coordinates.", file=sys.stderr)
            return 1
        if args.require_bbox:
            bbox = _compute_bbox(geometry)
            if bbox is None:
                print(f"Feature {index} has invalid bbox.", file=sys.stderr)
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
