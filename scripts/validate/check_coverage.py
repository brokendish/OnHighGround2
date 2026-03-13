#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Produce a minimal coverage status report.")
    parser.add_argument("--input", required=True, help="Input GeoJSON path.")
    parser.add_argument(
        "--output",
        default="data_lake/validated/tokyo/coverage_report.json",
        help="Output report path.",
    )
    parser.add_argument(
        "--coverage-status",
        default="unknown",
        help="Coverage status label to persist until spatial coverage checks are implemented.",
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

    report = {
        "input": str(input_path),
        "feature_count": len(data.get("features", [])),
        "coverage_status": args.coverage_status,
        "notes": [
            "TODO: compare actual geometry coverage against Tokyo boundary coverage targets."
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote coverage report to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
