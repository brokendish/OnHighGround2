#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Overlay validated hazard data onto an analysis mesh.")
    parser.add_argument("--mesh", required=False, help="Mesh input path.")
    parser.add_argument("--hazard", required=False, help="Hazard input path.")
    parser.add_argument(
        "--output",
        default="data_lake/validated/tokyo/mesh/tokyo_hazard_overlay.geojson",
        help="Overlay output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    overlay = {
        "type": "FeatureCollection",
        "name": "tokyo_hazard_overlay_placeholder",
        "features": [],
        "metadata": {
            "mesh": args.mesh,
            "hazard": args.hazard,
            "note": "TODO: spatial overlay implementation pending.",
        },
    }
    output_path.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote hazard overlay placeholder to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
