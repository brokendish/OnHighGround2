#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Tokyo shelter GeoJSON.")
    parser.add_argument(
        "--input",
        default="data_lake/raw/tokyo/shelter/tokyo_shelter.geojson",
        help="Input raw GeoJSON path.",
    )
    parser.add_argument(
        "--output",
        default="data_lake/normalized/tokyo/shelter/tokyo_shelter.geojson",
        help="Output normalized GeoJSON path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    with input_path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("type") != "FeatureCollection":
        print("Input is not a FeatureCollection.", file=sys.stderr)
        return 1

    normalized_features = []
    for feature in data.get("features", []):
        properties = dict(feature.get("properties", {}))
        properties.setdefault("source_dataset", "TOKYO-SHELTER-001")
        properties.setdefault("normalized_region_code", "13")
        normalized_features.append(
            {
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": properties,
            }
        )

    normalized = {
        "type": "FeatureCollection",
        "name": "tokyo_shelter_normalized",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": normalized_features,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote normalized shelter data to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
