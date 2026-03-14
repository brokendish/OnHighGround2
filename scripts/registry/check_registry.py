#!/usr/bin/env python3
import argparse
import csv
import sys
from pathlib import Path


REQUIRED_COLUMNS = [
    "record_id",
    "hazard_type",
    "sub_type",
    "region_level",
    "region_code",
    "region_name",
    "target_area",
    "provider_type",
    "provider_name",
    "source_name",
    "source_url",
    "source_format",
    "source_crs",
    "geometry_type",
    "normalize_required",
    "normalize_format",
    "normalize_crs",
    "delivery_format",
    "tile_required",
    "frontend_layer_name",
    "coverage_status",
    "validation_status",
    "update_frequency",
    "license_note",
    "remarks",
]

ALLOWED_HAZARD_TYPES = {
    "dem",
    "flood",
    "tsunami",
    "storm_surge",
    "urban_flood",
    "shelter",
    "boundary",
    "osm",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the Tokyo hazard registry CSV.")
    parser.add_argument(
        "--registry",
        default="data_lake/registry/tokyo_hazard_registry.csv",
        help="Path to the registry CSV.",
    )
    return parser.parse_args()


def main() -> int:
    # TODO: expand validation with per-hazard rules and enum checks.
    args = parse_args()
    registry_path = Path(args.registry)

    if not registry_path.exists():
        print(f"Registry file not found: {registry_path}", file=sys.stderr)
        return 1

    with registry_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REQUIRED_COLUMNS:
            print("Registry header mismatch.", file=sys.stderr)
            print(f"Expected: {REQUIRED_COLUMNS}", file=sys.stderr)
            print(f"Actual:   {reader.fieldnames}", file=sys.stderr)
            return 1

        seen = set()
        rows = list(reader)
        if not rows:
            print("Registry is empty.", file=sys.stderr)
            return 1

        for index, row in enumerate(rows, start=2):
            record_id = row["record_id"].strip()
            if not record_id:
                print(f"Row {index}: record_id is empty.", file=sys.stderr)
                return 1
            if record_id in seen:
                print(f"Row {index}: duplicate record_id {record_id}.", file=sys.stderr)
                return 1
            seen.add(record_id)

            for column in REQUIRED_COLUMNS:
                if row[column] is None or row[column].strip() == "":
                    print(f"Row {index}: {column} is empty.", file=sys.stderr)
                    return 1

            hazard_type = row["hazard_type"].strip()
            if hazard_type not in ALLOWED_HAZARD_TYPES:
                print(f"Row {index}: unsupported hazard_type {hazard_type}.", file=sys.stderr)
                return 1

            frontend_layer_name = row["frontend_layer_name"].strip()
            if frontend_layer_name != hazard_type:
                print(
                    f"Row {index}: frontend_layer_name must match hazard_type for the canonical naming policy.",
                    file=sys.stderr,
                )
                return 1

    print(f"Registry check passed: {registry_path} ({len(rows)} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
