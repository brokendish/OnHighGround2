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

A33 属性マッピング（バージョンによって番号が異なる場合あり）:
  A33_001 or A33_002 : 市区町村コード → city_code
  A33_003 or A33_006 : 区域名 → zone_name
  A33_004 or A33_003 : 区域区分コード → zone_type
  A33_005 or A33_004 : 現象種別コード → landslide_type

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
_ZONE_TYPE_MAP: dict[str | int, str] = {
    1: "warning",
    "1": "warning",
    "土砂災害警戒区域": "warning",
    "警戒区域": "warning",
    2: "special_warning",
    "2": "special_warning",
    "土砂災害特別警戒区域": "special_warning",
    "特別警戒区域": "special_warning",
}

_ZONE_TYPE_TO_SEVERITY: dict[str, str] = {
    "warning": "danger",
    "special_warning": "critical",
}

# ── landslide_type 正規化マップ ───────────────────────────────────────────────
_LANDSLIDE_TYPE_MAP: dict[str | int, str] = {
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

# ── A33 属性キー候補（バージョン違いを吸収） ─────────────────────────────────
# 複数候補を定義し、実際のデータに存在する最初のキーを採用する。
_CITY_CODE_KEYS   = ["A33_002", "A33_001"]
_ZONE_NAME_KEYS   = ["A33_006", "A33_003", "A33_007"]
_ZONE_TYPE_KEYS   = ["A33_004", "A33_003"]
_LANDSLIDE_TYPE_KEYS = ["A33_005", "A33_004"]
_PREF_CODE_KEYS   = ["A33_001"]


def _pick_key(props: dict, candidates: list[str]) -> tuple[str | None, object]:
    """候補キーリストから最初に存在するキーとその値を返す。なければ (None, None)。"""
    for key in candidates:
        if key in props:
            return key, props[key]
    return None, None


def _detect_key_mapping(sample_features: list[dict]) -> dict[str, str | None]:
    """サンプルフィーチャから実際に使われているキーを検出する。"""
    mapping: dict[str, str | None] = {}
    for feat in sample_features[:20]:
        props = feat.get("properties") or {}
        for label, candidates in [
            ("city_code",      _CITY_CODE_KEYS),
            ("zone_name",      _ZONE_NAME_KEYS),
            ("zone_type",      _ZONE_TYPE_KEYS),
            ("landslide_type", _LANDSLIDE_TYPE_KEYS),
            ("pref_code",      _PREF_CODE_KEYS),
        ]:
            if label not in mapping:
                for key in candidates:
                    if key in props:
                        mapping[label] = key
                        break
    return mapping


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

    # 最初のファイルからキーマッピングを検出
    with geojson_files[0].open("r", encoding="utf-8") as f:
        first_data = json.load(f)
    key_map = _detect_key_mapping(first_data.get("features", []))
    print(f"\n検出キーマッピング: {key_map}")

    # 未検出キーを警告
    for label in ["zone_type", "landslide_type"]:
        if label not in key_map:
            print(f"  警告: {label} のキーが検出できませんでした。unknown として扱います。",
                  file=sys.stderr)

    features_out: list[dict] = []
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

            # zone_type
            raw_zone = props.get(key_map.get("zone_type", ""), "") if key_map.get("zone_type") else ""
            zone_type = _ZONE_TYPE_MAP.get(raw_zone) or _ZONE_TYPE_MAP.get(str(raw_zone).strip())
            if zone_type is None:
                unknown_zone.add(raw_zone)
                zone_type = "unknown"
            severity_level = _ZONE_TYPE_TO_SEVERITY.get(zone_type, "unknown")

            # landslide_type
            raw_ltype = props.get(key_map.get("landslide_type", ""), "") if key_map.get("landslide_type") else ""
            landslide_type = _LANDSLIDE_TYPE_MAP.get(raw_ltype) or _LANDSLIDE_TYPE_MAP.get(str(raw_ltype).strip())
            if landslide_type is None:
                unknown_type.add(raw_ltype)
                landslide_type = "unknown"

            # その他属性
            zone_name  = props.get(key_map.get("zone_name",  ""), "") if key_map.get("zone_name") else ""
            city_code  = props.get(key_map.get("city_code",  ""), "") if key_map.get("city_code") else ""
            pref_code  = props.get(key_map.get("pref_code",  ""), "") if key_map.get("pref_code") else ""

            features_out.append({
                "type": "Feature",
                "properties": {
                    "hazard_type":     "landslide",
                    "landslide_type":  landslide_type,   # steep_slope / debris_flow / landslide / unknown
                    "zone_type":       zone_type,         # warning / special_warning / unknown
                    "severity_level":  severity_level,    # danger / critical / unknown
                    "zone_name":       zone_name,
                    "city_code":       str(city_code),
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
