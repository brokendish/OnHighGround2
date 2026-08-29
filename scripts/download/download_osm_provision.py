#!/usr/bin/env python3
"""
download_osm_provision.py — OSM PBF fail-closed provisioning
（Phase 2-D Round 2、P2D-AT17-BOOTSTRAP対応、指示書Round 2第11.3節）

`scripts/download/download_osm.sh`（従来のno-opプレースホルダー、
"TODO: fetch Tokyo extract..."とログを出すだけで実データを取得しない）を、
実際にfail-closedで機能するprovisioningへ置き換える。

region/extractは明示指定必須（既定値は小規模なdocumented demo extractのみ）。
公式source（Geofabrik、https://download.geofabrik.de/）のみを許可domainとする。
OSM/ODbLの帰属・再配布時の扱いは docs/third-party-inventory.md GEO-OSM-ROAD/
GEO-OSM-RAIL、ATTRIBUTIONS.mdを参照。

full install時のwalking/driving OSRM artifact build手順:
  1. 本scriptで <region>.osm.pbf を取得する
  2. docker compose up (osrm-driving / osrm-walking) が起動時に
     data_lake/validated/tokyo/osm/{driving,walking}/ 配下のPBFから
     osrm-extract/osrm-partition/osrm-customizeを自動実行する
     （docker-compose.ymlのcommand参照）
  3. 生成されたinput PBF・出力.osrm*ファイルのhashをmanifestへ記録するのは
     本scriptの責務ではなく、OSRM自体が生成するため、本scriptはPBF取得段階の
     manifestのみを担当する

使い方（明示region必須、既定値なし）:
  python3 scripts/download/download_osm_provision.py \\
      --region kanto \\
      --output data_lake/raw/tokyo/osm/kanto-latest.osm.pbf

  # 利用可能なdocumented demo region一覧を見る
  python3 scripts/download/download_osm_provision.py --list-regions

停止条件: 公式domain外へのredirect、checksum不一致、archive破損、容量不足、
manifest atomic write失敗。いずれもfail-closedで非0終了し、半端なfileを残さない。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _provisioning_common import (  # noqa: E402
    FetchResult,
    ProvisioningError,
    check_disk_space,
    fetch_with_validation,
    write_manifest,
)

ALLOWED_DOMAINS = ("download.geofabrik.de",)

# 指示書第11.3節「既定値を設定する場合は小規模なdocumented demoだけとする」への対応。
# 全国/関東規模のPBFは数百MB〜数GBのため、既定にはしない（明示指定必須）。
# ここに列挙するのは実在するGeofabrik配布URLのうち、比較的小さいregion例のみ。
DOCUMENTED_REGIONS = {
    "kanto": {
        "url": "https://download.geofabrik.de/asia/japan/kanto-latest.osm.pbf",
        "note": "関東地方（約1都6県相当）。フル運用向け。数百MB規模。",
    },
    "japan": {
        "url": "https://download.geofabrik.de/asia/japan-latest.osm.pbf",
        "note": "日本全国。GB規模。全国道路/鉄道PMTiles生成用（scripts/tile_build/build_railway_pmtiles.sh参照）。",
    },
}

# 事前チェック用の目安ディスク要件（実ファイルサイズは変動するため安全側の概算）。
_ESTIMATED_MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def list_regions() -> None:
    for key, info in DOCUMENTED_REGIONS.items():
        print(f"{key}: {info['url']}\n  {info['note']}")


def provision(region: str, output_path: Path, *, overwrite: bool) -> int:
    if region not in DOCUMENTED_REGIONS:
        print(f"ERROR: unknown region {region!r}. Use --list-regions to see options.", file=sys.stderr)
        return 1

    url = DOCUMENTED_REGIONS[region]["url"]

    try:
        check_disk_space(output_path, _ESTIMATED_MIN_FREE_BYTES)
    except ProvisioningError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    result: FetchResult = fetch_with_validation(
        url,
        output_path,
        allowed_domains=ALLOWED_DOMAINS,
        timeout_seconds=120.0,
        max_retries=3,
        min_bytes=1024,  # 実PBFはこれよりずっと大きいが、明白に空/エラーページでないことの最低限確認
        overwrite_existing=overwrite,
    )

    if not result.ok:
        print(f"ERROR: fetch failed (fail-closed, no partial file left): {result.error}", file=sys.stderr)
        return 1

    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    write_manifest(manifest_path, {
        "artifact": str(output_path),
        "source_url": url,
        "region": region,
        "http_status": result.http_status,
        "bytes": result.bytes_written,
        "sha256": result.sha256,
        "license": "ODbL 1.0 (OpenStreetMap contributors)",
        "attribution": "© OpenStreetMap contributors (https://www.openstreetmap.org/copyright)",
        "redistribution_note": "Derivative-database treatment recommended per docs/third-party-inventory.md GEO-OSM-ROAD/GEO-OSM-RAIL",
    })

    print(f"OK: {output_path} ({result.bytes_written} bytes, sha256={result.sha256})")
    print(f"manifest: {manifest_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", help="documented region key (see --list-regions)")
    parser.add_argument("--output", type=Path, help="output .osm.pbf path")
    parser.add_argument("--list-regions", action="store_true", help="list documented region options and exit")
    parser.add_argument("--overwrite", action="store_true", help="allow overwriting an existing output file")
    args = parser.parse_args()

    if args.list_regions:
        list_regions()
        return 0

    if not args.region or not args.output:
        parser.error("--region and --output are required unless --list-regions is given (no implicit default region)")

    return provision(args.region, args.output, overwrite=args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
