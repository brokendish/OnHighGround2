#!/usr/bin/env python3
"""
normalize_tsunami.py — 津波浸水想定データを GeoJSON へ正規化する。

対応入力:
  - .geojson / .json
  - .gml / .xml
  - .zip (内部の .gml/.xml または .geojson/.json を自動検出)

出力プロパティ:
  - depth
  - depth_text
  - hazard_type
  - dataset_id
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from io import TextIOWrapper
from pathlib import Path
from typing import Iterable, Optional


DEPTH_TEXT_KEYS = (
    "A40_003",
    "a40_003",
    "depth_text",
    "depth_label",
    "depth",
    "rank",
    "level",
)

DEPTH_TAG_HINTS = {
    "rank",
    "level",
    "depth",
    "waterdepth",
    "inundationdepth",
    "tsunamidepth",
    "tsunamihight",
    "cassificationofwaterdepth",
    "description",
    "classname",
    "category",
}


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _href_target(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value[1:] if value.startswith("#") else value


def _elem_id(elem: ET.Element) -> Optional[str]:
    for attr_name, attr_val in elem.attrib.items():
        if _local(attr_name) == "id":
            return attr_val
    return None


def _feature_path(elem: ET.Element, child_tag: Optional[str] = None) -> str:
    feature_name = _local(elem.tag)
    feature_id = _elem_id(elem)
    path = f"/Dataset/{feature_name}"
    if feature_id:
        path += f"[@gml:id='{feature_id}']"
    if child_tag:
        path += f"/{child_tag}"
    return path


def _extract_depth_value(raw: object) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    compact = text.replace(" ", "")
    if "0.5m未満" in compact or "0.3m未満" in compact:
        return 0.5
    if "0.5m以上" in compact and "1.0m未満" in compact:
        return 0.75
    if "1m以上" in compact and "3m未満" in compact:
        return 2.0
    if "3m以上" in compact and "5m未満" in compact:
        return 4.0
    if "5m以上" in compact and "10m未満" in compact:
        return 5.0
    if "10m以上" in compact and "20m未満" in compact:
        return 10.0
    if "20m以上" in compact:
        return 20.0
    if "5m以上" in compact:
        return 5.0

    numbers = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", compact)]
    if not numbers:
        return None
    if len(numbers) >= 2:
        return sum(numbers[:2]) / 2.0
    return numbers[0]


def _normalize_feature(feature: dict, dataset_id: str) -> dict:
    geometry = feature.get("geometry") or {}
    geom_type = geometry.get("type")
    if geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"unsupported geometry type: {geom_type}")

    props = dict(feature.get("properties") or {})
    depth_text = ""
    for key in DEPTH_TEXT_KEYS:
        if props.get(key) not in (None, ""):
            depth_text = str(props[key]).strip()
            break

    depth = _extract_depth_value(depth_text)
    if depth is None:
        depth = _extract_depth_value(props.get("depth"))

    props["depth"] = depth
    props["depth_text"] = depth_text
    props["hazard_type"] = "tsunami"
    props["dataset_id"] = dataset_id

    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": props,
    }


def _load_geojson_bytes(content: bytes, dataset_id: str, entry_name: str) -> list[dict]:
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{entry_name}: GeoJSON を読み込めませんでした ({exc})") from exc

    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{entry_name}: GeoJSON root type must be FeatureCollection")

    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"{entry_name}: feature が 0 件です")

    normalized = []
    for index, feature in enumerate(features):
        try:
            normalized.append(_normalize_feature(feature, dataset_id))
        except ValueError as exc:
            raise ValueError(f"{entry_name}: feature {index}: {exc}") from exc
    return normalized


def _iter_geojson_features(stream, entry_name: str):
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    index = 0
    eof = False
    need_more = True

    while True:
        if not eof and (need_more or not started or index >= len(buffer)):
            chunk = stream.read(1024 * 1024)
            if chunk == "":
                eof = True
            else:
                buffer += chunk
            need_more = False

        if not started:
            match = re.search(r'"features"\s*:\s*\[', buffer)
            if not match:
                if eof:
                    raise ValueError(f"{entry_name}: GeoJSON features 配列を検出できませんでした")
                continue
            index = match.end()
            started = True

        while True:
            while index < len(buffer) and buffer[index] in " \r\n\t,":
                index += 1

            if index < len(buffer) and buffer[index] == "]":
                return

            try:
                value, next_index = decoder.raw_decode(buffer, index)
            except json.JSONDecodeError as exc:
                if eof:
                    raise ValueError(f"{entry_name}: GeoJSON feature の解析に失敗しました ({exc})") from exc
                if index > 0:
                    buffer = buffer[index:]
                    index = 0
                need_more = True
                break

            yield value
            index = next_index

            if index > 1024 * 1024:
                buffer = buffer[index:]
                index = 0


def _stream_geojson_to_output(stream, output_path: Path, dataset_id: str, entry_name: str) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with output_path.open("w", encoding="utf-8") as out:
        out.write('{"type":"FeatureCollection","features":[')
        for feature in _iter_geojson_features(stream, entry_name):
            try:
                normalized = _normalize_feature(feature, dataset_id)
            except ValueError as exc:
                raise ValueError(f"{entry_name}: feature {count}: {exc}") from exc

            if count:
                out.write(",")
            json.dump(normalized, out, ensure_ascii=False, separators=(",", ":"))
            count += 1

        out.write("]}\n")

    if count == 0:
        raise ValueError(f"{entry_name}: feature が 0 件です")
    return count


def _parse_pos_list(text: str) -> list[tuple[float, float]]:
    vals = text.split()
    coords: list[tuple[float, float]] = []
    for i in range(0, len(vals) - 1, 2):
        lat, lon = float(vals[i]), float(vals[i + 1])
        coords.append((lon, lat))
    return coords


def _collect_curves(root: ET.Element) -> dict[str, list[tuple[float, float]]]:
    curves: dict[str, list[tuple[float, float]]] = {}
    for elem in root.iter():
        if _local(elem.tag) not in ("Curve", "LineString", "LinearRing"):
            continue
        geom_id = _elem_id(elem)
        if not geom_id:
            continue

        coords: list[tuple[float, float]] = []
        for child in elem.iter():
            if _local(child.tag) == "posList" and child.text:
                coords = _parse_pos_list(child.text.strip())
                break
        if coords:
            curves[geom_id] = coords

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
                base_ref = _href_target(next((v for k, v in child.attrib.items() if _local(k) == "href"), None))
                break
        if not base_ref or base_ref not in curves:
            continue
        coords = list(curves[base_ref])
        if orientation == "-":
            coords = list(reversed(coords))
        curves[geom_id] = coords

    return curves


def _collect_surfaces(root: ET.Element, curves: dict[str, list[tuple[float, float]]]) -> dict[str, dict]:
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
                href = _href_target(next((v for k, v in child.attrib.items() if _local(k) == "href"), None))
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
        geometry = {
            "type": geom_type,
            "coordinates": polygons if geom_type == "MultiPolygon" else polygons[0],
        }
        surfaces[geom_id] = geometry
    return surfaces


def _find_depth_text(elem: ET.Element) -> str:
    for child in elem.iter():
        local = _local(child.tag).lower()
        text = (child.text or "").strip()
        if not text:
            continue
        if local in DEPTH_TAG_HINTS:
            return text
        if "m" in text or "未満" in text or "以上" in text:
            return text
    return ""


def _find_surface_ref(elem: ET.Element) -> Optional[str]:
    for child in elem.iter():
        local = _local(child.tag).lower()
        if local not in ("bounds", "shape", "surface", "area", "geometry"):
            continue
        href = _href_target(next((v for k, v in child.attrib.items() if _local(k) == "href"), None))
        if href:
            return href
    return None


def _load_gml_bytes(content: bytes, dataset_id: str, entry_name: str) -> list[dict]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"{entry_name}: GML/XML パースエラー ({exc})") from exc

    curves = _collect_curves(root)
    surfaces = _collect_surfaces(root, curves)

    features: list[dict] = []
    errors: list[str] = []
    feature_tag_names = {"ExpectedTsunamiInundatedArea"}

    for elem in root.iter():
        if _local(elem.tag) not in feature_tag_names:
            continue

        ref_id = _find_surface_ref(elem)
        if not ref_id:
            errors.append(f"{_feature_path(elem, 'bounds')}: xlink:href が見つかりません")
            continue

        geometry = surfaces.get(ref_id)
        if not geometry:
            errors.append(
                f"{_feature_path(elem, 'bounds')}: surface ref '{ref_id}' を解決できません "
                f"(curves={len(curves)}, surfaces={len(surfaces)})"
            )
            continue

        depth_text = _find_depth_text(elem)
        if not depth_text:
            errors.append(f"{_feature_path(elem, 'cassificationOfWaterDepth')}: depth text が見つかりません")
            continue

        try:
            feature = _normalize_feature(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "depth_text": depth_text,
                        "A40_003": depth_text,
                    },
                },
                dataset_id,
            )
        except ValueError as exc:
            errors.append(f"{_feature_path(elem)}: {exc}")
            continue

        features.append(feature)

    if not features:
        error_preview = "\n".join(f"  - {err}" for err in errors[:10])
        raise ValueError(
            f"{entry_name}: tsunami feature を抽出できませんでした "
            f"(A40 GML / Polygon / MultiPolygon を想定)\n{error_preview}"
        )

    if errors:
        print(
            f"[gml] partial skips in {entry_name}: {len(errors)} issues\n"
            + "\n".join(f"  - {err}" for err in errors[:10]),
            file=sys.stderr,
        )
    return features


def _load_zip(path: Path, dataset_id: str) -> list[dict]:
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
    except zipfile.BadZipFile as exc:
        raise ValueError(f"ZIP を開けませんでした: {path.name} ({exc})") from exc

    gml_entries = [n for n in names if n.lower().endswith((".gml", ".xml"))]
    json_entries = [n for n in names if n.lower().endswith((".geojson", ".json"))]

    if not gml_entries and not json_entries:
        raise ValueError(
            f"ZIP 内にサポートされるファイルが見つかりません: {path.name}\n"
            f"含まれるファイル: {names[:15]}{'...' if len(names) > 15 else ''}"
        )

    with zipfile.ZipFile(path) as zf:
        for entry in gml_entries:
            print(f"[gml] processing: {entry}", file=sys.stderr)
            content = zf.read(entry)
            try:
                features = _load_gml_bytes(content, dataset_id, entry)
            except ValueError as exc:
                print(f"[gml] skip: {exc}", file=sys.stderr)
                continue
            print(f"[gml] {entry}: {len(features)} features", file=sys.stderr)
            return features

        for entry in json_entries:
            print(f"[json] processing: {entry}", file=sys.stderr)
            content = zf.read(entry)
            features = _load_geojson_bytes(content, dataset_id, entry)
            print(f"[json] {entry}: {len(features)} features", file=sys.stderr)
            return features

    raise ValueError(
        f"ZIP 内の GML/GeoJSON から tsunami feature を取得できませんでした: {path.name}"
    )


def stream_input_to_output(input_path: Path, output_path: Path, dataset_id: str) -> Optional[int]:
    suffix = input_path.suffix.lower()
    if suffix in (".geojson", ".json"):
        with input_path.open("r", encoding="utf-8") as stream:
            return _stream_geojson_to_output(stream, output_path, dataset_id, input_path.name)
    if suffix != ".zip":
        return None

    try:
        zf = zipfile.ZipFile(input_path)
    except zipfile.BadZipFile:
        return None

    with zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        json_entries = [n for n in names if n.lower().endswith((".geojson", ".json"))]
        for entry in json_entries:
            print(f"[json] processing: {entry}", file=sys.stderr)
            with zf.open(entry) as raw:
                stream = TextIOWrapper(raw, encoding="utf-8")
                count = _stream_geojson_to_output(stream, output_path, dataset_id, entry)
            print(f"[json] {entry}: {count} features", file=sys.stderr)
            return count
    return None


def load_input(input_path: Path, dataset_id: str) -> list[dict]:
    suffix = input_path.suffix.lower()
    if suffix in (".geojson", ".json"):
        return _load_geojson_bytes(input_path.read_bytes(), dataset_id, input_path.name)
    if suffix in (".gml", ".xml"):
        return _load_gml_bytes(input_path.read_bytes(), dataset_id, input_path.name)
    if suffix == ".zip":
        return _load_zip(input_path, dataset_id)
    raise ValueError(f"未対応の入力形式です: {input_path.suffix}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize tsunami data into GeoJSON.")
    parser.add_argument("--input", required=True, help="Input (.geojson/.json/.gml/.xml/.zip)")
    parser.add_argument("--output", required=True, help="Output GeoJSON path")
    parser.add_argument("--dataset-id", required=True, help="Dataset ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"[ERROR] input not found: {input_path}", file=sys.stderr)
        return 1

    print(f"Input:   {input_path} ({input_path.suffix})")
    print(f"Dataset: {args.dataset_id}")

    try:
        streamed_count = stream_input_to_output(input_path, output_path, args.dataset_id)
        if streamed_count is not None:
            print(f"Output:  {output_path} ({streamed_count} features)")
            return 0

        features = load_input(input_path, args.dataset_id)
    except ValueError as exc:
        print(f"[ERROR] normalize failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        import traceback
        print(f"[ERROR] unexpected failure: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    if not features:
        print("[ERROR] feature が 0 件です", file=sys.stderr)
        return 1

    output = {
        "type": "FeatureCollection",
        "features": features,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Output:  {output_path} ({len(features)} features)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
