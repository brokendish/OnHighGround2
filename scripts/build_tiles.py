#!/usr/bin/env python3
"""
build_tiles.py — Hazard GeoJSON → Vector Tiles (MBTiles)

Converts hazard GeoJSON files into vector tiles using tippecanoe.

Usage:
    python scripts/build_tiles.py [options]

Options:
    --minzoom INT     Minimum zoom level (default: 5)
    --maxzoom INT     Maximum zoom level (default: 14)
    --input DIR       Directory containing GeoJSON files (default: data/processed/hazard)
    --output DIR      Directory for .mbtiles output (default: tiles)
    --dry-run         Print commands without executing

NOTE on input directory:
    Default:    data/processed/hazard/   ← canonical GeoJSON source location
    Temporary:  frontend/hazard/         ← use --input frontend/hazard while migrating
    frontend/hazard/ should NOT be treated as the long-term source location.
    See scripts/README.md for the intended data pipeline direction.

NOTE on output directory structure:
    Current:  tiles/{dataset}.mbtiles
    Future:   tiles/{region}/{hazard_type}/{dataset}.mbtiles
              e.g. tiles/japan/tokyo/tsunami/tsunami_tokyo.mbtiles
    The long-term layout is documented in scripts/README.md.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def find_geojson_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("*.geojson"))


def build_tiles(
    geojson_path: Path,
    output_dir: Path,
    minzoom: int,
    maxzoom: int,
    dry_run: bool,
) -> bool:
    dataset = geojson_path.stem  # e.g. "tsunami_tokyo"
    output_path = output_dir / f"{dataset}.mbtiles"

    cmd = [
        "tippecanoe",
        f"--minimum-zoom={minzoom}",
        f"--maximum-zoom={maxzoom}",
        "--output", str(output_path),
        "--force",              # overwrite existing output
        "--no-tile-compression",
        "--layer", dataset,
        str(geojson_path),
    ]

    print(f"\n[build] {geojson_path.name} → {output_path.relative_to(ROOT)}")
    print("  " + " ".join(cmd))

    if dry_run:
        print("  [dry-run] skipped")
        return True

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] tippecanoe failed:\n{result.stderr}", file=sys.stderr)
        return False

    size_mb = output_path.stat().st_size / (1024 ** 2)
    print(f"  [OK] {size_mb:.1f} MB")
    return True


def main():
    parser = argparse.ArgumentParser(description="Build vector tiles from hazard GeoJSON files.")
    parser.add_argument("--minzoom", type=int, default=5)
    parser.add_argument("--maxzoom", type=int, default=14)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "processed" / "hazard",
        help="Directory containing GeoJSON files (default: data/processed/hazard)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tiles",
        help="Output directory for .mbtiles files",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Check tippecanoe (skip in dry-run so the pipeline can be validated without it)
    if not args.dry_run and not shutil.which("tippecanoe"):
        print(
            "ERROR: tippecanoe is not installed or not in PATH.\n"
            "Install it with:\n"
            "  macOS:  brew install tippecanoe\n"
            "  Ubuntu: sudo apt install tippecanoe\n"
            "  or build from source: https://github.com/felt/tippecanoe",
            file=sys.stderr,
        )
        sys.exit(1)

    input_dir: Path = args.input.resolve()
    output_dir: Path = args.output.resolve()

    if not input_dir.exists():
        print(f"ERROR: input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    geojson_files = find_geojson_files(input_dir)
    if not geojson_files:
        msg = f"No .geojson files found in {input_dir.relative_to(ROOT)}"
        # Give a helpful hint if the user is still using the old location
        fallback = ROOT / "frontend" / "hazard"
        if fallback.exists() and list(fallback.glob("*.geojson")):
            msg += (
                f"\n\nHint: GeoJSON files were found in frontend/hazard/ (legacy location)."
                f"\n  To use them now:    python scripts/build_tiles.py --input frontend/hazard"
                f"\n  Recommended action: copy or move them to data/processed/hazard/"
            )
        print(msg, file=sys.stderr)
        sys.exit(1)

    print(f"Input:    {input_dir.relative_to(ROOT)}")
    print(f"Output:   {output_dir.relative_to(ROOT)}")
    print(f"Zoom:     {args.minzoom} – {args.maxzoom}")
    print(f"Datasets: {[f.name for f in geojson_files]}")

    results = []
    for geojson_path in geojson_files:
        ok = build_tiles(geojson_path, output_dir, args.minzoom, args.maxzoom, args.dry_run)
        results.append((geojson_path.name, ok))

    print("\n--- Summary ---")
    all_ok = True
    for name, ok in results:
        status = "OK" if ok else "FAILED"
        print(f"  [{status}] {name}")
        if not ok:
            all_ok = False

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
