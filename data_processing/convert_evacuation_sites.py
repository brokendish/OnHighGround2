"""
自治体オープンデータ（CSV / GeoJSON）を
OnHighGround2用の避難施設CSVへ変換するスクリプト。

出力形式（ヘッダー固定）:
name,site_type,designation,lat,lon
"""
import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

OUTPUT_FIELDS = ["name", "site_type", "designation", "lat", "lon"]


def normalize_key(key: str) -> str:
    return "".join(str(key).strip().lower().split())


def normalize_designation(raw_value: str) -> Optional[str]:
    value = "".join(str(raw_value or "").strip().split())
    if not value:
        return None

    lower_value = value.lower()
    if value in {"緊急避難場所", "指定緊急避難場所"} or lower_value in {"emergencyevacuation", "emergencyevacuationsite"}:
        return "緊急避難場所"
    if value in {"指定避難所"} or lower_value in {"designatedshelter"}:
        return "指定避難所"

    return None


def pick_value(row: Dict, candidates: Iterable[str]) -> Optional[str]:
    normalized = {normalize_key(k): v for k, v in row.items()}
    for key in candidates:
        val = normalized.get(normalize_key(key))
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return None


def parse_lat_lon(row: Dict) -> Optional[Tuple[float, float]]:
    lat_raw = pick_value(row, ["lat", "latitude", "緯度", "y", "北緯"])
    lon_raw = pick_value(row, ["lon", "lng", "long", "longitude", "経度", "x", "東経"])
    if lat_raw is None or lon_raw is None:
        return None

    try:
        return float(lat_raw), float(lon_raw)
    except ValueError:
        return None


def normalize_site_record(raw: Dict, fallback_name_prefix: str, index: int) -> Optional[Dict]:
    lat_lon = parse_lat_lon(raw)
    if lat_lon is None:
        return None
    lat, lon = lat_lon

    designation_raw = pick_value(raw, ["designation", "指定区分", "指定", "site_designation", "避難種別", "種別"])
    designation = normalize_designation(designation_raw)
    if designation is None:
        return None

    name = pick_value(raw, ["name", "名称", "施設名", "避難所名"]) or f"{fallback_name_prefix}_{index}"
    site_type = pick_value(raw, ["site_type", "区分", "施設区分", "カテゴリ", "category"]) or "未分類"

    return {
        "name": name,
        "site_type": site_type,
        "designation": designation,
        "lat": f"{lat:.7f}",
        "lon": f"{lon:.7f}",
    }


def load_csv_rows(path: Path) -> List[Dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_geojson_rows(path: Path) -> List[Dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    rows: List[Dict] = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}

        if geometry.get("type") != "Point":
            continue

        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue

        row = dict(properties)
        row["lat"] = coords[1]
        row["lon"] = coords[0]
        rows.append(row)

    return rows


def convert(input_path: Path, output_path: Path) -> Tuple[int, int]:
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        raw_rows = load_csv_rows(input_path)
    elif suffix in {".json", ".geojson"}:
        raw_rows = load_geojson_rows(input_path)
    else:
        raise ValueError("入力形式は .csv / .json / .geojson に対応しています")

    converted: List[Dict] = []
    skipped = 0
    for i, raw in enumerate(raw_rows, 1):
        row = normalize_site_record(raw, "施設", i)
        if row is None:
            skipped += 1
            continue
        converted.append(row)

    # name+座標で重複排除
    unique_rows: List[Dict] = []
    seen = set()
    for row in converted:
        key = (row["name"], row["lat"], row["lon"], row["designation"])
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(unique_rows)

    return len(unique_rows), skipped


def main():
    parser = argparse.ArgumentParser(
        description="自治体オープンデータをOnHighGround2用避難施設CSVへ変換"
    )
    parser.add_argument("input", help="入力ファイル（CSV/GeoJSON）")
    parser.add_argument("output", help="出力CSVファイル")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")

    converted, skipped = convert(input_path, output_path)
    print(f"変換完了: {output_path}")
    print(f"出力件数: {converted}")
    print(f"スキップ件数: {skipped}")


if __name__ == "__main__":
    main()
