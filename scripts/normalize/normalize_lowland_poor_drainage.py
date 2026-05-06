#!/usr/bin/env python3
"""
低位地帯（低地・排水困難エリア）Shapefile → GeoJSON 変換スクリプト
国土数値情報 G08 低位地帯データ対応

入力:
  data_lake/raw/{region}/lowland_poor_drainage/G08-15_{code}_GML.zip
    内部: G08-15_{code}.shp / .dbf / .prj / .shx

出力:
  data_lake/normalized/{region}/lowland_poor_drainage/lowland_poor_drainage.geojson

GML フィールド:
  G08_001: 標高 (m)
  G08_002: 潮位面からの深さ (m)
  G08_003: 種別コード (1=低位地帯)

座標系: JGD2011 (EPSG:6668) ≈ WGS84 → GeoJSON (lon/lat) 順に変換
変換ツール: ogr2ogr (GDAL)
"""

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REGION_CODE = {"tokyo": "13", "kanagawa": "14"}
OUT_NAME = "lowland_poor_drainage.geojson"

REQUIRED_PROPERTIES = {
    "dataset": "lowland_poor_drainage",
    "source": "MLIT G08 lowland",
    "risk": "low",
    "risk_score": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="低位地帯 Shapefile → GeoJSON 変換")
    parser.add_argument(
        "--region",
        required=True,
        choices=list(REGION_CODE.keys()),
        help="対象地域 (tokyo / kanagawa)",
    )
    parser.add_argument("--input", help="入力 ZIP パス (省略時は自動解決)")
    parser.add_argument("--output", help="出力 GeoJSON パス (省略時は自動解決)")
    return parser.parse_args()


def find_shp(zf: zipfile.ZipFile) -> str:
    """ZIP 内の .shp エントリ名を返す。"""
    shps = [n for n in zf.namelist() if n.lower().endswith(".shp")]
    if not shps:
        raise FileNotFoundError("ZIP 内に .shp が見つかりません")
    return shps[0]


def convert_shp_to_geojson(shp_path: Path, tmp_dir: Path) -> Path:
    """ogr2ogr を使って Shapefile → GeoJSON に変換する。"""
    out_path = tmp_dir / "raw.geojson"
    cmd = [
        "ogr2ogr",
        "-f", "GeoJSON",
        "-t_srs", "EPSG:4326",
        str(out_path),
        str(shp_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ogr2ogr 失敗:\n{result.stderr}")
    return out_path


def enrich_features(raw_geojson: dict, region: str) -> dict:
    """各 Feature に標準プロパティを付与する。"""
    enriched = []
    for feat in raw_geojson.get("features", []):
        geom = feat.get("geometry")
        if geom is None:
            continue
        props = {
            **REQUIRED_PROPERTIES,
            "region": region,
        }
        original = feat.get("properties") or {}
        if original.get("G08_001") is not None:
            props["elevation_m"] = original["G08_001"]
        if original.get("G08_002") is not None:
            props["depth_below_tide_m"] = original["G08_002"]
        enriched.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "name": OUT_NAME.replace(".geojson", ""), "features": enriched}


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent.parent

    zip_path = (
        Path(args.input)
        if args.input
        else repo_root / f"data_lake/raw/{args.region}/lowland_poor_drainage/G08-15_{REGION_CODE[args.region]}_GML.zip"
    )
    out_path = (
        Path(args.output)
        if args.output
        else repo_root / f"data_lake/normalized/{args.region}/lowland_poor_drainage/{OUT_NAME}"
    )

    if not zip_path.exists():
        print(f"エラー: 入力 ZIP が見つかりません: {zip_path}", file=sys.stderr)
        return 1

    print(f"入力: {zip_path}")
    print(f"出力: {out_path}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # ZIP 展開
        with zipfile.ZipFile(zip_path) as zf:
            shp_name = find_shp(zf)
            zf.extractall(tmp_dir)
            print(f"  .shp: {shp_name}  ({zip_path.stat().st_size / 1024:.0f} KB)")

        shp_path = tmp_dir / shp_name

        # ogr2ogr で GeoJSON 変換
        print("  ogr2ogr 変換中...", flush=True)
        raw_geojson_path = convert_shp_to_geojson(shp_path, tmp_dir)

        with raw_geojson_path.open(encoding="utf-8") as f:
            raw = json.load(f)

        total_raw = len(raw.get("features", []))
        print(f"  変換フィーチャ数: {total_raw:,}")

        # プロパティ付与
        result = enrich_features(raw, args.region)
        total_out = len(result["features"])

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")

        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"完了: {total_out:,} フィーチャ  {size_mb:.2f} MB  → {out_path}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
