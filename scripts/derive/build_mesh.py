#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a placeholder analysis mesh.")
    parser.add_argument(
        "--output",
        default="data_lake/validated/tokyo/mesh/tokyo_mesh.geojson",
        help="Output mesh path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mesh = {"type": "FeatureCollection", "name": "tokyo_mesh_placeholder", "features": []}
    output_path.write_text(json.dumps(mesh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote mesh placeholder to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
