#!/usr/bin/env python3
"""
normalize_shelter_p20.py — 国土数値情報 P20 避難施設 Shapefile を正規化 GeoJSON に変換する。

入力: P20-XX_NN_GML/*.shp  (NN = 都道府県コード)
出力: data_lake/normalized/{region}/shelter/{region}_shelter.geojson

バックエンド (main.py の load_emergency_shelters_from_geojson) が期待するプロパティ:
  施設名, 住所, designation, 洪水, 崖崩れ、土石流及び地滑り, 高潮, 地震, 津波, 大規模な火事

P20 フィールドマッピング:
  P20_001 → 市区町村コード
  P20_002 → 施設名
  P20_003 → 住所
  P20_004 → 施設種別 (避難所 / 指定緊急避難場所 / etc.)
  P20_005 → 収容人数
  P20_006 → 面積 (m²)
  P20_007 → 洪水          (1/0)
  P20_008 → 崖崩れ、土石流及び地滑り (1/0)
  P20_009 → 高潮          (1/0)
  P20_010 → 地震          (1/0)
  P20_011 → 津波          (1/0)
  P20_012 → 大規模な火事   (1/0)
  レベル  → 指定レベル
  備考    → 備考
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


# P20 フィールド → 出力プロパティ名のマッピング
P20_FIELD_MAP = {
    "P20_001": "市区町村コード",
    "P20_002": "施設名",
    "P20_003": "住所",
    "P20_004": "施設種別",
    "P20_005": "収容人数",
    "P20_006": "面積",
    "P20_007": "洪水",
    "P20_008": "崖崩れ、土石流及び地滑り",
    "P20_009": "高潮",
    "P20_010": "地震",
    "P20_011": "津波",
    "P20_012": "大規模な火事",
    "レベル":   "指定レベル",
    "備考":     "備考",
}

# 施設種別 → designation のマッピング
# P20_004 の値は自治体・年次によって表記が異なるため、部分一致で判定する。
# 2013年災害対策基本法改正前の P20 データ（P20-12 等）では「避難所」と記録されており、
# 現行の「指定緊急避難場所」に相当するため同義として扱う。
DESIGNATION_KEYWORDS = {
    "指定緊急避難場所": "指定緊急避難場所",
    "緊急避難":         "指定緊急避難場所",
    "避難所":           "指定緊急避難場所",
}


def detect_shp(input_path: Path) -> Path:
    """入力がディレクトリの場合、内部の .shp を探して返す。"""
    if input_path.is_file() and input_path.suffix.lower() == ".shp":
        return input_path
    if input_path.is_dir():
        shps = list(input_path.rglob("*.shp"))
        if not shps:
            raise FileNotFoundError(f".shp が見つかりません: {input_path}")
        if len(shps) > 1:
            print(f"[warn] .shp が複数見つかりました。最初のファイルを使用します: {shps[0]}", file=sys.stderr)
        return shps[0]
    raise FileNotFoundError(f"入力パスが見つかりません: {input_path}")


def shp_to_geojson(shp_path: Path) -> dict:
    """ogr2ogr で Shapefile → GeoJSON (WGS84) に変換し、dict として返す。"""
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    tmp_path.unlink()  # ogr2ogr は既存ファイルを上書きしないため事前に削除
    cmd = [
        "ogr2ogr",
        "-f", "GeoJSON",
        "-t_srs", "EPSG:4326",
        str(tmp_path),
        str(shp_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[error] ogr2ogr 失敗:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(tmp_path.read_text(encoding="utf-8"))
    tmp_path.unlink()
    return data


def map_designation(facility_type: str) -> str:
    """施設種別文字列から designation を決定する。"""
    if not facility_type:
        return "避難所"
    for keyword, designation in DESIGNATION_KEYWORDS.items():
        if keyword in facility_type:
            return designation
    return "避難所"


def normalize_feature(feature: dict, source_dataset: str, region_code: str):
    """1 フィーチャーを正規化して返す。ジオメトリ不正の場合は None。"""
    geometry = feature.get("geometry")
    if not geometry or geometry.get("type") != "Point":
        return None
    coords = geometry.get("coordinates", [])
    if len(coords) < 2:
        return None

    raw_props = feature.get("properties") or {}

    # フィールドリマップ
    props: dict = {}
    for p20_key, out_key in P20_FIELD_MAP.items():
        val = raw_props.get(p20_key)
        props[out_key] = val

    # ハザードフラグを 0/1 整数に統一
    hazard_keys = ["洪水", "崖崩れ、土石流及び地滑り", "高潮", "地震", "津波", "大規模な火事"]
    for key in hazard_keys:
        props[key] = 1 if str(props.get(key, "0")).strip() == "1" else 0

    # 収容人数: -1 は不明として None に変換
    capacity = props.get("収容人数")
    props["収容人数"] = None if (capacity is None or capacity == -1) else int(capacity)

    # designation
    props["designation"] = map_designation(props.get("施設種別") or "")

    # メタ
    props["source_dataset"] = source_dataset
    props["normalized_region_code"] = region_code

    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": props,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="国土数値情報 P20 避難施設 Shapefile を正規化 GeoJSON に変換する。"
    )
    parser.add_argument(
        "--input",
        default="data_lake/raw/kanagawa/shelter/P20-12_14_GML",
        help="入力 .shp ファイルまたはそれを含むディレクトリ",
    )
    parser.add_argument(
        "--output",
        default="data_lake/normalized/kanagawa/shelter/kanagawa_shelter.geojson",
        help="出力 GeoJSON パス",
    )
    parser.add_argument(
        "--source-dataset",
        default="KANAGAWA-SHELTER-P20",
        help="source_dataset プロパティに埋め込む識別子",
    )
    parser.add_argument(
        "--region-code",
        default="14",
        help="都道府県コード（デフォルト: 14 = 神奈川）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    shp_path = detect_shp(Path(args.input))
    print(f"[normalize_shelter_p20] 入力: {shp_path}")

    raw_geojson = shp_to_geojson(shp_path)

    features_in = raw_geojson.get("features", [])
    print(f"[normalize_shelter_p20] 読み込み件数: {len(features_in)}")

    normalized_features = []
    skipped = 0
    for f in features_in:
        nf = normalize_feature(f, args.source_dataset, args.region_code)
        if nf is None:
            skipped += 1
        else:
            normalized_features.append(nf)

    if skipped:
        print(f"[normalize_shelter_p20] スキップ（ジオメトリ不正）: {skipped} 件", file=sys.stderr)

    output = {
        "type": "FeatureCollection",
        "name": f"kanagawa_shelter_normalized",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": normalized_features,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[normalize_shelter_p20] 出力: {output_path}  ({len(normalized_features)} 件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
