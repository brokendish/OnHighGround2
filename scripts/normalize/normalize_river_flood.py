#!/usr/bin/env python3
"""
洪水浸水想定区域データ正規化スクリプト

対応入力フォーマット:
  - 単一 GeoJSON / JSON ファイル (.geojson, .json)
  - 単一 GML / XML ファイル (.gml, .xml) — 国土数値情報 A31a / A31b 形式
  - ZIP アーカイブ（内部の GeoJSON / GML を全件マージ）
  - ZIP の中に ZIP（ネスト ZIP を再帰展開）
  - ディレクトリ（.geojson / .json / .gml / .xml / .zip を再帰スキャン）

複数 ZIP をひとつにまとめてアップロードする場合:
  zip bundle.zip 荒川.zip 江戸川.zip 多摩川.zip

出力: GeoJSON FeatureCollection（ストリーミング書き出し）

正規化プロパティ:
  hazard_type   = "flood"
  dataset_id    = <--dataset-id 引数>
  flood_rank    (int 1-5): 浸水深区分
  depth_text    (str): 区分テキスト
  depth         (float): 代表浸水深 [m]
  river_name    (str): 河川名（あれば）
  river_number  (str): 河川番号（あれば）

浸水深ランク対応 (A31a_205 / A31b_205):
  1: 0.5m未満        → depth 0.25
  2: 0.5m以上3m未満  → depth 1.75
  3: 3m以上5m未満    → depth 4.00
  4: 5m以上10m未満   → depth 7.50
  5: 10m以上20m未満  → depth 15.0
"""

import argparse
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Generator, Iterator, Optional

# 国土数値情報 A31a/A31b ZIP 内の非 MaximumScale ディレクトリ（スキーマ不一致）
# 20_想定最大規模 以外のディレクトリはサイレントスキップする
_NON_MAXSCALE_DIR = re.compile(r"(?:^|[/\\])(?:10|30|41|42)_")

# ── ランクルックアップ ─────────────────────────────────────────────────────

# rank → (depth_text, representative_depth_m)
RANK_TABLE: dict[int, tuple] = {
    1: ("0.5m未満",       0.25),
    2: ("0.5m以上3m未満", 1.75),
    3: ("3m以上5m未満",   4.00),
    4: ("5m以上10m未満",  7.50),
    5: ("10m以上20m未満", 15.0),
}

# 浸水深テキスト → rank（テキストで入ってくる場合）
TEXT_TO_RANK: dict[str, int] = {v[0]: k for k, v in RANK_TABLE.items()}

# プロパティキー優先順: 正規化済みキー優先, 旧 raw キーはフォールバック
# flood_rank: _iter_gml_features が DEPTH_TO_RANK で変換済みの値を入れる（1-5）
# water_depth: ksj:waterDepth の生値（1-6）。flood_rank がない場合のフォールバック
_RANK_KEYS = ("flood_rank", "water_depth", "A31a_205", "A31b_205")


def _extract_rank(props: dict) -> int:
    """プロパティ辞書から flood_rank (1-5) を抽出する。不明なら 0。"""
    for key in _RANK_KEYS:
        val = props.get(key)
        if val is None:
            continue
        if isinstance(val, int) and val in RANK_TABLE:
            return val
        if isinstance(val, float) and int(val) in RANK_TABLE:
            return int(val)
        if isinstance(val, str):
            try:
                iv = int(float(val))
                if iv in RANK_TABLE:
                    return iv
            except (ValueError, TypeError):
                pass
            if val in TEXT_TO_RANK:
                return TEXT_TO_RANK[val]
    return 0


# ── GML ジオメトリユーティリティ ───────────────────────────────────────────
# 国土数値情報 GML 3.x 形式（A31a / A31b）に対応。
# 座標系は JGD2011 (EPSG:6668) で (lat, lon) 順のため lon/lat へ変換して出力する。

def _local(tag: str) -> str:
    """名前空間 URI を除いたローカル名を返す。"""
    return tag.split("}")[-1] if "}" in tag else tag


def _href_target(value: Optional[str]) -> Optional[str]:
    """xlink:href の値から '#' プレフィックスを除去して返す。"""
    if not value:
        return None
    return value[1:] if value.startswith("#") else value


def _elem_id(elem: ET.Element) -> Optional[str]:
    """gml:id 属性値を返す。"""
    for attr_name, attr_val in elem.attrib.items():
        if _local(attr_name) == "id":
            return attr_val
    return None


def _parse_pos_list(text: str) -> list[tuple[float, float]]:
    """
    GML posList テキスト（lat lon lat lon ...）を [(lon, lat), ...] のリストに変換する。
    GeoJSON は lon/lat 順のため、ここで swap する。
    """
    vals = text.split()
    return [
        (float(vals[i + 1]), float(vals[i]))   # (lon, lat)
        for i in range(0, len(vals) - 1, 2)
    ]


def _collect_curves(root: ET.Element) -> dict[str, list[tuple[float, float]]]:
    """
    ドキュメント全体から id 付き Curve / LineString / LinearRing を収集し、
    {id: [(lon, lat), ...]} の辞書を返す。OrientableCurve の方向反転も処理する。
    """
    curves: dict[str, list[tuple[float, float]]] = {}

    for elem in root.iter():
        if _local(elem.tag) not in ("Curve", "LineString", "LinearRing"):
            continue
        geom_id = _elem_id(elem)
        if not geom_id:
            continue
        for child in elem.iter():
            if _local(child.tag) == "posList" and child.text:
                coords = _parse_pos_list(child.text.strip())
                curves[geom_id] = coords
                # 国土数値情報 A31a/A31b の xlink:href は gml:id に '_' を付けて参照する
                # 例: gml:id="cv0_0" → xlink:href="#_cv0_0"
                # 両方のキーで引けるようにエイリアスを登録する
                curves["_" + geom_id] = coords
                break

    for elem in root.iter():
        if _local(elem.tag) != "OrientableCurve":
            continue
        geom_id = _elem_id(elem)
        if not geom_id:
            continue
        orientation = elem.attrib.get("orientation", "+")
        base_ref = None
        for child in elem:
            if _local(child.tag) == "baseCurve":
                base_ref = _href_target(
                    next((v for k, v in child.attrib.items() if _local(k) == "href"), None)
                )
                break
        if base_ref and base_ref in curves:
            coords = list(curves[base_ref])
            if orientation == "-":
                coords = list(reversed(coords))
            curves[geom_id] = coords
            curves["_" + geom_id] = coords

    return curves


def _collect_surfaces(
    root: ET.Element,
    curves: dict[str, list[tuple[float, float]]],
) -> dict[str, dict]:
    """
    ドキュメント全体から id 付き Surface / Polygon / MultiSurface を収集し、
    {id: geojson_geometry} の辞書を返す。
    """
    surfaces: dict[str, dict] = {}

    for elem in root.iter():
        local = _local(elem.tag)
        if local not in ("Surface", "Polygon", "MultiSurface"):
            continue
        geom_id = _elem_id(elem)
        if not geom_id:
            continue

        polygons: list[list[list[float]]] = []
        ring_refs: list[str] = []

        for child in elem.iter():
            if _local(child.tag) in ("curveMember", "ringMember"):
                href = _href_target(
                    next((v for k, v in child.attrib.items() if _local(k) == "href"), None)
                )
                if href:
                    ring_refs.append(href)
            elif _local(child.tag) == "posList" and child.text:
                ring = [[lon, lat] for lon, lat in _parse_pos_list(child.text.strip())]
                if ring and ring[0] != ring[-1]:
                    ring.append(ring[0])
                polygons.append([ring])

        if not polygons and ring_refs:
            ring: list[list[float]] = []
            for ref in ring_refs:
                coords = curves.get(ref, [])
                points = [[lon, lat] for lon, lat in coords]
                if ring and points and ring[-1] == points[0]:
                    ring.extend(points[1:])
                else:
                    ring.extend(points)
            if ring:
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                polygons.append([ring])

        if not polygons:
            continue

        geom_type = "MultiPolygon" if len(polygons) > 1 else "Polygon"
        surfaces[geom_id] = {
            "type": geom_type,
            "coordinates": polygons if geom_type == "MultiPolygon" else polygons[0],
        }

    return surfaces


def _extract_inline_geom(elem: ET.Element) -> Optional[dict]:
    """
    A31a_208 / A31b_208 要素に直接埋め込まれた GML ジオメトリを解析する。
    surfaceMember 単位で Polygon を収集し、複数なら MultiPolygon として返す。
    """
    polygons: list[list[list[list[float]]]] = []

    for sub in elem.iter():
        if _local(sub.tag) != "Polygon":
            continue
        rings: list[list[list[float]]] = []
        for ring_container in sub:               # exterior / interior
            rl = _local(ring_container.tag)
            if rl not in ("exterior", "interior"):
                continue
            for pos_elem in ring_container.iter():
                if _local(pos_elem.tag) == "posList" and pos_elem.text:
                    coords = [[lon, lat] for lon, lat in _parse_pos_list(pos_elem.text.strip())]
                    if len(coords) >= 3:
                        if coords[0] != coords[-1]:
                            coords.append(coords[0])
                        rings.append(coords)
                    break
        if rings:
            polygons.append(rings)

    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


# ── GML フィーチャ抽出 ────────────────────────────────────────────────────

# 国土数値情報 A31a/A31b の waterDepth (1-6) → flood_rank (1-5) 変換
# waterDepth=6 (20m以上) は最大ランク 5 に統合（RANK_TABLE の上限に合わせる）
DEPTH_TO_RANK: dict[int, int] = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 5}


def _parse_xml(raw: bytes, label: str) -> ET.Element:
    """
    XML バイト列を安全にパースして Element ツリーのルートを返す。

    ET.fromstring(raw) は一部の multi-byte encoding 宣言を持つファイルで失敗する。
    ET.parse(BytesIO(raw)) は encoding 宣言を正しく処理するため、こちらを使用する。
    """
    try:
        return ET.parse(io.BytesIO(raw)).getroot()
    except (ET.ParseError, ValueError) as exc:
        raise ValueError(f"GML/XML パースエラー ({label}): {exc}") from exc


def _iter_gml_features(raw: bytes, label: str) -> Iterator[dict]:
    """
    国土数値情報 A31a / A31b GML バイト列から Feature dict を yield する。

    実データの GML 構造:
      ksj:MaximumScale          ← フィーチャ単位（旧コードの "A31a"/"A31b" は誤り）
        ksj:bounds xlink:href="#sfN"   ← Surface への参照
        ksj:waterDepth          ← 浸水深ランク (1-6)
        ksj:riverName           ← 河川名
        ksj:riverNumber         ← 河川番号

    座標参照の特記事項:
      curveMember の xlink:href は "#_cvN_M" 形式（先頭に '_'）だが、
      Curve 要素の gml:id は "cvN_M" 形式（'_' なし）。
      _collect_curves() でエイリアスを登録することでこのミスマッチを吸収する。
    """
    try:
        root = _parse_xml(raw, label)
    except ValueError:
        raise

    curves   = _collect_curves(root)
    surfaces = _collect_surfaces(root, curves)

    found    = 0
    skipped  = 0

    for elem in root.iter():
        if _local(elem.tag) != "MaximumScale":
            continue

        water_depth  = 0
        river_name   = ""
        river_number = ""
        sf_id        = None

        for child in elem:
            cl = _local(child.tag)
            if cl == "bounds":
                href = _href_target(
                    next((v for k, v in child.attrib.items() if _local(k) == "href"), None)
                )
                if href:
                    sf_id = href
            elif cl == "waterDepth":
                try:
                    water_depth = int((child.text or "").strip())
                except ValueError:
                    pass
            elif cl == "riverName":
                river_name = (child.text or "").strip()
            elif cl == "riverNumber":
                river_number = (child.text or "").strip()

        if sf_id is None:
            skipped += 1
            continue

        geom = surfaces.get(sf_id)
        if geom is None:
            skipped += 1
            continue

        rank = DEPTH_TO_RANK.get(water_depth, 0)
        props: dict = {"flood_rank": rank, "water_depth": water_depth}
        if river_name:
            props["river_name"] = river_name
        if river_number:
            props["river_number"] = river_number

        found += 1
        yield {"type": "Feature", "geometry": geom, "properties": props}

    if found == 0:
        print(
            f"[WARN] {label}: MaximumScale フィーチャが見つかりませんでした "
            f"(surfaces={len(surfaces)}, curves={len(curves)//2}, skipped={skipped})\n"
            f"  → XML 構造が想定外の可能性があります",
            file=sys.stderr,
        )
    elif skipped:
        print(
            f"[WARN] {label}: {skipped} フィーチャをスキップ（surface 未解決）",
            file=sys.stderr,
        )


# ── 入力読み込み（ジェネレータ）────────────────────────────────────────────

def _parse_geojson_bytes(raw: bytes, label: str) -> dict:
    """
    バイト列を GeoJSON dict に変換する。
    失敗時は ValueError（呼び出し側が WARN してスキップ）。
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON 解析エラー ({label}): {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"GeoJSON ルートはオブジェクト必須 ({label})")
    if data.get("type") not in {"FeatureCollection", "Feature"}:
        raise ValueError(
            f"非対応 GeoJSON タイプ: {data.get('type')!r} ({label})\n"
            f"  対応: FeatureCollection / Feature"
        )
    return data


def _iter_zip(zf: zipfile.ZipFile, zip_label: str) -> Iterator[dict]:
    """
    ZipFile オブジェクト内のエントリを再帰的にスキャンし Feature を yield する。

    処理順序: GeoJSON → GML/XML → ネスト ZIP
    各エントリの失敗は WARN してスキップ（他エントリの処理を継続）。
    """
    names = sorted(
        n for n in zf.namelist()
        if not n.startswith("__MACOSX") and not n.endswith("/")
    )
    geojson_names = [n for n in names if n.lower().endswith((".geojson", ".json"))]
    gml_names     = [n for n in names if n.lower().endswith((".gml", ".xml"))]
    zip_names     = [n for n in names if n.lower().endswith(".zip")]

    if not geojson_names and not gml_names and not zip_names:
        print(
            f"[WARN] ZIP 内に対応ファイルなし（スキップ）: {zip_label}\n"
            f"  含まれるファイル: {names[:10]}{'...' if len(names) > 10 else ''}",
            file=sys.stderr,
        )
        return

    for name in geojson_names:
        label = f"{zip_label}::{name}"
        raw = zf.read(name)
        try:
            data = _parse_geojson_bytes(raw, label)
        except ValueError as exc:
            print(f"[WARN] スキップ: {exc}", file=sys.stderr)
            continue
        features = (
            data.get("features") or []
            if data["type"] == "FeatureCollection"
            else [data]
        )
        print(f"  [{label}] {len(features):,} フィーチャ (GeoJSON)")
        yield from features

    for name in gml_names:
        # 10_計画規模 / 30_セグメント / 41_ / 42_ は MaximumScale を持たない別スキーマ
        # WARN を出さずサイレントスキップ
        if _NON_MAXSCALE_DIR.search(name):
            continue
        label = f"{zip_label}::{name}"
        raw = zf.read(name)
        try:
            feats = list(_iter_gml_features(raw, label))
        except ValueError as exc:
            print(f"[WARN] GML スキップ: {exc}", file=sys.stderr)
            continue
        print(f"  [{label}] {len(feats):,} フィーチャ (GML)")
        yield from feats

    for name in zip_names:
        label = f"{zip_label}::{name}"
        raw = zf.read(name)
        try:
            inner_zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            print(f"[WARN] 内部 ZIP を開けません、スキップ: {label}: {exc}", file=sys.stderr)
            continue
        print(f"  内部 ZIP 展開: {label}")
        with inner_zf:
            yield from _iter_zip(inner_zf, label)


def iter_features(input_path: Path) -> Generator[dict, None, None]:
    """
    入力パス（ファイル / ZIP / ディレクトリ）から Feature dict を yield する。

    ディレクトリ: .geojson / .json / .gml / .xml / .zip を再帰スキャンして全件マージ
    ZIP        : 内部 GeoJSON・GML を全件マージ、ネスト ZIP も再帰展開
    GeoJSON    : 直接読み込み
    GML/XML    : A31a / A31b フォーマットとして解析

    ValueError: 入力が存在しない、対応形式でない、読み込み不可の場合。
    """
    if input_path.is_dir():
        sources = sorted(
            f for f in input_path.rglob("*")
            if f.is_file()
            and f.suffix.lower() in {".geojson", ".json", ".gml", ".xml", ".zip"}
        )
        if not sources:
            raise ValueError(
                f"ディレクトリ内に対応ファイルが見つかりません: {input_path}\n"
                f"  対応: .geojson / .json / .gml / .xml / .zip"
            )
        print(f"ディレクトリ読み込み: {len(sources)} ファイル")
        for fp in sources:
            yield from iter_features(fp)
        return

    suffix = input_path.suffix.lower()

    if suffix == ".zip":
        print(f"読み込み中 (ZIP): {input_path}")
        try:
            with zipfile.ZipFile(input_path, "r") as zf:
                yield from _iter_zip(zf, str(input_path))
        except zipfile.BadZipFile as exc:
            raise ValueError(
                f"ZIP 読み込みエラー: {input_path}\n"
                f"  ファイルが破損しているか ZIP 形式ではありません: {exc}"
            ) from exc
        return

    if suffix in {".geojson", ".json"}:
        print(f"読み込み中 (GeoJSON): {input_path}")
        try:
            raw = input_path.read_bytes()
        except OSError as exc:
            raise ValueError(f"ファイルを開けません: {exc}") from exc
        data = _parse_geojson_bytes(raw, str(input_path))
        features = (
            data.get("features") or []
            if data["type"] == "FeatureCollection"
            else [data]
        )
        print(f"  {len(features):,} フィーチャ (GeoJSON)")
        yield from features
        return

    if suffix in {".gml", ".xml"}:
        print(f"読み込み中 (GML): {input_path}")
        try:
            raw = input_path.read_bytes()
        except OSError as exc:
            raise ValueError(f"ファイルを開けません: {exc}") from exc
        yield from _iter_gml_features(raw, str(input_path))
        return

    raise ValueError(
        f"非対応の入力形式: {suffix!r}\n"
        f"  対応: .geojson / .json / .gml / .xml / .zip / ディレクトリ\n"
        f"  入力: {input_path}"
    )


# ── 正規化（ストリーミング書き出し）───────────────────────────────────────

def normalize(input_path: Path, output_path: Path, dataset_id: str) -> int:
    """
    iter_features() で取得した Feature を正規化しながら逐次書き出す。
    features リストを全件メモリに保持しないため、大規模データに対応。
    出力は tmp ファイルへ書き出し後に atomic rename する。
    """
    try:
        feature_iter = iter_features(input_path)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    total_in         = 0
    out_count        = 0
    skipped_no_geom  = 0
    skipped_bad_geom = 0
    unknown_rank_count = 0
    rank_counts: dict[int, int] = {}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.geojson")

    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            f.write('{"type":"FeatureCollection","name":"flood_merged","features":[\n')
            first = True

            for feat in feature_iter:
                total_in += 1
                props = feat.get("properties") or {}
                geom  = feat.get("geometry")

                if not geom:
                    skipped_no_geom += 1
                    continue

                geom_type = geom.get("type", "")
                if geom_type not in {"Polygon", "MultiPolygon"}:
                    skipped_bad_geom += 1
                    print(f"[WARN] 非対応ジオメトリをスキップ: {geom_type!r}", file=sys.stderr)
                    continue

                rank = _extract_rank(props)
                if rank == 0:
                    unknown_rank_count += 1
                rank_info  = RANK_TABLE.get(rank)
                depth_text = rank_info[0] if rank_info else ""
                depth      = rank_info[1] if rank_info else None

                out_props: dict = {
                    "hazard_type": "flood",
                    "flood_rank":  rank,
                    "depth_text":  depth_text,
                }
                if depth is not None:
                    out_props["depth"] = depth
                for extra in ("river_name", "river_number", "source"):
                    if props.get(extra):
                        out_props[extra] = props[extra]
                if dataset_id:
                    out_props["dataset_id"] = dataset_id

                if not first:
                    f.write(",\n")
                json.dump(
                    {"type": "Feature", "properties": out_props, "geometry": geom},
                    f, ensure_ascii=False, separators=(",", ":"),
                )
                first = False
                out_count += 1
                rank_counts[rank] = rank_counts.get(rank, 0) + 1

            f.write("\n]}\n")

    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        print(f"[ERROR] 出力書き込み中にエラーが発生しました: {exc}", file=sys.stderr)
        return 1

    if unknown_rank_count:
        print(
            f"[WARN] flood_rank を特定できなかったフィーチャ: {unknown_rank_count} 件 (rank=0 で出力)",
            file=sys.stderr,
        )

    if out_count == 0:
        tmp_path.unlink(missing_ok=True)
        print(
            f"[ERROR] 出力フィーチャが 0 件です。入力データを確認してください。\n"
            f"  入力: {total_in}  ジオメトリなし: {skipped_no_geom}  非対応ジオメトリ: {skipped_bad_geom}\n"
            f"  ヒント: 国土数値情報 A31a/A31b データの場合は「20_想定最大規模」ディレクトリを含む\n"
            f"          ZIP ファイルをアップロードしてください。10_/30_/41_/42_ のみのデータは\n"
            f"          MaximumScale 要素を持たないため取り込み対象外です。",
            file=sys.stderr,
        )
        return 1

    # atomic rename（書き込み途中で失敗しても既存ファイルを壊さない）
    tmp_path.replace(output_path)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"完了: {output_path}")
    print(f"  入力: {total_in:,}  出力: {out_count:,}  スキップ: {skipped_no_geom + skipped_bad_geom}")
    print(f"  ファイルサイズ: {size_mb:.1f} MB")
    print("  ランク別件数:")
    for r in sorted(rank_counts):
        label = RANK_TABLE.get(r, ("?",))[0]
        print(f"    rank {r} ({label}): {rank_counts[r]:,}件")

    return 0


# ── エントリポイント ──────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="洪水浸水想定区域データ正規化 (A31a / A31b GML, GeoJSON)",
        epilog=(
            "複数 ZIP をひとつにまとめる場合:\n"
            "  zip bundle.zip 荒川.zip 江戸川.zip 多摩川.zip\n"
            "  python normalize_river_flood.py --input bundle.zip --output out.geojson"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        required=True,
        help="入力パス（.geojson / .json / .gml / .xml / .zip / ディレクトリ）",
    )
    parser.add_argument("--output",     required=True, help="出力 GeoJSON パス")
    parser.add_argument("--dataset-id", default="",    help="データセット ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root   = Path(__file__).resolve().parent.parent.parent
    input_path  = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_absolute():
        input_path = repo_root / input_path
    if not output_path.is_absolute():
        output_path = repo_root / output_path

    if not input_path.exists():
        print(
            f"[ERROR] 入力が見つかりません: {input_path}\n"
            f"  data_lake/raw/tokyo/flood/ にデータを配置してください。",
            file=sys.stderr,
        )
        return 1

    return normalize(input_path, output_path, dataset_id=args.dataset_id)


if __name__ == "__main__":
    sys.exit(main())
