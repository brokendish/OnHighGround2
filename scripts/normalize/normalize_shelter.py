#!/usr/bin/env python3
"""
normalize_shelter.py — 指定緊急避難場所データ正規化スクリプト

サポートする入力フォーマット:
  geojson / json  : GeoJSON FeatureCollection
  gml / xml       : 国土数値情報 KSJ P20 GML
  zip             : 上記いずれかを含む ZIP（国土数値情報 P20 配布 ZIP 含む）

使用方法:
  python3 normalize_shelter.py --input <input> --output <output.geojson>
  python3 normalize_shelter.py --input <P20-12_14_GML.zip> --output <out.geojson> \\
      --dataset-id KANAGAWA-SHELTER-001
"""
import argparse
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# ── 地域マッピング ─────────────────────────────────────────────────────────────

_REGION_CODE_MAP: dict[str, str] = {
    "tokyo":    "13",
    "kanagawa": "14",
    "saitama":  "11",
    "chiba":    "12",
    "osaka":    "27",
    "aichi":    "23",
}

_DATASET_PREFIX_MAP: dict[str, str] = {
    "TOKYO":    "tokyo",
    "KANAGAWA": "kanagawa",
    "SAITAMA":  "saitama",
    "CHIBA":    "chiba",
    "OSAKA":    "osaka",
    "AICHI":    "aichi",
}


def _infer_region(dataset_id: str) -> str:
    prefix = dataset_id.split("-")[0].upper()
    return _DATASET_PREFIX_MAP.get(prefix, "unknown")


def _infer_region_from_path(path: Path) -> str:
    parts = str(path).lower().split("/")
    for p in parts:
        if p in _REGION_CODE_MAP:
            return p
    return "unknown"


# ── XML ユーティリティ ─────────────────────────────────────────────────────────

def _local(tag: str) -> str:
    """namespace を除いたローカル名を返す: {ns}local → local"""
    return tag.split("}")[-1] if "}" in tag else tag


# ── GML (国土数値情報 KSJ P20) パーサー ───────────────────────────────────────

# 指定避難所ファイルに特有の列名（これらがあれば designation を '指定避難所' と推定する）
_EVAC_SHELTER_INDICATOR_KEYS: frozenset[str] = frozenset({
    "受入対象者",
    "指定緊急避難場所との住所同一",
})


def _infer_designation_for_features(features: list[dict]) -> str:
    """全フィーチャーの列名からファイル種別を推定する。
    指定避難所固有の列があれば '指定避難所'、それ以外は '指定緊急避難場所' を返す。"""
    all_keys: set[str] = set()
    for feat in features:
        all_keys.update((feat.get("properties") or {}).keys())
    if _EVAC_SHELTER_INDICATOR_KEYS & all_keys:
        return "指定避難所"
    for feat in features:
        shisetu = (feat.get("properties") or {}).get("施設種別", "")
        if shisetu in ("避難所", "指定避難所"):
            return "指定避難所"
    return "指定緊急避難場所"


# KSJ P20 ハザード要素名 → 共通スキーマの日本語列名
# P20-12 (2012版) の hazardClassification サブ要素
_KSJ_HAZARD_MAP: dict[str, str] = {
    "earthquakeHazard":  "地震",
    "tsunamiHazard":     "津波",
    # windAndFloodDamage は洪水・高潮・崖崩れの合算フィールド。
    # 2012版では個別フラグがないため 洪水 に代表させる。
    "windAndFloodDamage": "洪水",
    "volcanicHazard":    "火山現象",
}

# GeoJSON 入力時の日本語ハザード列名セット（setdefault 補完用）
_ALL_HAZARD_JP: tuple[str, ...] = (
    "洪水", "崖崩れ、土石流及び地滑り", "高潮",
    "地震", "津波", "大規模な火事", "内水氾濫", "火山現象",
)


def _parse_gml_bytes(content: bytes, source_dataset: str, region_code: str) -> list[dict]:
    """
    GML/XML バイト列から GeoJSON Feature リストを生成する。

    国土数値情報 P20 形式を前提とする:
      - ksj:EvacuationFacilities が各施設フィーチャー
      - gml:Point/{gml:pos} で座標（lat lon 順 → GeoJSON では lon lat に変換）
      - ksj:position の xlink:href で gml:Point を参照
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"GML/XML パースエラー: {exc}") from exc

    # ── gml:id → (lat, lon) の座標マップを構築 ────────────────────────────
    # P20 XML では <gml:Point gml:id="ptXXXXXX"><gml:pos>lat lon</gml:pos>
    point_map: dict[str, tuple[float, float]] = {}
    for elem in root.iter():
        if _local(elem.tag) != "Point":
            continue
        # gml:id 属性: {ns}id 形式 or プレーン "id"
        gml_id = None
        for attr_name, attr_val in elem.attrib.items():
            if _local(attr_name) == "id":
                gml_id = attr_val
                break
        if gml_id is None:
            continue
        pos_elem = next(
            (c for c in elem if _local(c.tag) == "pos"),
            None,
        )
        if pos_elem is None or not pos_elem.text:
            continue
        parts = pos_elem.text.strip().split()
        if len(parts) < 2:
            continue
        try:
            point_map[gml_id] = (float(parts[0]), float(parts[1]))  # lat, lon
        except ValueError:
            continue

    # ── EvacuationFacilities フィーチャーを変換 ────────────────────────────
    features: list[dict] = []
    for elem in root.iter():
        if _local(elem.tag) != "EvacuationFacilities":
            continue

        # 位置: ksj:position[xlink:href] → gml:Point 参照
        lonlat: Optional[tuple[float, float]] = None
        pos_elem = next(
            (c for c in elem if _local(c.tag) == "position"),
            None,
        )
        if pos_elem is not None:
            href = next(
                (v for k, v in pos_elem.attrib.items() if _local(k) == "href"),
                None,
            )
            if href:
                ref_id = href.lstrip("#")
                entry = point_map.get(ref_id)
                if entry:
                    lat, lon = entry
                    lonlat = (lon, lat)  # GeoJSON は (lon, lat)

        if lonlat is None:
            continue

        # 子要素からプロパティを収集（local name → text）
        raw: dict[str, str] = {}
        for child in elem:
            raw[_local(child.tag)] = (child.text or "").strip()

        # ハザードフラグは hazardClassification の孫要素
        hazard_vals: dict[str, str] = {}
        haz_cls = next(
            (c for c in elem if _local(c.tag) == "hazardClassification"),
            None,
        )
        if haz_cls is not None:
            cls = next(
                (c for c in haz_cls if _local(c.tag) == "Classification"),
                None,
            )
            if cls is not None:
                for child in cls:
                    hazard_vals[_local(child.tag)] = (child.text or "").strip()

        # 共通スキーマへ変換
        name = raw.get("name", "名称未設定") or "名称未設定"
        address = raw.get("address", "")

        props: dict = {
            "施設・場所名": name,
            "住所": address,
            "designation": "指定緊急避難場所",
            "source_dataset": source_dataset,
            "normalized_region_code": region_code,
        }

        # KSJ ハザードフラグ → 日本語列名（"1"/"0"）
        for ksj_key, jp_col in _KSJ_HAZARD_MAP.items():
            val = hazard_vals.get(ksj_key, "false")
            props[jp_col] = "1" if val.lower() == "true" else "0"

        # 未マップの標準列はデフォルト "0"
        for jp_col in _ALL_HAZARD_JP:
            props.setdefault(jp_col, "0")

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": list(lonlat)},
            "properties": props,
        })

    return features


# ── フォーマット別ローダー ─────────────────────────────────────────────────────

def _load_geojson(path: Path, source_dataset: str, region_code: str) -> list[dict]:
    """GeoJSON/JSON FeatureCollection を読み込む（既存フロー互換）。"""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if data.get("type") != "FeatureCollection":
        raise ValueError(f"Input is not a GeoJSON FeatureCollection: {path.name}")

    raw_features = data.get("features", [])
    # designation が全件未設定の場合は列名から一括推定する
    inferred_designation = _infer_designation_for_features(raw_features)

    features: list[dict] = []
    for feature in raw_features:
        props = dict(feature.get("properties") or {})
        props.setdefault("source_dataset", source_dataset)
        props.setdefault("normalized_region_code", region_code)
        # 個別 feature に designation がない場合は推定値を使う
        if not props.get("designation"):
            props["designation"] = inferred_designation
        features.append({
            "type": "Feature",
            "geometry": feature.get("geometry"),
            "properties": props,
        })
    return features


def _load_gml_file(path: Path, source_dataset: str, region_code: str) -> list[dict]:
    """GML/XML ファイルを読み込む。"""
    return _parse_gml_bytes(path.read_bytes(), source_dataset, region_code)


def _load_zip(path: Path, source_dataset: str, region_code: str) -> list[dict]:
    """
    ZIP アーカイブを開いて中身のフォーマットを自動判定し読み込む。

    優先順位:
      1. .gml / .xml ファイル → GML パーサーで処理
         （KS-META- で始まるメタデータファイルは 0 フィーチャーを返すだけ）
      2. .geojson / .json ファイル → GeoJSON パーサーで処理
      3. いずれも存在しない → 明確なエラー
    """
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise ValueError(f"ZIP 展開エラー ({path.name}): {exc}") from exc

    gml_names  = [n for n in names if n.lower().endswith((".gml", ".xml"))]
    json_names = [n for n in names if n.lower().endswith((".geojson", ".json"))]

    if not gml_names and not json_names:
        visible = [n for n in names if not n.endswith("/")]
        raise ValueError(
            f"ZIP 内にサポートされるファイルが見つかりません: {path.name}\n"
            f"含まれるファイル: {visible[:15]}{'...' if len(visible) > 15 else ''}\n"
            f"サポートされる形式: .gml, .xml, .geojson, .json"
        )

    features: list[dict] = []
    gml_parsed: list[str] = []    # feature を 1 件以上取得できた GML エントリ名
    gml_skipped: list[str] = []   # パース不能だったエントリ名

    if gml_names:
        with zipfile.ZipFile(path) as zf:
            for entry in gml_names:
                print(f"  [gml] processing: {entry}", file=sys.stderr)
                content = zf.read(entry)
                try:
                    batch = _parse_gml_bytes(content, source_dataset, region_code)
                    if batch:
                        features.extend(batch)
                        gml_parsed.append(entry)
                        print(f"  [gml] {entry}: {len(batch)} features", file=sys.stderr)
                    else:
                        # XML として読めたが shelter feature が 0 件（非データ XML or 非 P20 形式）
                        gml_skipped.append(entry)
                        print(f"  [skip] {entry}: shelter feature なし（非 P20 XML の可能性）",
                              file=sys.stderr)
                except ValueError as exc:
                    # KS-META-*.xml など Shift-JIS エンコードのメタデータファイルは
                    # ElementTree が "multi-byte encodings are not supported" を返す。
                    gml_skipped.append(entry)
                    print(f"  [skip] {entry}: パース対象外 ({exc})", file=sys.stderr)

        # XML/GML は見つかったが feature が 1 件も得られなかった場合は明確なエラー
        if gml_names and not features and not json_names:
            raise ValueError(
                f"ZIP 内の XML/GML から shelter feature を取得できませんでした: {path.name}\n"
                f"処理対象: {gml_names}\n"
                f"想定フォーマット: 国土数値情報 P20 (ksj:EvacuationFacilities)\n"
                f"ZIP 内が非 P20 XML の場合は、対応する GML または GeoJSON を用意してください。"
            )

    if not features and json_names:
        # GML が空だった場合のみ GeoJSON にフォールバック
        with zipfile.ZipFile(path) as zf:
            for entry in json_names:
                print(f"  [json] processing: {entry}", file=sys.stderr)
                content = zf.read(entry)
                try:
                    data = json.loads(content.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ValueError(
                        f"ZIP 内の JSON エントリを読み込めませんでした: {entry}\n"
                        f"原因: {exc}"
                    ) from exc
                if data.get("type") == "FeatureCollection":
                    raw_feats = data.get("features", [])
                    inferred_designation = _infer_designation_for_features(raw_feats)
                    for feat in raw_feats:
                        props = dict(feat.get("properties") or {})
                        props.setdefault("source_dataset", source_dataset)
                        props.setdefault("normalized_region_code", region_code)
                        if not props.get("designation"):
                            props["designation"] = inferred_designation
                        features.append({
                            "type": "Feature",
                            "geometry": feat.get("geometry"),
                            "properties": props,
                        })
                    print(f"  [json] {entry}: {len(features)} features", file=sys.stderr)
                else:
                    raise ValueError(
                        f"ZIP 内の JSON エントリが GeoJSON FeatureCollection ではありません: {entry}\n"
                        f"(type={data.get('type')!r})"
                    )

    return features


def load_input(input_path: Path, source_dataset: str, region_code: str) -> list[dict]:
    """
    入力フォーマットを自動判定して GeoJSON Feature リストを返す。

    対応フォーマット: geojson, json, gml, xml, zip
    """
    suffix = input_path.suffix.lower()

    if suffix in (".geojson", ".json"):
        return _load_geojson(input_path, source_dataset, region_code)
    elif suffix in (".gml", ".xml"):
        return _load_gml_file(input_path, source_dataset, region_code)
    elif suffix == ".zip":
        return _load_zip(input_path, source_dataset, region_code)
    else:
        raise ValueError(
            f"未対応の入力フォーマット: '{suffix}' ({input_path.name})\n"
            f"サポートされる形式: .geojson, .json, .gml, .xml, .zip"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize shelter data (GeoJSON / GML / ZIP) for any region."
    )
    parser.add_argument("--input",       required=True, help="Input file (.geojson/.json/.gml/.xml/.zip)")
    parser.add_argument("--output",      required=True, help="Output normalized GeoJSON path")
    parser.add_argument("--dataset-id",  default=None,  help="Dataset ID (e.g. KANAGAWA-SHELTER-001)")
    parser.add_argument("--designation", default=None,
                        help='designation 値を全フィーチャーに強制セット（例: "指定緊急避難場所", "指定避難所"）')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path  = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"[ERROR] 入力ファイルが見つかりません: {input_path}", file=sys.stderr)
        return 1

    # dataset_id と region の決定
    dataset_id = args.dataset_id
    if dataset_id:
        region = _infer_region(dataset_id)
    else:
        region = _infer_region_from_path(input_path)
        stem = output_path.stem.upper().replace("_NORMALIZED", "").replace("-", "_")
        for prefix in _DATASET_PREFIX_MAP:
            if stem.startswith(prefix):
                region = _DATASET_PREFIX_MAP[prefix]
                break

    region_code    = _REGION_CODE_MAP.get(region, "00")
    source_dataset = dataset_id or f"{region.upper()}-SHELTER-001"

    print(f"Input:   {input_path} ({input_path.suffix})")
    print(f"Dataset: {source_dataset}  region={region}  region_code={region_code}")
    if args.designation:
        print(f"Designation: {args.designation} (forced)")

    try:
        features = load_input(input_path, source_dataset, region_code)
    except ValueError as exc:
        print(f"[ERROR] 読み込み失敗: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] 予期しないエラー: {exc}", file=sys.stderr)
        return 1

    if not features:
        print("[ERROR] フィーチャーが 0 件です。入力フォーマットまたはパスを確認してください。",
              file=sys.stderr)
        return 1

    # --designation が指定された場合は全フィーチャーに強制上書き
    if args.designation:
        for feat in features:
            props = feat.get("properties")
            if props is not None:
                props["designation"] = args.designation

    normalized = {
        "type": "FeatureCollection",
        "name": f"{region}_shelter_normalized",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Output:  {output_path}  ({len(features)} features)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
