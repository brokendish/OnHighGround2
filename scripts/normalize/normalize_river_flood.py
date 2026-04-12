#!/usr/bin/env python3
"""
洪水浸水想定区域データ正規化スクリプト

対応入力フォーマット:
  - 単一 GeoJSON / JSON ファイル (.geojson, .json)
  - ZIP アーカイブ（内部の GeoJSON / 洪水 GML を全件マージ）
  - ZIP の中に ZIP（ネスト ZIP を一時ファイルに書き出して再帰処理）
  - ディレクトリ（.geojson / .json / .zip を再帰スキャン）

注意: 単体 GML/XML ファイルは非対応。
  A31a/A31b データは国土数値情報配布の ZIP アーカイブのまま入力してください。

複数 ZIP をひとつにまとめてアップロードする場合:
  zip bundle.zip 荒川.zip 江戸川.zip 多摩川.zip

出力: GeoJSON FeatureCollection（ストリーミング書き出し）

GML 変換:
  国土数値情報 A31a/A31b GML は非標準スキーマ（ksj:Dataset ルート + xlink ジオメトリ参照）
  のため GDAL/ogr2ogr では処理できない。Python xml.etree.ElementTree.iterparse を使用。

  A31 GML 構造:
    ksj:Dataset
      gml:Curve gml:id="cvN"   → 座標列（lat lon 順）
      gml:Surface gml:id="sfN" → curveMember xlink:href="#cvN"
      ksj:MaximumScale gml:id="idN"
        ksj:bounds xlink:href="#sfN"
        ksj:waterDepth (1-6)
        ksj:riverName / ksj:riverNumber (A31a のみ)
  全 Curve/Surface が MaximumScale より先に出現するため 1 パス処理可能。

正規化プロパティ:
  hazard_type   = "flood"
  dataset_id    = <--dataset-id 引数>
  flood_rank    (int 1-5): 浸水深区分
  depth_text    (str): 区分テキスト
  depth         (float): 代表浸水深 [m]
  river_name    (str): 河川名（あれば）
  river_number  (str): 河川番号（あれば）

浸水深ランク対応 (A31a/A31b waterDepth 1-6 → flood_rank 1-5):
  1: 0.5m未満        → depth 0.25
  2: 0.5m以上3m未満  → depth 1.75
  3: 3m以上5m未満    → depth 4.00
  4: 5m以上10m未満   → depth 7.50
  5: 10m以上20m未満  → depth 15.0
  6: 20m以上         → rank 5（上位区分に統合）
"""

import argparse
import array
import json
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Generator, Iterator, Optional

# 洪水本体 GML のファイル名許可パターン（許可方式）
#
# ZIP 内の .xml/.gml は以下のみ処理する:
#   A31a-20-*.xml / A31b-20-*.xml  →  20_想定最大規模（MaximumScale 要素あり）
#
# 除外（サイレントスキップ）:
#   KS-META-*.xml   … メタデータ XML
#   A31a-10-*.xml   … 10_計画規模
#   A31a-30/41/42-* … その他スキーマ
_FLOOD_GML_PATTERN = re.compile(r"^A31[ab]-20-", re.IGNORECASE)

# 進捗ログ出力間隔
_GML_PROGRESS_INTERVAL    = 5_000   # ogr2ogr 出力ストリーミング時
_NORMALIZE_LOG_INTERVAL   = 10_000  # normalize() 全体カウント


def _is_flood_gml(name: str) -> bool:
    """ZIP エントリ名または Path から、洪水本体 GML として処理すべきかを返す。"""
    basename = name.replace("\\", "/").rsplit("/", 1)[-1]
    return bool(_FLOOD_GML_PATTERN.match(basename))


# ── ランクルックアップ ─────────────────────────────────────────────────────

# rank → (depth_text, representative_depth_m)
RANK_TABLE: dict[int, tuple] = {
    1: ("0.5m未満",       0.25),
    2: ("0.5m以上3m未満", 1.75),
    3: ("3m以上5m未満",   4.00),
    4: ("5m以上10m未満",  7.50),
    5: ("10m以上20m未満", 15.0),
}

# 浸水深テキスト → rank
TEXT_TO_RANK: dict[str, int] = {v[0]: k for k, v in RANK_TABLE.items()}

# A31a/A31b waterDepth (1-6) → flood_rank (1-5)
# waterDepth=6 (20m以上) は最大ランク 5 に統合
DEPTH_TO_RANK: dict[int, int] = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 5}


def _extract_rank(props: dict) -> int:
    """
    プロパティ辞書から flood_rank (1-5) を抽出する。不明なら 0。

    対応キー（優先順）:
      flood_rank   : 正規化済み (1-5)
      water_depth  : 生値 (1-6) → DEPTH_TO_RANK で変換
                     ※ ogr2ogr 出力の waterDepth は _iter_gml_features_ogr2ogr で
                        water_depth にリネーム済み
      A31a_205 / A31b_205: 旧フォーマット (int/str/text)
    """
    # flood_rank: 正規化済み (1-5)
    val = props.get("flood_rank")
    if val is not None:
        try:
            iv = int(float(val)) if isinstance(val, str) else int(val)
            if iv in RANK_TABLE:
                return iv
        except (ValueError, TypeError):
            pass

    # water_depth: 生値 (1-6) → DEPTH_TO_RANK 変換
    val = props.get("water_depth")
    if val is not None:
        try:
            iv = int(float(val)) if isinstance(val, str) else int(val)
            r = DEPTH_TO_RANK.get(iv, 0)
            if r:
                return r
        except (ValueError, TypeError):
            pass

    # A31a/A31b 旧フォーマット
    for key in ("A31a_205", "A31b_205"):
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


# ── A31a/A31b GML XML パーサー（iterparse ベース）─────────────────────────────
#
# 国土数値情報 A31a/A31b GML は非標準スキーマ（ksj:Dataset ルート + xlink ジオメトリ）
# のため GDAL/ogr2ogr では geometry=None となり変換できない。
# xml.etree.ElementTree.iterparse を使って 1 パスで処理する。
#
# ZIP 内のエントリ名が Shift-JIS（CP932）エンコードのため、Python zipfile で
# 展開すると文字化けする。extractall を使わず read() で個別に読み出す。

# GML / KSJ の XML 名前空間
_NS_GML   = "http://schemas.opengis.net/gml/3.2.1"
_NS_KSJ   = "http://nlftp.mlit.go.jp/ksj/schemas/ksj-app"
_NS_XLINK = "http://www.w3.org/1999/xlink"

_TAG_CURVE    = f"{{{_NS_GML}}}Curve"
_TAG_SURFACE  = f"{{{_NS_GML}}}Surface"
_TAG_POSLIST  = f"{{{_NS_GML}}}posList"
_TAG_CURVE_MB = f"{{{_NS_GML}}}curveMember"
_TAG_MS       = f"{{{_NS_KSJ}}}MaximumScale"
_TAG_BOUNDS   = f"{{{_NS_KSJ}}}bounds"
_TAG_WD       = f"{{{_NS_KSJ}}}waterDepth"
_TAG_RNAME    = f"{{{_NS_KSJ}}}riverName"
_TAG_RNUM     = f"{{{_NS_KSJ}}}riverNumber"
_ATTR_ID      = f"{{{_NS_GML}}}id"
_ATTR_HREF    = f"{{{_NS_XLINK}}}href"


def _parse_a31_xml_stream(xml_source, out_path: Path, label: str) -> int:
    """
    A31a/A31b GML XML をストリーミングで解析し、GeoJSONSeq を out_path に書き出す。

    xml_source: ファイルパス (str/Path) またはファイルライクオブジェクト。
    大きなファイル (337MB 等) でも zf.open() ストリームを渡せばメモリを使い切らない。

    処理フロー（1パス iterparse）:
      1. gml:Curve  → ID: [[lon,lat], ...]  curves dict に蓄積
      2. gml:Surface → ID: [[lon,lat], ...] surfaces dict に蓄積（curve を解決）
      3. ksj:MaximumScale → feature を出力（surface を解決）

    座標系: GML の posList は (lat lon) 順 → GeoJSON (lon lat) にスワップ。

    Returns:
        int: 出力したフィーチャ数

    Raises:
        ValueError: パース失敗または出力 0 件
    """
    # array.array('d', [x0,y0, x1,y1, ...]) で格納 → Python list より約 8 倍省メモリ
    curves: dict[str, array.array]   = {}  # gml_id → array('d', flat xy)
    surfaces: dict[str, array.array] = {}  # gml_id → array('d', flat xy)
    count = 0
    geom_none_count = 0

    try:
        context = ET.iterparse(xml_source, events=("start", "end"))
    except Exception as exc:
        raise ValueError(f"XML 解析エラー: {label}: {exc}") from exc

    # depth カウンタで「root の直下要素が完了した」タイミングを検出し、
    # root.remove(elem) で元ツリーから切り離してメモリを解放する。
    # （elem.clear() だけでは root._children にゴミが残りメモリリークになる）
    root: Optional[ET.Element] = None
    depth = 0

    with out_path.open("w", encoding="utf-8") as fout:
        for event, elem in context:
            if event == "start":
                depth += 1
                if depth == 1:
                    root = elem  # ksj:Dataset ルート要素
                continue

            # event == "end"
            depth -= 1

            if depth != 1:
                # root の直下でない子孫要素 → スキップ（親要素が完了時にまとめて解放）
                continue

            tag = elem.tag

            if tag == _TAG_CURVE:
                gml_id = elem.get(_ATTR_ID)
                if gml_id:
                    pos_el = elem.find(f".//{_TAG_POSLIST}")
                    if pos_el is not None and pos_el.text:
                        vals = pos_el.text.split()
                        # posList は lat lon lat lon … 順 → flat xy [lon,lat, lon,lat, ...]
                        flat = array.array("d", [
                            v
                            for i in range(0, len(vals) - 1, 2)
                            for v in (float(vals[i + 1]), float(vals[i]))  # lon, lat
                        ])
                        curves[gml_id] = flat

            elif tag == _TAG_SURFACE:
                gml_id = elem.get(_ATTR_ID)
                if gml_id:
                    flat_pts: array.array = array.array("d")
                    for cm in elem.findall(f".//{_TAG_CURVE_MB}"):
                        href = cm.get(_ATTR_HREF, "")
                        if href.startswith("#"):
                            curve_id = href[1:]
                            cv = curves.pop(curve_id, None)  # 参照済み curve を解放
                            if cv:
                                flat_pts.extend(cv)
                    if flat_pts:
                        surfaces[gml_id] = flat_pts

            elif tag == _TAG_MS:
                # ジオメトリ解決
                geom = None
                bounds_el = elem.find(_TAG_BOUNDS)
                if bounds_el is not None:
                    href = bounds_el.get(_ATTR_HREF, "")
                    if href.startswith("#"):
                        surface_id = href[1:]
                        flat_ring = surfaces.pop(surface_id, None)  # 参照済み surface を解放
                        if flat_ring:
                            # flat array → [[lon,lat], ...] for GeoJSON
                            ring = [
                                [flat_ring[j], flat_ring[j + 1]]
                                for j in range(0, len(flat_ring), 2)
                            ]
                            geom = {"type": "Polygon", "coordinates": [ring]}

                if geom is None:
                    geom_none_count += 1

                # プロパティ抽出
                props: dict = {}
                wd_el = elem.find(_TAG_WD)
                if wd_el is not None and wd_el.text:
                    try:
                        props["water_depth"] = int(wd_el.text)
                    except ValueError:
                        props["water_depth"] = wd_el.text

                rn_el = elem.find(_TAG_RNAME)
                if rn_el is not None and rn_el.text:
                    props["river_name"] = rn_el.text

                rno_el = elem.find(_TAG_RNUM)
                if rno_el is not None and rno_el.text:
                    props["river_number"] = rno_el.text

                feat = {"type": "Feature", "properties": props, "geometry": geom}
                fout.write(json.dumps(feat, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1

                if count % _GML_PROGRESS_INTERVAL == 0:
                    print(f"  [{label}] {count:,} フィーチャ処理中...", file=sys.stderr)

            # root 直下要素を処理したら root から切り離してメモリ解放
            if root is not None:
                root.remove(elem)

    if geom_none_count:
        print(
            f"  [{label}] ジオメトリ解決できなかったフィーチャ: {geom_none_count} 件",
            file=sys.stderr,
        )

    if count == 0:
        raise ValueError(
            f"A31 GML パース後のフィーチャが 0 件: {label}\n"
            f"  ヒント: ZIP 内に A31a-20-* / A31b-20-* の GML ファイルが含まれているか確認してください。"
        )

    print(f"  [{label}] {count:,} フィーチャ (A31 GML parser)", file=sys.stderr)
    return count


def _iter_a31_zip(zip_path: Path, label: str) -> Iterator[dict]:
    """
    A31 ZIP（内部に A31a-20-* / A31b-20-* GML を含む）をパースし Feature を yield する。

    ZIP エントリは CP932（Shift-JIS）エンコードのため zipfile.read() で個別に読む。
    一時ファイルを経由せずバイト列で直接 _parse_a31_xml_bytes に渡す。

    Raises:
        ValueError: 変換失敗、空出力
    """
    with zipfile.ZipFile(zip_path) as zf:
        # ZIP エントリ名を CP932 で正しくデコード（flag_bits bit11 が未設定の場合）
        entries: list[tuple[str, str]] = []
        for info in zf.infolist():
            raw_name = info.filename
            if not (info.flag_bits & 0x800):  # UTF-8 フラグ未設定
                try:
                    decoded = raw_name.encode("raw_unicode_escape").decode("cp932")
                    entries.append((raw_name, decoded))
                except Exception:
                    entries.append((raw_name, raw_name))
            else:
                entries.append((raw_name, raw_name))

        # A31a-20-* / A31b-20-* GML のみ処理
        gml_entries = [
            (raw, dec) for raw, dec in entries
            if _is_flood_gml(dec) and dec.lower().endswith(".xml")
        ]

        if not gml_entries:
            raise ValueError(
                f"ZIP 内に A31a-20-* / A31b-20-* の GML ファイルが見つかりません: {label}\n"
                f"  エントリ例: {[dec for _, dec in entries[:5]]}"
            )

        print(
            f"  [{label}] A31 GML {len(gml_entries)} 件を処理します",
            file=sys.stderr,
        )

        for raw_name, dec_name in gml_entries:
            file_label = f"{label}::{Path(dec_name).name}"
            print(f"  [{file_label}] 読み込み中...", file=sys.stderr)

            with tempfile.TemporaryDirectory(prefix="a31_parse_") as tmpdir:
                out_path = Path(tmpdir) / "out.geojsonl"
                try:
                    # zf.open() でストリーミング読み込み（大容量ファイルをメモリに展開しない）
                    with zf.open(raw_name) as xml_stream:
                        _parse_a31_xml_stream(xml_stream, out_path, file_label)
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc

                # GeoJSONSeq をストリーミング yield
                yield from _stream_geojsonseq(out_path, file_label)


def _stream_geojsonseq(out_path: Path, label: str) -> Iterator[dict]:
    """
    GeoJSONSeq ファイルを 1 行 = 1 フィーチャとしてストリーミング yield する。

    フィーチャが 0 件の場合は ValueError を送出する。
    """
    count = 0
    with out_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                feat = json.loads(line)
            except json.JSONDecodeError:
                continue
            if feat.get("type") != "Feature":
                continue

            count += 1
            if count % _GML_PROGRESS_INTERVAL == 0:
                print(f"  [{label}] {count:,} フィーチャ処理中...", file=sys.stderr)
            yield feat

    if count == 0:
        raise ValueError(
            f"GeoJSONSeq のフィーチャが 0 件です: {label}\n"
            f"  ヒント: ZIP 内に A31a-20-* / A31b-20-* の GML ファイルが含まれているか確認してください。"
        )
    print(f"  [{label}] {count:,} フィーチャ", file=sys.stderr)


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


def _iter_zip(
    zf: zipfile.ZipFile,
    zip_label: str,
    zip_path: Optional[Path] = None,
) -> Iterator[dict]:
    """
    ZipFile オブジェクト内のエントリをスキャンし Feature を yield する。

    処理優先順: GML → GeoJSON → ネスト ZIP
    - 洪水 GML (A31a-20-*/A31b-20-*): A31 専用 iterparse パーサーで処理
      → zip_path が必要（None の場合は内部エラー）
      → ValueError は呼び出し側（normalize）に伝播して処理を止める
    - GeoJSON: Python で直接解析、失敗は WARN してスキップ
    - ネスト ZIP: 一時ファイルに書き出して再帰処理

    注意: ZIP エントリ名が CP932（Shift-JIS）の場合、ファイル名（basename）は ASCII
    なので _is_flood_gml の判定は正常に動作する。
    """
    names = sorted(
        n for n in zf.namelist()
        if not n.startswith("__MACOSX") and not n.endswith("/")
    )
    geojson_names = [n for n in names if n.lower().endswith((".geojson", ".json"))]
    gml_names     = [n for n in names if n.lower().endswith((".gml", ".xml")) and _is_flood_gml(n)]
    zip_names     = [n for n in names if n.lower().endswith(".zip")]

    if not geojson_names and not gml_names and not zip_names:
        print(
            f"[WARN] ZIP 内に対応ファイルなし（スキップ）: {zip_label}\n"
            f"  含まれるファイル: {names[:10]}{'...' if len(names) > 10 else ''}",
            file=sys.stderr,
        )
        return

    # 洪水 GML を含む場合: A31 専用 iterparse パーサーで処理
    # ZIP ごと渡すことで CP932 エンコードの ZIP エントリ名を正しく解決する
    if gml_names:
        print(
            f"  [{zip_label}] 洪水 GML {len(gml_names)} 件 → A31 GML パーサーで処理",
            file=sys.stderr,
        )
        if zip_path is None:
            raise ValueError(
                f"GML を含む ZIP の処理には zip_path が必要です: {zip_label}\n"
                f"  (内部エラー: ネスト ZIP の処理フローを確認してください)"
            )
        # ValueError は呼び出し側に伝播して処理を止める
        yield from _iter_a31_zip(zip_path, zip_label)

    # GeoJSON ファイルを Python で処理
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
        print(f"  [{label}] {len(features):,} フィーチャ (GeoJSON)", file=sys.stderr)
        yield from features

    # ネスト ZIP: 一時ファイルに書き出して再帰処理
    # （/vsizip/ のために実ファイルパスが必要）
    for name in zip_names:
        label = f"{zip_label}::{name}"
        raw = zf.read(name)
        with tempfile.TemporaryDirectory(prefix="flood_inner_") as inner_tmpdir:
            inner_zip_path = Path(inner_tmpdir) / Path(name).name
            inner_zip_path.write_bytes(raw)
            try:
                inner_zf = zipfile.ZipFile(inner_zip_path)
            except zipfile.BadZipFile as exc:
                print(f"[WARN] 内部 ZIP を開けません、スキップ: {label}: {exc}", file=sys.stderr)
                continue
            print(f"  内部 ZIP 展開: {label}", file=sys.stderr)
            with inner_zf:
                # ValueError は呼び出し側に伝播して処理を止める
                yield from _iter_zip(inner_zf, label, zip_path=inner_zip_path)


def iter_features(input_path: Path) -> Generator[dict, None, None]:
    """
    入力パス（ファイル / ZIP / ディレクトリ）から Feature dict を yield する。

    ディレクトリ: .geojson / .json / .zip を再帰スキャンして全件マージ
    ZIP        : 内部 GeoJSON・洪水 GML (A31a-20-*/A31b-20-*) を全件マージ
                 洪水 GML は ZIP ごと ogr2ogr /vsizip/ で変換
                 ネスト ZIP は一時ファイルに書き出して再帰処理
    GeoJSON    : 直接読み込み
    GML/XML    : 単体ファイルは非対応。ZIP に入れて渡すこと。

    ValueError: 入力が存在しない、対応形式でない、変換失敗の場合。
    """
    if input_path.is_dir():
        sources = sorted(
            f for f in input_path.rglob("*")
            if f.is_file()
            and f.suffix.lower() in {".geojson", ".json", ".zip"}
        )
        if not sources:
            raise ValueError(
                f"ディレクトリ内に対応ファイルが見つかりません: {input_path}\n"
                f"  対応: .geojson / .json / .zip (GML は ZIP に入れて配置)"
            )
        print(f"ディレクトリ読み込み: {len(sources)} ファイル", file=sys.stderr)
        for fp in sources:
            yield from iter_features(fp)
        return

    suffix = input_path.suffix.lower()

    if suffix == ".zip":
        print(f"読み込み中 (ZIP): {input_path}", file=sys.stderr)
        try:
            with zipfile.ZipFile(input_path, "r") as zf:
                # zip_path を渡すことで GML を含む場合に /vsizip/ 経由で処理できる
                yield from _iter_zip(zf, str(input_path), zip_path=input_path)
        except zipfile.BadZipFile as exc:
            raise ValueError(
                f"ZIP 読み込みエラー: {input_path}\n"
                f"  ファイルが破損しているか ZIP 形式ではありません: {exc}"
            ) from exc
        return

    if suffix in {".geojson", ".json"}:
        print(f"読み込み中 (GeoJSON): {input_path}", file=sys.stderr)
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
        print(f"  {len(features):,} フィーチャ (GeoJSON)", file=sys.stderr)
        yield from features
        return

    if suffix in {".gml", ".xml"}:
        # A31 GML は単体 XML では GDAL が正しく変換できない。
        # ZIP に含めてアップロードしてください。
        raise ValueError(
            f"単体 GML/XML ファイルは非対応です: {input_path}\n"
            f"  A31a/A31b データは ZIP アーカイブのまま入力してください。\n"
            f"  例: ogr2ogr は /vsizip/ 経由で ZIP 単位で処理します。"
        )

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

    total_in           = 0
    out_count          = 0
    skipped_no_geom    = 0
    skipped_bad_geom   = 0
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

                if out_count % _NORMALIZE_LOG_INTERVAL == 0:
                    print(
                        f"  ... {out_count:,} フィーチャ出力済み (入力 {total_in:,} 件処理)",
                        file=sys.stderr,
                    )

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
    print(f"完了: {output_path}", file=sys.stderr)
    print(f"  入力: {total_in:,}  出力: {out_count:,}  スキップ: {skipped_no_geom + skipped_bad_geom}", file=sys.stderr)
    print(f"  ファイルサイズ: {size_mb:.1f} MB", file=sys.stderr)
    print("  ランク別件数:", file=sys.stderr)
    for r in sorted(rank_counts):
        rlabel = RANK_TABLE.get(r, ("?",))[0]
        print(f"    rank {r} ({rlabel}): {rank_counts[r]:,}件", file=sys.stderr)

    return 0


# ── エントリポイント ──────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="洪水浸水想定区域データ正規化 (A31a / A31b GML, GeoJSON) — ogr2ogr 使用",
        epilog=(
            "複数 ZIP をひとつにまとめる場合:\n"
            "  zip bundle.zip 荒川.zip 江戸川.zip 多摩川.zip\n"
            "  python normalize_river_flood.py --input bundle.zip --output out.geojson\n\n"
            "依存: ogr2ogr (GDAL)\n"
            "  Docker: apt-get install -y gdal-bin\n"
            "  Mac:    brew install gdal"
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
