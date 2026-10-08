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


# provenance metadata（source_dataset / normalized_region_code）は呼び出し側（pipeline は dataset
# definition の dataset_id / expected_source_region_code）から受け取る。以前は東京固定値で、神奈川の
# 境界にも TOKYO-BOUNDARY-001 / 13 が付与されていた。geometry と N03 属性は変更しない。
GEOJSON_EXTENSIONS = {".geojson", ".json"}
METADATA_FIELDS = ("source_dataset", "normalized_region_code", "feature_index")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize administrative boundary data (N03) to GeoJSON.")
    parser.add_argument("--input", required=True, help="Input dataset path.")
    parser.add_argument("--output", required=True, help="Output GeoJSON path.")
    parser.add_argument("--dataset-id", required=True, help="source_dataset に記録する dataset ID")
    parser.add_argument("--region-code", required=True,
                        help="normalized_region_code（都道府県コード 2 桁）。N03_007 の先頭 2 桁と照合する")
    args = parser.parse_args()
    if not (len(args.region_code) == 2 and args.region_code.isdigit()):
        parser.error("--region-code は 2 桁の数字（例: 13, 14）")
    return args


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


def _normalize_feature(feature: dict, index: int, dataset_id: str, region_code: str) -> Optional[dict]:
    geometry = feature.get("geometry")
    if not geometry:
        return None
    properties = dict(feature.get("properties") or {})
    # normalizer が付与する metadata は常に上書きする（入力に旧値が残っていても引き継がない）
    properties["source_dataset"] = dataset_id
    properties["normalized_region_code"] = region_code
    properties["feature_index"] = index
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties,
    }


def _check_region_codes(features: list, region_code: str) -> None:
    """N03_007（全国地方公共団体コード）の先頭 2 桁が region_code と異なる feature があれば拒否する
    （別都道府県の原本を取り込んで metadata だけ付け替える事故を防ぐ）。N03_007 が無い feature は対象外。"""
    bad = sorted({str(f["properties"].get("N03_007"))[:2] for f in features
                  if f["properties"].get("N03_007") and str(f["properties"]["N03_007"])[:2] != region_code})
    if bad:
        raise ValueError(f"N03_007 の都道府県コード {bad} が --region-code {region_code} と一致しません")


def _build_normalized_collection(source_data: dict, source_name: str, dataset_id: str, region_code: str) -> dict:
    normalized_features = []
    for index, feature in enumerate(source_data.get("features", [])):
        normalized = _normalize_feature(feature, index, dataset_id, region_code)
        if normalized is not None:
            normalized_features.append(normalized)
    if not normalized_features:
        raise ValueError("Normalized boundary data contains no usable features.")
    _check_region_codes(normalized_features, region_code)
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
        normalized = _build_normalized_collection(source_data, source_name, args.dataset_id, args.region_code)
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
