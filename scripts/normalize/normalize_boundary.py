#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple


DATASET_ID = "TOKYO-BOUNDARY-001"
REGION_CODE = "13"
DEFAULT_OUTPUT = "data_lake/normalized/tokyo/boundary/tokyo_boundary.geojson"
GEOJSON_EXTENSIONS = {".geojson", ".json"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Tokyo boundary data to GeoJSON.")
    parser.add_argument("--input", required=True, help="Input dataset path.")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Output GeoJSON path.",
    )
    return parser.parse_args()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (_repo_root() / path).resolve()


def _ensure_shapefile_sidecars(shp_path: Path) -> Tuple[bool, list[str]]:
    required = [".dbf", ".shx"]
    missing = [suffix for suffix in required if not shp_path.with_suffix(suffix).exists()]
    return not missing, missing


def _run_ogr2ogr(input_path: Path, output_path: Path) -> None:
    ogr2ogr = shutil.which("ogr2ogr")
    if not ogr2ogr:
        raise RuntimeError("ogr2ogr is not available in this environment.")

    result = subprocess.run(
        [
            ogr2ogr,
            "-f",
            "GeoJSON",
            "-t_srs",
            "EPSG:4326",
            str(output_path),
            str(input_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"ogr2ogr failed: {stderr or 'unknown error'}")


def _load_geojson(input_path: Path) -> dict:
    with input_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("type") != "FeatureCollection":
        raise ValueError("Boundary input must be a GeoJSON FeatureCollection.")
    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError("Boundary input features must be a list.")
    return data


def _normalize_feature(feature: dict, index: int) -> Optional[dict]:
    geometry = feature.get("geometry")
    if not geometry:
        return None
    properties = dict(feature.get("properties") or {})
    properties.setdefault("source_dataset", DATASET_ID)
    properties.setdefault("normalized_region_code", REGION_CODE)
    properties.setdefault("feature_index", index)
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties,
    }


def _build_normalized_collection(source_data: dict, source_name: str) -> dict:
    normalized_features = []
    for index, feature in enumerate(source_data.get("features", [])):
        normalized = _normalize_feature(feature, index)
        if normalized is not None:
            normalized_features.append(normalized)
    if not normalized_features:
        raise ValueError("Normalized boundary data contains no usable features.")
    return {
        "type": "FeatureCollection",
        "name": f"{source_name}_normalized",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": normalized_features,
    }


def _convert_input_to_geojson(input_path: Path) -> Tuple[dict, str]:
    suffix = input_path.suffix.lower()

    if suffix in GEOJSON_EXTENSIONS:
        return _load_geojson(input_path), input_path.stem

    if suffix == ".shp":
        sidecars_ok, missing = _ensure_shapefile_sidecars(input_path)
        if not sidecars_ok:
            joined = ", ".join(missing)
            raise RuntimeError(
                f"Shapefile sidecar files are missing for {input_path.name}: {joined}. "
                "Upload the full shapefile set (.shp, .shx, .dbf, optional .prj) or a GeoJSON/ZIP package."
            )
        with tempfile.TemporaryDirectory(prefix="normalize-boundary-") as tmpdir:
            temp_geojson = Path(tmpdir) / f"{input_path.stem}.geojson"
            _run_ogr2ogr(input_path, temp_geojson)
            return _load_geojson(temp_geojson), input_path.stem

    if suffix == ".zip":
        with tempfile.TemporaryDirectory(prefix="normalize-boundary-zip-") as tmpdir:
            extract_dir = Path(tmpdir) / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(input_path) as archive:
                archive.extractall(extract_dir)

            shp_candidates = sorted(extract_dir.rglob("*.shp"))
            geojson_candidates = sorted(
                path for path in extract_dir.rglob("*") if path.suffix.lower() in GEOJSON_EXTENSIONS
            )
            if shp_candidates:
                chosen = shp_candidates[0]
                sidecars_ok, missing = _ensure_shapefile_sidecars(chosen)
                if not sidecars_ok:
                    joined = ", ".join(missing)
                    raise RuntimeError(
                        f"ZIP contains {chosen.name} but is missing required sidecars: {joined}."
                    )
                temp_geojson = Path(tmpdir) / f"{chosen.stem}.geojson"
                _run_ogr2ogr(chosen, temp_geojson)
                return _load_geojson(temp_geojson), chosen.stem
            if geojson_candidates:
                chosen = geojson_candidates[0]
                return _load_geojson(chosen), chosen.stem
            raise RuntimeError("ZIP does not contain a .shp or .geojson boundary dataset.")

    raise RuntimeError(
        f"Unsupported boundary input format: {input_path.suffix or '(no extension)'}. "
        "Use .geojson, .json, .zip, or a complete shapefile set."
    )


def main() -> int:
    args = parse_args()
    input_path = _resolve_path(args.input)
    output_path = _resolve_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    try:
        source_data, source_name = _convert_input_to_geojson(input_path)
        normalized = _build_normalized_collection(source_data, source_name)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote normalized boundary data to {output_path} ({len(normalized['features'])} features)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
