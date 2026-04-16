#!/usr/bin/env python3
"""
土砂災害警戒区域データ正規化スクリプト（国土数値情報 A33）

対応入力:
  - .zip  — A33-24_XX_GML.zip（内部の .xml を自動展開）
  - .gml / .xml — A33 GML ファイル
  - .geojson / .json — A33 属性付き GeoJSON
  - ディレクトリ — 上記を含むディレクトリ（再帰）

GML 構造（A33-24 形式）:
  GML トポロジーモデルを使用。
  Feature → ksj:bounds.xlink:href → gml:Surface
  gml:Surface → gml:Ring.curveMember.xlink:href → gml:Curve
  gml:Curve → gml:posList（lat lon 順、GeoJSON では lon lat に反転）

属性名（A33-24 新形式）:
  ksj:cop → 現象種別コード → landslide_type
  ksj:coz → 区域区分コード → zone_type
  ksj:prc → 都道府県コード → pref_code
  ksj:znm → 区域名 → zone_name

zone_type:
  1 → warning (severity: danger)     ← 土砂災害警戒区域
  2 → special_warning (severity: critical) ← 特別警戒区域

landslide_type:
  1 → steep_slope  (急傾斜地の崩壊)
  2 → debris_flow  (土石流)
  3 → landslide    (地すべり)

使い方:
  python scripts/normalize/normalize_landslide.py \\
    --input  data_lake/raw/kanagawa/landslide/A33-24_14_GML.zip \\
    --output data_lake/normalized/kanagawa/landslide/kanagawa-landslide-001.geojson
"""

import argparse
import json
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# ── 正規化マップ ──────────────────────────────────────────────────────────────

_ZONE_TYPE_MAP: dict = {
    # A33-24 新形式 (cop / coz の値)
    "1": "warning",   "1": "warning",
    "2": "special_warning",
    # 旧 A33_002 形式
    1: "warning",  2: "special_warning",
    "土砂災害警戒区域": "warning",   "警戒区域": "warning",
    "土砂災害特別警戒区域": "special_warning", "特別警戒区域": "special_warning",
}
_ZONE_TYPE_TO_SEVERITY: dict = {
    "warning": "danger",
    "special_warning": "critical",
}
_LANDSLIDE_TYPE_MAP: dict = {
    # A33-24 新形式
    "1": "steep_slope",  1: "steep_slope",
    "2": "debris_flow",  2: "debris_flow",
    "3": "landslide",    3: "landslide",
    # テキスト形式（旧）
    "急傾斜地の崩壊": "steep_slope", "急傾斜地崩壊": "steep_slope",
    "土石流": "debris_flow",
    "地すべり": "landslide",
}


# ── GML パーサー（A33-24 トポロジーモデル対応） ──────────────────────────────

def _poslist_to_coords(text: str) -> list:
    """
    GML posList（lat lon 順）を GeoJSON 座標リスト（lon lat 順）に変換。
    """
    vals = text.split()
    coords = []
    for i in range(0, len(vals) - 1, 2):
        try:
            lat = float(vals[i])
            lon = float(vals[i + 1])
            coords.append([lon, lat])
        except ValueError:
            continue
    return coords


def _parse_gml(content: bytes, filename: str) -> list:
    """
    A33 GML バイト列を解析し GeoJSON feature リストを返す。

    A33-24 GML はトポロジーモデルを使う。
      Feature.bounds xlink:href → Surface
      Surface.(exterior|interior).Ring.curveMember xlink:href → Curve
      Curve.posList → 座標列

    処理順:
      1. 全 Curve を id → 座標リストの dict に収集
      2. 全 Surface を id → GeoJSON geometry の dict に構築
      3. 全 Feature を走査して geometry を解決
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"{filename}: XML パースエラー ({exc})")

    # 名前空間 URI を root タグから検出
    import re
    ns_match = re.match(r"\{(.+?)\}", root.tag)
    ksj_ns = ns_match.group(1) if ns_match else ""
    if not ksj_ns:
        raise ValueError(f"{filename}: GML 名前空間を検出できませんでした (root={root.tag!r})")

    # GML 名前空間は属性や子要素から推定する
    gml_ns = "http://schemas.opengis.net/gml/3.2.1"
    xlink_ns = "http://www.w3.org/1999/xlink"

    # 代替 GML 名前空間をフォールバックとして試みる
    GML_NS_CANDIDATES = [
        "http://schemas.opengis.net/gml/3.2.1",
        "http://www.opengis.net/gml/3.2",
        "http://www.opengis.net/gml",
    ]

    print(f"[gml] {filename}: ksj_ns={ksj_ns!r}", file=sys.stderr)

    # ── Step1: Curve を収集 ─────────────────────────────────────────────────
    curves: dict[str, list] = {}  # curve_id → [[lon, lat], ...]
    for ns in GML_NS_CANDIDATES:
        for curve in root.iter(f"{{{ns}}}Curve"):
            cid = curve.attrib.get(f"{{{ns}}}id") or curve.attrib.get("id")
            if not cid:
                continue
            pl = curve.find(f".//{{{ns}}}posList")
            if pl is not None and pl.text:
                coords = _poslist_to_coords(pl.text)
                if coords:
                    curves[cid] = coords
        if curves:
            gml_ns = ns
            break

    print(f"[gml] Curve 数: {len(curves)}", file=sys.stderr)

    def _ring_coords_from_ring_elem(ring_elem) -> list:
        """gml:Ring 要素から座標リストを返す（各 curveMember を結合）。"""
        all_coords: list = []
        for cm in ring_elem.findall(f"{{{gml_ns}}}curveMember"):
            href = cm.attrib.get(f"{{{xlink_ns}}}href", "")
            cid = href.lstrip("#")
            coords = curves.get(cid, [])
            if all_coords and coords:
                # 前の座標列の末尾と重複する場合は除去
                if all_coords[-1] == coords[0]:
                    coords = coords[1:]
            all_coords.extend(coords)
        # GeoJSON リングは閉じている必要がある
        if all_coords and all_coords[0] != all_coords[-1]:
            all_coords.append(all_coords[0])
        return all_coords

    # ── Step2: Surface を収集 ──────────────────────────────────────────────
    surfaces: dict[str, dict] = {}  # surface_id → GeoJSON geometry

    for surf in root.iter(f"{{{gml_ns}}}Surface"):
        sid = surf.attrib.get(f"{{{gml_ns}}}id") or surf.attrib.get("id")
        if not sid:
            continue

        exterior_elem = surf.find(f".//{{{gml_ns}}}exterior")
        if exterior_elem is None:
            continue
        ext_ring = exterior_elem.find(f"{{{gml_ns}}}Ring")
        if ext_ring is None:
            continue

        ext_coords = _ring_coords_from_ring_elem(ext_ring)
        if len(ext_coords) < 3:
            continue

        rings = [ext_coords]

        # interior rings（穴）
        for interior_elem in surf.findall(f".//{{{gml_ns}}}interior"):
            int_ring = interior_elem.find(f"{{{gml_ns}}}Ring")
            if int_ring is not None:
                int_coords = _ring_coords_from_ring_elem(int_ring)
                if len(int_coords) >= 3:
                    rings.append(int_coords)

        surfaces[sid] = {"type": "Polygon", "coordinates": rings}

    print(f"[gml] Surface 数: {len(surfaces)}", file=sys.stderr)

    # ── Step3: Feature を走査して GeoJSON feature を生成 ─────────────────
    # A33-24 の feature 要素名は SedimentRelatedDisasterWarningAreasPolygon
    # ただし将来バージョン変化に備え ksj:bounds を持つ要素を全て対象とする
    FEATURE_TYPE = f"{{{ksj_ns}}}SedimentRelatedDisasterWarningAreasPolygon"
    BOUNDS_KEY   = f"{{{ksj_ns}}}bounds"

    features_out: list = []
    skipped = 0

    for feat in root.iter(FEATURE_TYPE):
        bounds = feat.find(BOUNDS_KEY)
        if bounds is None:
            skipped += 1
            continue
        href = bounds.attrib.get(f"{{{xlink_ns}}}href", "")
        sid = href.lstrip("#")
        geom = surfaces.get(sid)
        if geom is None:
            skipped += 1
            continue

        # 属性取得（A33-24 新形式: cop/coz/prc/znm）
        def txt(key: str) -> str:
            elem = feat.find(f"{{{ksj_ns}}}{key}")
            return (elem.text or "").strip() if elem is not None else ""

        features_out.append({
            "type": "Feature",
            "properties": {
                # 生属性をそのまま保持（normalize() でマッピング済みに変換）
                "A33_001": txt("cop"),   # 現象種別コード
                "A33_002": txt("coz"),   # 区域区分コード
                "A33_003": txt("prc"),   # 都道府県コード
                "A33_006": txt("znm"),   # 区域名
            },
            "geometry": geom,
        })

    print(f"[gml] Feature 生成: {len(features_out)}, skipped={skipped}", file=sys.stderr)
    return features_out


# ── 入力ローダー ──────────────────────────────────────────────────────────────

def _load_geojson_bytes(data: bytes, filename: str) -> list:
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{filename}: JSON パースエラー ({exc})")
    return obj.get("features", [])


def _load_input(input_path: Path, tmp_dir: Path) -> list:
    if input_path.is_dir():
        return _load_from_directory(input_path, tmp_dir)

    suffix = input_path.suffix.lower()

    if suffix == ".zip":
        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(input_path) as zf:
                # __MACOSX などのメタデータを除いて展開
                for member in zf.namelist():
                    if not member.startswith("__MACOSX"):
                        zf.extract(member, extract_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"ZIP を開けませんでした: {input_path.name} ({exc})")
        print(f"[info] ZIP 展開: {input_path.name}", file=sys.stderr)
        return _load_from_directory(extract_dir, tmp_dir)

    if suffix in (".geojson", ".json"):
        print(f"[info] GeoJSON: {input_path.name}", file=sys.stderr)
        return _load_geojson_bytes(input_path.read_bytes(), input_path.name)

    if suffix in (".gml", ".xml"):
        print(f"[info] GML: {input_path.name}", file=sys.stderr)
        return _parse_gml(input_path.read_bytes(), input_path.name)

    raise ValueError(f"未対応の入力形式: {input_path.suffix} ({input_path.name})")


def _load_from_directory(dir_path: Path, tmp_dir: Path) -> list:
    all_files = [
        p for p in sorted(dir_path.rglob("*"))
        if p.is_file() and not p.name.startswith(".")
    ]
    geojson_files = [p for p in all_files if p.suffix.lower() in (".geojson", ".json")]
    gml_files     = [p for p in all_files if p.suffix.lower() in (".gml", ".xml")
                     and "META" not in p.name.upper()]

    if not geojson_files and not gml_files:
        raise ValueError(
            f"対応ファイルが見つかりません: {dir_path}\n"
            f"対応形式: .geojson/.json/.gml/.xml\n"
            f"含まれるファイル: {[p.name for p in all_files[:15]]}"
        )

    src_files = geojson_files if geojson_files else gml_files
    features: list = []
    for p in src_files:
        try:
            rel = p.relative_to(dir_path)
        except ValueError:
            rel = p.name
        print(f"[info] 読み込み: {rel}", file=sys.stderr)
        features.extend(_load_input(p, tmp_dir))

    return features


# ── 正規化処理 ────────────────────────────────────────────────────────────────

_KEY_LANDSLIDE_TYPE = "A33_001"
_KEY_ZONE_TYPE      = "A33_002"
_KEY_PREF_CODE      = "A33_003"
_KEY_ZONE_NAME      = "A33_006"


def normalize(raw_features: list, output_path: Path) -> int:
    features_out: list = []
    skipped = 0
    unknown_zone: set = set()
    unknown_type: set = set()

    for feat in raw_features:
        props = feat.get("properties") or {}
        geom  = feat.get("geometry")

        if not geom:
            skipped += 1
            continue

        raw_zone = props.get(_KEY_ZONE_TYPE, "")
        zone_type = (
            _ZONE_TYPE_MAP.get(raw_zone)
            or _ZONE_TYPE_MAP.get(str(raw_zone).strip())
        )
        if zone_type is None:
            unknown_zone.add(str(raw_zone))
            zone_type = "unknown"
        severity_level = _ZONE_TYPE_TO_SEVERITY.get(zone_type, "unknown")

        raw_ltype = props.get(_KEY_LANDSLIDE_TYPE, "")
        landslide_type = (
            _LANDSLIDE_TYPE_MAP.get(raw_ltype)
            or _LANDSLIDE_TYPE_MAP.get(str(raw_ltype).strip())
        )
        if landslide_type is None:
            unknown_type.add(str(raw_ltype))
            landslide_type = "unknown"

        features_out.append({
            "type": "Feature",
            "properties": {
                "hazard_type":    "landslide",
                "landslide_type": landslide_type,
                "zone_type":      zone_type,
                "severity_level": severity_level,
                "zone_name":      str(props.get(_KEY_ZONE_NAME, "")),
                "pref_code":      str(props.get(_KEY_PREF_CODE, "")),
                "source":         "A33",
            },
            "geometry": geom,
        })

    if unknown_zone:
        print(f"  警告: 未知の区域区分値 → zone_type=unknown: {unknown_zone}", file=sys.stderr)
    if unknown_type:
        print(f"  警告: 未知の現象種別値 → landslide_type=unknown: {unknown_type}", file=sys.stderr)

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
        "--input", required=True,
        help="入力パス（.zip/.gml/.xml/.geojson/.json またはディレクトリ）",
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
