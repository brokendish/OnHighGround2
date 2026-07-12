#!/usr/bin/env python3
"""
simplify_municipality_boundaries.py

/live/stream 小画面 (地震・キキクル・豪雨) の市区町村境界線表示 (Phase 8-B / 8-B.1) 用に、
全国市区町村境界データを地方ブロック単位の軽量 GeoJSON に変換する。

入力: data_lake/raw/nationwide/boundary/N03-21_{pref_code}_210101.json (47都道府県分)
      scripts/download/download_municipality_boundaries_nationwide.py で事前取得しておくこと。
      データソース: スマートニュース メディア研究所 japan-topography
      (加工元は国土交通省 国土数値情報「行政区域」データ)。

処理:
  1. 都道府県コードを8地方ブロックに割り当てる (北海道/東北/関東/中部/近畿/中国/四国/九州・沖縄)
  2. 同一市区町村コード (N03_007) の断片があれば shapely.unary_union で統合
     (入力データは基本1市区町村=1featureだが、将来別ソースに切り替わっても壊れないよう保持する)
  3. ラベル用代表点 (representative_point) と bbox を事前計算して properties に埋め込む
  4. 不要な property を落とし、座標精度を丸めてファイルサイズを削減

出力: frontend/layers/administrative/municipality_boundaries/{block}.geojson (8ファイル)
  小画面は表示中の bbox に応じて必要なブロックだけを遅延ロードする
  (frontend/js/live-stream/live-stream-municipality-boundary.js 側で制御)。

Usage:
  venv/bin/python scripts/derive/simplify_municipality_boundaries.py
  venv/bin/python scripts/derive/simplify_municipality_boundaries.py --tolerance 0.0005
"""

import argparse
import json
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT / "data_lake/raw/nationwide/boundary"
OUTPUT_DIR = ROOT / "frontend/layers/administrative/municipality_boundaries"

COORD_PRECISION = 5  # 小数点以下桁数 (約1m精度、mini-map用途には十分)

# 8地方ブロック定義 (都道府県コード2桁)。ファイル名は指示書の案Bの例と揃える。
BLOCKS = {
    "hokkaido":       ["01"],
    "tohoku":         ["02", "03", "04", "05", "06", "07"],
    "kanto":          ["08", "09", "10", "11", "12", "13", "14"],
    "chubu":          ["15", "16", "17", "18", "19", "20", "21", "22", "23"],
    "kinki":          ["24", "25", "26", "27", "28", "29", "30"],
    "chugoku":        ["31", "32", "33", "34", "35"],
    "shikoku":        ["36", "37", "38", "39"],
    "kyushu_okinawa": ["40", "41", "42", "43", "44", "45", "46", "47"],
}


def _muni_name(props):
    # 標準 N03 スキーマ: N03_003 = 郡・政令指定都市名 (例: 横浜市), N03_004 = 市区町村名 (例: 中区)。
    # 政令指定都市の区は N03_003+N03_004 (例: 横浜市中区)、それ以外は N03_004 のみでよい。
    designated_city = props.get("N03_003")
    muni = props.get("N03_004") or ""
    return f"{designated_city}{muni}" if designated_city else muni


def _round_coords(geom_mapping, ndigits):
    def _round_ring(ring):
        return [[round(x, ndigits), round(y, ndigits)] for x, y in ring]

    if geom_mapping["type"] == "Polygon":
        geom_mapping["coordinates"] = [_round_ring(r) for r in geom_mapping["coordinates"]]
    elif geom_mapping["type"] == "MultiPolygon":
        geom_mapping["coordinates"] = [
            [_round_ring(r) for r in poly] for poly in geom_mapping["coordinates"]
        ]
    return geom_mapping


def _load_prefecture_features(pref_code):
    src = RAW_DIR / f"N03-21_{pref_code}_210101.json"
    if not src.exists():
        print(f"[skip] raw file not found for pref {pref_code}: {src}")
        return []
    data = json.loads(src.read_text())
    return data.get("features", [])


def _process_block(pref_codes, tolerance):
    # code -> { name, pref, pref_code, frags: [shapely geometry, ...] }
    groups = {}
    for pref_code in pref_codes:
        for feat in _load_prefecture_features(pref_code):
            props = feat.get("properties") or {}
            code = props.get("N03_007")
            geom = feat.get("geometry")
            if not code or not geom:
                continue
            g = groups.setdefault(code, {
                "name": _muni_name(props), "pref": props.get("N03_001"),
                "pref_code": pref_code, "frags": [],
            })
            try:
                g["frags"].append(shape(geom))
            except Exception as e:
                print(f"[warn] failed to parse geometry for {code}: {e}")

    out_features = []
    for code, g in sorted(groups.items()):
        try:
            merged = g["frags"][0] if len(g["frags"]) == 1 else unary_union(g["frags"])
            if not merged.is_valid:
                merged = merged.buffer(0)
            simplified = merged.simplify(tolerance, preserve_topology=True) if tolerance > 0 else merged
            if simplified.is_empty:
                simplified = merged
            rep_point = simplified.representative_point()
        except Exception as e:
            print(f"[warn] failed to process {code} ({g['name']}): {e}")
            continue

        geom_map = _round_coords(mapping(simplified), COORD_PRECISION)
        minx, miny, maxx, maxy = simplified.bounds
        out_features.append({
            "type": "Feature",
            "properties": {
                "code": code,
                "name": g["name"],
                "pref": g["pref"],
                "pref_code": g["pref_code"],
                "cx": round(rep_point.x, COORD_PRECISION),
                "cy": round(rep_point.y, COORD_PRECISION),
                "bbox": [round(minx, COORD_PRECISION), round(miny, COORD_PRECISION),
                         round(maxx, COORD_PRECISION), round(maxy, COORD_PRECISION)],
            },
            "geometry": geom_map,
        })
    return out_features


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tolerance", type=float, default=0.0003,
                         help="追加簡略化トレランス (度単位。既定 0.0003 ≈ 30m。"
                              "入力は既に1%簡略化済みのため軽めでよい。0 で無効化)")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    total_munis = 0
    for block, pref_codes in BLOCKS.items():
        features = _process_block(pref_codes, args.tolerance)
        out_path = args.output_dir / f"{block}.geojson"
        out_path.write_text(json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False, separators=(",", ":"),
        ))
        total_munis += len(features)
        print(f"{block}: {len(features)} municipalities -> {out_path.stat().st_size / 1024:.0f} KB")

    print(f"\ntotal municipalities: {total_munis}")
    print(f"written to: {args.output_dir}")


if __name__ == "__main__":
    main()
