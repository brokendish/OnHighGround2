#!/usr/bin/env python3
"""
土砂災害警戒区域データ正規化スクリプト（国土数値情報 A33）

対応入力:
  - .zip  — A33-24_XX_GML.zip（内部の .xml を自動展開）
  - .gml / .xml — A33 GML ファイル
  - .geojson / .json — A33 属性付き GeoJSON
  - ディレクトリ — 上記を含むディレクトリ（再帰）

GML 構造（A33-24 形式）:
  ksj:Dataset
    gml:Curve(×N)   ← 座標列（posList）を保持
    gml:Surface(×N) ← Curve を xlink:href で参照
    ksj:SedimentRelatedDisasterWarningAreasPolygon(×N)
                    ← Surface を xlink:href で参照 + 属性(cop/coz/prc/znm)

メモリ対策:
  ET.iterparse を使い要素ごとにストリーム処理する。
  処理済み要素は root から除去・clear() してメモリを解放。
  Curve 座標はフラットタプルで保持しリスト-of-リストより約 8 倍省メモリ。

属性名（A33-24 新形式）:
  ksj:cop → 現象種別コード  1=急傾斜, 2=土石流, 3=地すべり
  ksj:coz → 区域区分コード  1=警戒, 2=特別警戒
  ksj:prc → 都道府県コード
  ksj:znm → 区域名

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
from typing import Dict, List, Optional, Tuple

# ── 正規化マップ ──────────────────────────────────────────────────────────────

_ZONE_TYPE_MAP: dict = {
    "1": "warning",        1: "warning",
    "2": "special_warning", 2: "special_warning",
    "土砂災害警戒区域": "warning",   "警戒区域": "warning",
    "土砂災害特別警戒区域": "special_warning", "特別警戒区域": "special_warning",
}
_ZONE_TYPE_TO_SEVERITY: dict = {
    "warning": "danger",
    "special_warning": "critical",
}
_LANDSLIDE_TYPE_MAP: dict = {
    "1": "steep_slope",  1: "steep_slope",
    "2": "debris_flow",  2: "debris_flow",
    "3": "landslide",    3: "landslide",
    "急傾斜地の崩壊": "steep_slope", "急傾斜地崩壊": "steep_slope",
    "土石流": "debris_flow",
    "地すべり": "landslide",
}


# ── 座標ユーティリティ ────────────────────────────────────────────────────────

def _poslist_to_flat(text: str) -> tuple:
    """
    GML posList（lat lon 順）をフラットタプル（lon lat 順）に変換。
    tuple で保持することでリスト-of-リストより約 8 倍省メモリ。
    (lon1, lat1, lon2, lat2, ...)
    """
    vals = text.split()
    result = []
    for i in range(0, len(vals) - 1, 2):
        try:
            lat = float(vals[i])
            lon = float(vals[i + 1])
            result.append(lon)
            result.append(lat)
        except ValueError:
            continue
    return tuple(result)


def _flat_to_ring(flat: tuple) -> list:
    """フラットタプル → [[lon,lat],...] (GeoJSON ring 形式)"""
    return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]


# ── Surface ヘルパー ──────────────────────────────────────────────────────────

def _surface_elem_to_geom(surf_elem, gml_ns: str, xlink_ns: str,
                           curves: Dict[str, tuple]) -> Optional[dict]:
    """
    gml:Surface 要素から GeoJSON Polygon を生成する。
    Curve はフラットタプル辞書から解決する。
    """
    def ring_from_ring_elem(ring_elem) -> list:
        all_flat: list = []
        for cm in ring_elem.findall(f"{{{gml_ns}}}curveMember"):
            href = cm.attrib.get(f"{{{xlink_ns}}}href", "").lstrip("#")
            flat = curves.get(href)
            if flat is None:
                continue
            # 前の終点と重複する場合は先頭を除く
            if all_flat and len(flat) >= 2:
                if all_flat[-2] == flat[0] and all_flat[-1] == flat[1]:
                    flat = flat[2:]
            all_flat.extend(flat)
        if len(all_flat) < 6:  # 最低 3 点
            return []
        ring = _flat_to_ring(tuple(all_flat))
        # GeoJSON リングは閉じている必要がある
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return ring

    exterior = surf_elem.find(f".//{{{gml_ns}}}exterior")
    if exterior is None:
        return None
    ext_ring_elem = exterior.find(f"{{{gml_ns}}}Ring")
    if ext_ring_elem is None:
        return None
    ext_ring = ring_from_ring_elem(ext_ring_elem)
    if not ext_ring:
        return None

    rings = [ext_ring]
    for interior in surf_elem.findall(f".//{{{gml_ns}}}interior"):
        int_ring_elem = interior.find(f"{{{gml_ns}}}Ring")
        if int_ring_elem is not None:
            int_ring = ring_from_ring_elem(int_ring_elem)
            if int_ring:
                rings.append(int_ring)

    return {"type": "Polygon", "coordinates": rings}


# ── GML ストリーミングパーサー ────────────────────────────────────────────────

def _parse_gml_streaming(xml_stream, filename: str) -> list:
    """
    iterparse によるストリーミング GML 解析。

    処理フロー（A33-24 ドキュメント順に対応）:
      1. gml:Curve       → 座標をフラットタプルで curves dict に蓄積、即 clear
      2. gml:Surface     → Curve を解決して geom を surfaces dict に蓄積、即 clear
      3. ksj:Sediment... → Surface を解決して feature を生成、surfaces.pop で解放

    root.remove(elem) + elem.clear() により処理済み要素をメモリから解放する。
    """
    try:
        context = ET.iterparse(xml_stream, events=("start", "end"))
        event, root = next(context)   # <ksj:Dataset> start イベント
    except ET.ParseError as exc:
        raise ValueError(f"{filename}: XML パースエラー ({exc})")
    except StopIteration:
        raise ValueError(f"{filename}: 空の XML")

    # 名前空間を root タグから検出
    ksj_ns = root.tag.split("}")[0][1:] if "}" in root.tag else ""
    if not ksj_ns:
        raise ValueError(f"{filename}: ksj 名前空間を検出できませんでした (root={root.tag!r})")
    print(f"[gml] {filename}: ksj_ns={ksj_ns!r}", file=sys.stderr)

    xlink_ns = "http://www.w3.org/1999/xlink"
    gml_ns = ""   # 最初の gml 要素で自動検出

    # curves:   curve_id → flat tuple (lon1,lat1,lon2,lat2,...)
    # surfaces: surface_id → GeoJSON geometry dict
    curves:   Dict[str, tuple] = {}
    surfaces: Dict[str, dict]  = {}
    features: List[dict] = []

    curve_count = surface_count = feat_count = 0

    for event, elem in context:
        if event != "end":
            continue

        tag   = elem.tag
        local = tag.split("}")[1] if "}" in tag else tag

        # GML 名前空間を最初の GML 要素から自動検出
        if not gml_ns and "}" in tag:
            ns = tag.split("}")[0][1:]
            if "opengis.net/gml" in ns or "schemas.opengis.net/gml" in ns:
                gml_ns = ns
                print(f"[gml] gml_ns={gml_ns!r}", file=sys.stderr)

        # ── Curve 処理 ────────────────────────────────────────────────────
        if local == "Curve" and gml_ns:
            cid = elem.attrib.get(f"{{{gml_ns}}}id") or elem.attrib.get("id", "")
            if cid:
                pl = elem.find(f".//{{{gml_ns}}}posList")
                if pl is not None and pl.text:
                    flat = _poslist_to_flat(pl.text)
                    if flat:
                        curves[cid] = flat
                        curve_count += 1
            try:
                root.remove(elem)
            except ValueError:
                pass
            elem.clear()

        # ── Surface 処理 ─────────────────────────────────────────────────
        elif local == "Surface" and gml_ns:
            sid = elem.attrib.get(f"{{{gml_ns}}}id") or elem.attrib.get("id", "")
            if sid:
                geom = _surface_elem_to_geom(elem, gml_ns, xlink_ns, curves)
                if geom:
                    surfaces[sid] = geom
                    surface_count += 1
            try:
                root.remove(elem)
            except ValueError:
                pass
            elem.clear()

        # ── Feature 処理 ─────────────────────────────────────────────────
        elif "SedimentRelatedDisasterWarningAreasPolygon" in local:
            bounds = elem.find(f"{{{ksj_ns}}}bounds")
            if bounds is not None:
                href = bounds.attrib.get(f"{{{xlink_ns}}}href", "").lstrip("#")
                # pop で参照解除 → Surface dict のメモリを逐次解放
                geom = surfaces.pop(href, None)
                if geom:
                    def _txt(key: str) -> str:
                        e = elem.find(f"{{{ksj_ns}}}{key}")
                        return (e.text or "").strip() if e is not None else ""
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "A33_001": _txt("cop"),
                            "A33_002": _txt("coz"),
                            "A33_003": _txt("prc"),
                            "A33_006": _txt("znm"),
                        },
                        "geometry": geom,
                    })
                    feat_count += 1
            try:
                root.remove(elem)
            except ValueError:
                pass
            elem.clear()

    print(
        f"[gml] Curve={curve_count}, Surface={surface_count}, Feature={feat_count}",
        file=sys.stderr,
    )
    return features


# ── 入力ローダー ──────────────────────────────────────────────────────────────

def _load_geojson_stream(data: bytes, filename: str) -> list:
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
        return _load_from_zip(input_path, tmp_dir)

    if suffix in (".geojson", ".json"):
        print(f"[info] GeoJSON: {input_path.name}", file=sys.stderr)
        return _load_geojson_stream(input_path.read_bytes(), input_path.name)

    if suffix in (".gml", ".xml"):
        print(f"[info] GML: {input_path.name}", file=sys.stderr)
        with input_path.open("rb") as f:
            return _parse_gml_streaming(f, input_path.name)

    raise ValueError(f"未対応の入力形式: {input_path.suffix} ({input_path.name})")


def _load_from_zip(zip_path: Path, tmp_dir: Path) -> list:
    """ZIP をストリーム展開し、GML/GeoJSON を解析する。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist()
                     if not n.startswith("__MACOSX") and not n.endswith("/")]
    except zipfile.BadZipFile as exc:
        raise ValueError(f"ZIP を開けませんでした: {zip_path.name} ({exc})")

    # ファイル種別で優先順位
    gml_entries  = [n for n in names if n.lower().endswith((".xml", ".gml"))
                    and "META" not in n.upper() and "KS-META" not in n]
    json_entries = [n for n in names if n.lower().endswith((".geojson", ".json"))]

    print(f"[info] ZIP={zip_path.name}: gml={gml_entries}, json={json_entries}",
          file=sys.stderr)

    if not gml_entries and not json_entries:
        all_names = [n for n in names if not n.endswith("/")]
        raise ValueError(
            f"ZIP 内に対応ファイルが見つかりません: {zip_path.name}\n"
            f"含まれるファイル: {all_names[:15]}"
        )

    features: list = []

    # GeoJSON を優先（GML より高速・低メモリ）
    if json_entries:
        with zipfile.ZipFile(zip_path) as zf:
            for entry in json_entries:
                print(f"[info] JSON in ZIP: {entry}", file=sys.stderr)
                data = zf.read(entry)
                features.extend(_load_geojson_stream(data, entry))
        return features

    # GML をストリームで直接パース（ファイルに展開せず ZIP から直接読む）
    with zipfile.ZipFile(zip_path) as zf:
        for entry in gml_entries:
            print(f"[info] GML in ZIP: {entry}", file=sys.stderr)
            with zf.open(entry) as gml_stream:
                features.extend(_parse_gml_streaming(gml_stream, entry))

    return features


def _load_from_directory(dir_path: Path, tmp_dir: Path) -> list:
    all_files = [
        p for p in sorted(dir_path.rglob("*"))
        if p.is_file() and not p.name.startswith(".")
    ]
    geojson_files = [p for p in all_files if p.suffix.lower() in (".geojson", ".json")]
    gml_files = [
        p for p in all_files
        if p.suffix.lower() in (".gml", ".xml") and "META" not in p.name.upper()
    ]

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
