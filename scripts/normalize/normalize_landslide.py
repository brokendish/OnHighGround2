#!/usr/bin/env python3
"""
土砂災害警戒区域データ正規化スクリプト（国土数値情報 A33）

対応入力:
  - .geojson / .json              — A33 属性付き GeoJSON
  - .gml / .xml                   — A33 GML (ogr2ogr で GeoJSON 変換)
  - .shp                          — A33 Shapefile (ogr2ogr で GeoJSON 変換)
  - .zip                          — 上記ファイルを含む ZIP（自動展開）
  - ディレクトリ                   — 上記ファイルをサブディレクトリ含め再帰探索

出力: 正規化済み GeoJSON

処理内容:
  - A33 属性を標準プロパティに変換
  - zone_type / landslide_type / severity_level を付与
  - CRS を EPSG:4326 に統一（ogr2ogr が処理）

A33 属性マッピング（国土数値情報 A33-24 確認済み）:
  A33_001 : 現象種別コード → landslide_type
  A33_002 : 区域区分コード → zone_type
  A33_003 : 都道府県コード → pref_code
  A33_006 : 区域名       → zone_name

zone_type コード:
  1 / "1" / "土砂災害警戒区域"     → warning    (severity: danger)
  2 / "2" / "土砂災害特別警戒区域"  → special_warning (severity: critical)

landslide_type コード:
  1 / "1" / "急傾斜地の崩壊" → steep_slope
  2 / "2" / "土石流"         → debris_flow
  3 / "3" / "地すべり"       → landslide

使い方:
  python scripts/normalize/normalize_landslide.py --input data_lake/raw/kanagawa/landslide/A33-24_14_GML.zip --output data_lake/normalized/kanagawa/landslide/kanagawa-landslide-001.geojson
  python scripts/normalize/normalize_landslide.py --input data_lake/raw/tokyo/landslide/ --output data_lake/normalized/tokyo/landslide/tokyo-landslide-001.geojson
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

# ── zone_type 正規化マップ ────────────────────────────────────────────────────
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

# ── A33 属性キー（GeoJSON / ogr2ogr 変換後どちらにも対応） ─────────────────────
# ogr2ogr は属性名をそのまま保持するため変換後でも同じキーを使う
_KEY_LANDSLIDE_TYPE = "A33_001"
_KEY_ZONE_TYPE      = "A33_002"
_KEY_PREF_CODE      = "A33_003"
_KEY_ZONE_NAME      = "A33_006"


# ── ogr2ogr ヘルパー ──────────────────────────────────────────────────────────

def _run_ogr2ogr(input_path: Path, output_path: Path) -> None:
    """GML / SHP → GeoJSON（EPSG:4326）変換。ogr2ogr が必須。"""
    ogr2ogr = shutil.which("ogr2ogr")
    if not ogr2ogr:
        raise RuntimeError(
            "ogr2ogr が見つかりません。GDAL をインストールしてください。\n"
            "  apt-get install gdal-bin  または  brew install gdal"
        )
    result = subprocess.run(
        [ogr2ogr, "-f", "GeoJSON", str(output_path), str(input_path), "-t_srs", "EPSG:4326"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"ogr2ogr 失敗: {err or 'unknown error'}")


# ── 入力ローダー ──────────────────────────────────────────────────────────────

def _load_geojson_file(path: Path) -> list:
    """GeoJSON ファイルから feature リストを返す。"""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("features", [])


def _load_input(input_path: Path, tmp_dir: Path) -> list:
    """
    入力（ファイル / ディレクトリ）から GeoJSON feature リストを返す。
    ZIP は自動展開し、GML / SHP は ogr2ogr で変換してから読み込む。
    """
    if input_path.is_dir():
        return _load_from_directory(input_path, tmp_dir)

    suffix = input_path.suffix.lower()

    if suffix == ".zip":
        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(input_path) as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"ZIP を開けませんでした: {input_path.name} ({exc})")
        print(f"[info] ZIP 展開: {input_path.name} → {extract_dir}", file=sys.stderr)
        return _load_from_directory(extract_dir, tmp_dir)

    if suffix in (".geojson", ".json"):
        print(f"[info] GeoJSON 読み込み: {input_path}", file=sys.stderr)
        return _load_geojson_file(input_path)

    if suffix in (".gml", ".xml", ".shp"):
        converted = tmp_dir / f"{input_path.stem}_converted.geojson"
        print(f"[info] ogr2ogr 変換: {input_path.name} → {converted.name}", file=sys.stderr)
        _run_ogr2ogr(input_path, converted)
        return _load_geojson_file(converted)

    raise ValueError(f"未対応の入力形式: {input_path.suffix}")


def _load_from_directory(dir_path: Path, tmp_dir: Path) -> list:
    """
    ディレクトリを再帰探索し、GeoJSON / GML / SHP から features を集約する。
    優先順位: GeoJSON > GML/XML > SHP
    """
    features: list = []

    geojson_files = sorted(
        p for p in dir_path.rglob("*")
        if p.is_file() and p.suffix.lower() in (".geojson", ".json") and not p.name.startswith(".")
    )
    if geojson_files:
        for p in geojson_files:
            print(f"[info] GeoJSON: {p.relative_to(dir_path)}", file=sys.stderr)
            features.extend(_load_geojson_file(p))
        return features

    # GML / SHP を ogr2ogr で変換
    conv_sources = sorted(
        p for p in dir_path.rglob("*")
        if p.is_file() and p.suffix.lower() in (".gml", ".xml", ".shp") and not p.name.startswith(".")
    )
    if conv_sources:
        for p in conv_sources:
            out = tmp_dir / f"{p.stem}_{p.suffix[1:]}_converted.geojson"
            print(f"[info] ogr2ogr 変換: {p.relative_to(dir_path)}", file=sys.stderr)
            _run_ogr2ogr(p, out)
            features.extend(_load_geojson_file(out))
        return features

    raise ValueError(
        f"対応ファイルが見つかりません: {dir_path}\n"
        "対応形式: .geojson / .json / .gml / .xml / .shp"
    )


# ── 正規化処理 ────────────────────────────────────────────────────────────────

def normalize(raw_features: list, output_path: Path) -> int:
    features_out: list = []
    skipped = 0
    unknown_zone: set = set()
    unknown_type: set = set()

    for feat in raw_features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry")

        if not geom:
            skipped += 1
            continue

        # zone_type (A33_002: 1=警戒区域, 2=特別警戒区域)
        raw_zone = props.get(_KEY_ZONE_TYPE, "")
        zone_type = _ZONE_TYPE_MAP.get(raw_zone) or _ZONE_TYPE_MAP.get(str(raw_zone).strip())
        if zone_type is None:
            unknown_zone.add(str(raw_zone))
            zone_type = "unknown"
        severity_level = _ZONE_TYPE_TO_SEVERITY.get(zone_type, "unknown")

        # landslide_type (A33_001: 1=急傾斜地崩壊, 2=土石流, 3=地すべり)
        raw_ltype = props.get(_KEY_LANDSLIDE_TYPE, "")
        landslide_type = (
            _LANDSLIDE_TYPE_MAP.get(raw_ltype)
            or _LANDSLIDE_TYPE_MAP.get(str(raw_ltype).strip())
        )
        if landslide_type is None:
            unknown_type.add(str(raw_ltype))
            landslide_type = "unknown"

        zone_name = str(props.get(_KEY_ZONE_NAME, ""))
        pref_code = str(props.get(_KEY_PREF_CODE, ""))

        features_out.append({
            "type": "Feature",
            "properties": {
                "hazard_type":    "landslide",
                "landslide_type": landslide_type,
                "zone_type":      zone_type,
                "severity_level": severity_level,
                "zone_name":      zone_name,
                "pref_code":      pref_code,
                "source":         "A33",
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
        "name": "landslide_A33",
        "features": features_out,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"\n完了: {output_path}")
    print(f"  フィーチャ数: {len(features_out)} (スキップ: {skipped})")
    print(f"  ファイルサイズ: {size_mb:.2f} MB")

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


# ── エントリポイント ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="土砂災害警戒区域データ正規化 (A33)")
    parser.add_argument(
        "--input",
        required=True,
        help="入力パス（.geojson/.json/.gml/.xml/.shp/.zip またはディレクトリ）",
    )
    parser.add_argument("--output", required=True, help="出力 GeoJSON パス")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent.parent

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_absolute():
        input_path = repo_root / input_path
    if not output_path.is_absolute():
        output_path = repo_root / output_path

    if not input_path.exists():
        print(f"入力パスが見つかりません: {input_path}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="normalize-landslide-") as tmp:
        tmp_dir = Path(tmp)
        try:
            raw_features = _load_input(input_path, tmp_dir)
        except (ValueError, RuntimeError) as exc:
            print(f"入力読み込みエラー: {exc}", file=sys.stderr)
            return 1

    print(f"入力フィーチャ数（正規化前）: {len(raw_features)}")
    if not raw_features:
        print("フィーチャが 0 件です。入力データを確認してください。", file=sys.stderr)
        return 1

    return normalize(raw_features, output_path)


if __name__ == "__main__":
    sys.exit(main())
