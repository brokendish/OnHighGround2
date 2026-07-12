#!/usr/bin/env python3
"""
download_municipality_boundaries_nationwide.py

全国市区町村境界データ (Phase 8-B.1) の raw データを取得する。

データソース: スマートニュース メディア研究所 japan-topography リポジトリ
  https://github.com/smartnews-smri/japan-topography
  (data/municipality/geojson/s0010/ — 境界線1%簡略化・都道府県別分割済み GeoJSON)

加工元は国土交通省 国土数値情報「行政区域」データ (https://nlftp.mlit.go.jp/ksj/)。
同リポジトリの README によれば、スマートニュースへのクレジット表記は不要だが、
国土数値情報側が指定するクレジットは必要 (商用・非商用問わず無償利用可)。
このプロジェクトでは frontend/js/live-stream/live-stream-municipality-boundary.js が
地図の attribution に「国土交通省 国土数値情報（行政区域データ）を加工して作成」を追加する。

47都道府県分の GeoJSON を data_lake/raw/nationwide/boundary/ にキャッシュする
(既存ファイルはスキップするため、再実行時は差分のみ・オフラインでも scripts/derive/ 側は動く)。

Usage:
  venv/bin/python scripts/download/download_municipality_boundaries_nationwide.py
  venv/bin/python scripts/download/download_municipality_boundaries_nationwide.py --force
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "data_lake/raw/nationwide/boundary"
BASE_URL = "https://raw.githubusercontent.com/smartnews-smri/japan-topography/main/data/municipality/geojson/s0010"

PREF_CODES = [f"{i:02d}" for i in range(1, 48)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="既存ファイルも再取得する")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok, skipped, failed = 0, 0, []
    for code in PREF_CODES:
        fname = f"N03-21_{code}_210101.json"
        dest = OUT_DIR / fname
        if dest.exists() and not args.force:
            skipped += 1
            continue
        url = f"{BASE_URL}/{fname}"
        try:
            with urllib.request.urlopen(url, timeout=20) as res:
                data = res.read()
            dest.write_bytes(data)
            ok += 1
            print(f"[ok] {fname} ({len(data) / 1024:.0f} KB)")
        except Exception as e:
            failed.append((fname, str(e)))
            print(f"[fail] {fname}: {e}", file=sys.stderr)
        time.sleep(0.1)  # 相手先 (GitHub raw) への連続アクセスを控えめにする

    print(f"\ndownloaded={ok} skipped={skipped} failed={len(failed)}")
    if failed:
        print("failed files:", [f[0] for f in failed], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
