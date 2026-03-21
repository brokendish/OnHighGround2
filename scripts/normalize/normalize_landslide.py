#!/usr/bin/env python3
"""
土砂災害警戒区域データ正規化スクリプト（国土数値情報 A33）

入力: data_lake/raw/tokyo/landslide/ 以下の全 *.geojson（サブディレクトリ含む）
      ※ Shapefile の場合は先に ogr2ogr で GeoJSON に変換すること:
         ogr2ogr -f GeoJSON A33-24_13.geojson A33-24_13.shp -t_srs EPSG:4326

出力: data_lake/normalized/tokyo/landslide/tokyo_landslide_A33.geojson

処理内容:
  - A33 属性を標準プロパティに変換
  - zone_type / landslide_type / severity_level を付与
  - CRS を EPSG:4326 に統一

A33-24 属性マッピング（東京都 GeoJSON 版で確認済み）:
  A33_001 : 現象種別コード → landslide_type
  A33_002 : 区域区分コード → zone_type
  A33_003 : 都道府県コード → pref_code
  A33_006 : 区域名 → zone_name

zone_type コード:
  1 / "1" / "土砂災害警戒区域"     → warning    (severity: danger)
  2 / "2" / "土砂災害特別警戒区域"  → special_warning (severity: critical)

landslide_type コード:
  1 / "1" / "急傾斜地の崩壊" → steep_slope
  2 / "2" / "土石流"         → debris_flow
  3 / "3" / "地すべり"       → landslide

使い方:
  python scripts/normalize/normalize_landslide.py
  python scripts/normalize/normalize_landslide.py --input-dir data_lake/raw/tokyo/landslide/ --output data_lake/normalized/tokyo/landslide/tokyo_landslide_A33.geojson
"""

import argparse
import json
import sys
from pathlib import Path

RAW_DEFAULT = "data_lake/raw/tokyo/landslide"
OUT_DEFAULT = "data_lake/normalized/tokyo/landslide/tokyo_landslide_A33.geojson"

# ── zone_type 正規化マップ ────────────────────────────────────────────────────
# コード（int/str）またはテキストから正規化形式へ
_ZONE_TYPE_MAP: dict = {
    1: "warning",
    "1": "warning",
    "土砂災害警戒区域": "warning",
    "警戒区域": "warning",
    2: "special_warning",
    "2": "special_warning",
    "土砂災害特別警戒区域": "special_warning",
    "特別警戒区域": "special_warning",
}

_ZONE_TYPE_TO_SEVERITY: dict = {
    "warning": "danger",
    "special_warning": "critical",
}

# ── landslide_type 正規化マップ ───────────────────────────────────────────────
_LANDSLIDE_TYPE_MAP: dict = {
    1: "steep_slope",
    "1": "steep_slope",
    "急傾斜地の崩壊": "steep_slope",
    "急傾斜地崩壊": "steep_slope",
    2: "debris_flow",
    "2": "debris_flow",
    "土石流": "debris_flow",
    3: "landslide",
    "3": "landslide",
    "地すべり": "landslide",
}

# ── A33 属性キーマッピング（A33-24 東京都 GeoJSON 版で確認済み） ─────────────
# A33_001: 現象種別コード  A33_002: 区域区分コード
# A33_003: 都道府県コード  A33_006: 区域名
_KEY_LANDSLIDE_TYPE = "A33_001"
_KEY_ZONE_TYPE      = "A33_002"
_KEY_PREF_CODE      = "A33_003"
_KEY_ZONE_NAME      = "A33_006"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="土砂災害警戒区域データ正規化 (A33)")
    parser.add_argument(
        "--input-dir",
        default=RAW_DEFAULT,
        help="A33 GeoJSON が格納されたディレクトリ（サブディレクトリ含む）",
    )
    parser.add_argument("--output", default=OUT_DEFAULT, help="出力 GeoJSON パス")
    return parser.parse_args()


def normalize(input_dir: Path, output_path: Path) -> int:
    geojson_files = sorted(input_dir.rglob("*.geojson"))
    if not geojson_files:
        print(f"GeoJSON ファイルが見つかりません: {input_dir}", file=sys.stderr)
        return 1

    print(f"入力ファイル数: {len(geojson_files)}")
    for p in geojson_files:
        print(f"  {p}")

    features_out: list = []
    skipped = 0
    unknown_zone: set = set()
    unknown_type: set = set()

    for src in geojson_files:
        with src.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            geom = feat.get("geometry")

            if not geom:
                skipped += 1
                continue

            # zone_type (A33_002: 1=警戒, 2=特別警戒)
            raw_zone = props.get(_KEY_ZONE_TYPE, "")
            zone_type = _ZONE_TYPE_MAP.get(raw_zone) or _ZONE_TYPE_MAP.get(str(raw_zone).strip())
            if zone_type is None:
                unknown_zone.add(raw_zone)
                zone_type = "unknown"
            severity_level = _ZONE_TYPE_TO_SEVERITY.get(zone_type, "unknown")

            # landslide_type (A33_001: 1=急傾斜地崩壊, 2=土石流, 3=地すべり)
            raw_ltype = props.get(_KEY_LANDSLIDE_TYPE, "")
            landslide_type = _LANDSLIDE_TYPE_MAP.get(raw_ltype) or _LANDSLIDE_TYPE_MAP.get(str(raw_ltype).strip())
            if landslide_type is None:
                unknown_type.add(raw_ltype)
                landslide_type = "unknown"

            zone_name = props.get(_KEY_ZONE_NAME, "")
            pref_code = props.get(_KEY_PREF_CODE, "")

            features_out.append({
                "type": "Feature",
                "properties": {
                    "hazard_type":     "landslide",
                    "landslide_type":  landslide_type,   # steep_slope / debris_flow / landslide / unknown
                    "zone_type":       zone_type,         # warning / special_warning / unknown
                    "severity_level":  severity_level,    # danger / critical / unknown
                    "zone_name":       str(zone_name),
                    "pref_code":       str(pref_code),
                    "source":          "A33",
                },
                "geometry": geom,
            })

    if unknown_zone:
        print(f"  警告: 未知の区域区分値（zone_type=unknown として出力）: {unknown_zone}",
              file=sys.stderr)
    if unknown_type:
        print(f"  警告: 未知の現象種別値（landslide_type=unknown として出力）: {unknown_type}",
              file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "type": "FeatureCollection",
        "name": "tokyo_landslide_A33",
        "features": features_out,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"\n完了: {output_path}")
    print(f"  フィーチャ数: {len(features_out)} (スキップ: {skipped})")
    print(f"  ファイルサイズ: {size_mb:.2f} MB")

    # 集計
    from collections import Counter
    zone_counts = Counter(f["properties"]["zone_type"] for f in features_out)
    type_counts = Counter(f["properties"]["landslide_type"] for f in features_out)
    print("  zone_type 別件数:")
    for k, v in sorted(zone_counts.items()):
        sev = _ZONE_TYPE_TO_SEVERITY.get(k, "?")
        print(f"    {k} (severity={sev}): {v}件")
    print("  landslide_type 別件数:")
    for k, v in sorted(type_counts.items()):
        print(f"    {k}: {v}件")

    return 0


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent.parent
    input_dir = Path(args.input_dir)
    output_path = Path(args.output)
    if not input_dir.is_absolute():
        input_dir = repo_root / input_dir
    if not output_path.is_absolute():
        output_path = repo_root / output_path

    if not input_dir.is_dir():
        print(f"入力ディレクトリが見つかりません: {input_dir}", file=sys.stderr)
        return 1

    return normalize(input_dir, output_path)


if __name__ == "__main__":
    sys.exit(main())
