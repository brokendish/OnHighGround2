#!/usr/bin/env python3
# Legacy filename retained for compatibility. Canonical data category is flood.
import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize flood data to GeoJSON.")
    parser.add_argument("--input", required=False, help="Input dataset path.")
    parser.add_argument(
        "--output",
        default="data_lake/normalized/tokyo/flood/flood.geojson",
        help="Output GeoJSON path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Input not found: {input_path}", file=sys.stderr)
            return 1

    feature_collection = {
        "type": "FeatureCollection",
        "name": "tokyo_flood_placeholder",
        "features": [],
    }
    output_path.write_text(
        json.dumps(feature_collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote normalized flood placeholder to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
