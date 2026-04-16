#!/usr/bin/env python3
"""
build_walking_extract.py

東京 + 神奈川の境界 GeoJSON から walking 用の縮小 OSM PBF を生成する。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _extract_polygons(geojson_path: Path) -> list[list[list[list[float]]]]:
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    polygons: list[list[list[list[float]]]] = []

    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        gtype = geometry.get("type")
        coords = geometry.get("coordinates")
        if not coords:
            continue
        if gtype == "Polygon":
            polygons.append(coords)
        elif gtype == "MultiPolygon":
            polygons.extend(coords)

    if not polygons:
        raise ValueError(f"no polygon geometries found in {geojson_path}")
    return polygons


def _write_polygon(boundary_paths: list[Path], polygon_path: Path) -> None:
    polygons: list[list[list[list[float]]]] = []
    for boundary_path in boundary_paths:
        polygons.extend(_extract_polygons(boundary_path))

    feature = {
        "type": "Feature",
        "properties": {
            "name": polygon_path.stem,
            "regions": [path.stem for path in boundary_paths],
        },
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": polygons,
        },
    }

    tmp_path = polygon_path.with_suffix(polygon_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(feature, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp_path, polygon_path)


def _is_up_to_date(output_path: Path, input_paths: list[Path]) -> bool:
    if not output_path.exists():
        return False
    output_mtime = output_path.stat().st_mtime
    return all(path.exists() and path.stat().st_mtime <= output_mtime for path in input_paths)


def _run_osmium_extract(source_pbf: Path, polygon_path: Path, output_pbf: Path) -> None:
    tmp_output = output_pbf.with_name(f"{output_pbf.stem}.tmp{output_pbf.suffix}")
    if tmp_output.exists():
        tmp_output.unlink()

    cmd = [
        "osmium",
        "extract",
        "--polygon",
        str(polygon_path),
        "--strategy",
        "complete_ways",
        "--set-bounds",
        "--overwrite",
        "--output",
        str(tmp_output),
        str(source_pbf),
    ]
    subprocess.run(cmd, check=True)
    os.replace(tmp_output, output_pbf)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build reduced walking OSM extract")
    parser.add_argument("--source", required=True, help="Source OSM PBF")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--output-stem", required=True, help="Output file stem without extension")
    parser.add_argument("--boundary", action="append", required=True, help="Boundary GeoJSON path")
    parser.add_argument("--force", action="store_true", help="Rebuild even if output is up to date")
    args = parser.parse_args()

    source_pbf = Path(args.source).resolve()
    output_dir = Path(args.output_dir).resolve()
    boundary_paths = [Path(path).resolve() for path in args.boundary]

    if not source_pbf.exists():
        raise FileNotFoundError(f"source pbf not found: {source_pbf}")
    for boundary_path in boundary_paths:
        if not boundary_path.exists():
            raise FileNotFoundError(f"boundary not found: {boundary_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    polygon_path = output_dir / f"{args.output_stem}-boundary.geojson"
    output_pbf = output_dir / f"{args.output_stem}.osm.pbf"

    _write_polygon(boundary_paths, polygon_path)

    inputs = [source_pbf, polygon_path, *boundary_paths]
    if args.force or not _is_up_to_date(output_pbf, inputs):
        _run_osmium_extract(source_pbf, polygon_path, output_pbf)

    print(output_pbf)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(exc.returncode)
