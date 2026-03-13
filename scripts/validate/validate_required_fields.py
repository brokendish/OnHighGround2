#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate required GeoJSON property fields.")
    parser.add_argument("--input", required=True, help="Input GeoJSON path.")
    parser.add_argument(
        "--required-field",
        action="append",
        dest="required_fields",
        default=[],
        help="Property field that must exist on every feature. Can be repeated.",
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

    for index, feature in enumerate(data.get("features", [])):
        properties = feature.get("properties", {})
        for field in args.required_fields:
            value = properties.get(field)
            if value in (None, ""):
                print(f"Feature {index} missing required field: {field}", file=sys.stderr)
                return 1

    print(f"Required field validation passed: {input_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
