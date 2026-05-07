#!/usr/bin/env python3
"""
generate_municipality_coords.py
全国市区町村の代表座標辞書を生成して frontend/data/municipality_coords.json に出力する。

データソース: geolonia/japanese-addresses (GitHub raw CSV)
列: 都道府県コード, 都道府県名, ..., 市区町村名, ..., 緯度, 経度
"""
import csv
import io
import json
import statistics
import urllib.request
from pathlib import Path

OUTPUT = Path(__file__).parent.parent / "frontend" / "data" / "municipality_coords.json"
URL = "https://raw.githubusercontent.com/geolonia/japanese-addresses/master/data/latest.csv"

PREF_COL  = 1   # 都道府県名
CITY_COL  = 5   # 市区町村名
LAT_COL   = 12  # 緯度
LON_COL   = 13  # 経度


def fetch() -> str:
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "OnHighGround2/1.0 (+https://github.com/brokendish/OnHighGround2)"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def build(csv_text: str) -> dict:
    reader = csv.reader(io.StringIO(csv_text))
    next(reader)  # header

    # 中心座標計算用に (pref|city) → [lat, lon] のリストを収集
    buckets: dict[str, tuple[list[float], list[float]]] = {}
    for row in reader:
        if len(row) <= LON_COL:
            continue
        pref = row[PREF_COL].strip()
        city = row[CITY_COL].strip()
        lat_s = row[LAT_COL].strip()
        lon_s = row[LON_COL].strip()
        if not pref or not city or not lat_s or not lon_s:
            continue
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except ValueError:
            continue
        key = f"{pref}|{city}"
        if key not in buckets:
            buckets[key] = ([], [])
        buckets[key][0].append(lat)
        buckets[key][1].append(lon)

    result = {}
    for key, (lats, lons) in buckets.items():
        result[key] = {
            "lat": round(statistics.mean(lats), 6),
            "lon": round(statistics.mean(lons), 6),
        }
    return result


def main() -> None:
    print("geolonia/japanese-addresses CSV 取得中...")
    try:
        csv_text = fetch()
        print(f"  取得完了: {len(csv_text):,} bytes")
    except Exception as exc:
        print(f"  取得失敗: {exc}")
        return

    coords = build(csv_text)
    print(f"  市区町村数: {len(coords):,} 件")

    # 確認: 政令市区が含まれているか
    checks = [
        "北海道|札幌市中央区",
        "宮城県|仙台市青葉区",
        "東京都|千代田区",
        "東京都|八王子市",
        "神奈川県|横浜市鶴見区",
        "神奈川県|横須賀市",
        "大阪府|大阪市中央区",
        "大阪府|堺市中区",
        "愛知県|名古屋市中区",
        "福岡県|福岡市博多区",
    ]
    print("\n  サンプル確認:")
    for k in checks:
        v = coords.get(k)
        print(f"    {k}: {v}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    print(f"\n出力完了: {OUTPUT}")


if __name__ == "__main__":
    main()
