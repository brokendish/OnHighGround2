#!/usr/bin/env python3
"""
build_tiles.py — ハザード GeoJSON → ベクタータイル (MBTiles)

tippecanoe を使ってハザード GeoJSON ファイルをベクタータイルに変換します。

Usage:
    python scripts/build_tiles.py [options]

Options:
    --profile PROF    ビルドプロファイル (デフォルト: current)
    --minzoom INT     最小ズームレベル (デフォルト: 5)
    --maxzoom INT     最大ズームレベル (デフォルト: 16)
    --input DIR       GeoJSON ファイルが置かれたディレクトリ
                      (デフォルト: data_lake/normalized/tokyo)
    --output DIR      .mbtiles 出力ディレクトリ
                      (デフォルト: data_lake/tiles/tokyo)
    --dry-run         実行せずにコマンドを表示のみ

プロファイル:
    current  ベースライン。--no-tile-compression のみ。現行 runtime と同等。
    drop     描画削減プロファイル。--drop-densest-as-needed で低ズームの
             フィーチャ密度を間引く。storm_surge は追加で coalesce +
             detect-shared-borders を適用。

評価観点:
    current → drop で改善すべき指標:
      - 低ズーム（z8/z10）の 1 タイルあたり feature 数
      - ブラウザの描画 CPU 負荷（Chrome DevTools Main thread）
      - パン・ズームの引っかかり感
    許容されるトレードオフ:
      - z5〜z10 での小面積浸水域の非表示（防災目的のため要目視確認）

入力ディレクトリについて:
    デフォルト: data_lake/normalized/tokyo/   ← 正規化済みデータ
    互換:       data/processed/hazard/        ← 旧処理済み GeoJSON
    暫定:       frontend/hazard/              ← 旧フロント直読場所

出力ディレクトリ構成:
    data_lake/tiles/tokyo/{hazard_type}/{dataset}.mbtiles
"""

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

# ── プロファイル定義 ──────────────────────────────────────────────────────────
#
# DATASET_PROFILES[dataset][profile] = 追加フラグのリスト
# すべてのプロファイルに共通するフラグ:
#   --no-tile-compression（転送量の観点で CURRENT が最良と確認済み）
#   --minimum-zoom / --maximum-zoom / --output / --force / --layer
#
# flood へ --coalesce-densest-as-needed を適用すると 66 万フィーチャで
# tippecanoe が収束不能になるため、flood には適用しない。
#
DATASET_PROFILES: dict[str, dict[str, list[str]]] = {
    "tokyo_flood_max": {
        "current": [],
        "drop": [
            "--drop-densest-as-needed",
        ],
    },
    "tokyo_storm_surge": {
        "current": [],
        "drop": [
            "--drop-densest-as-needed",
            "--coalesce-densest-as-needed",
            "--detect-shared-borders",
        ],
    },
}

# 上記に定義のないデータセットへのフォールバック
DEFAULT_PROFILES: dict[str, list[str]] = {
    "current": [],
    "drop": ["--drop-densest-as-needed"],
}


def find_geojson_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.rglob("*.geojson"))


def extra_flags(dataset: str, profile: str) -> list[str]:
    return DATASET_PROFILES.get(dataset, DEFAULT_PROFILES).get(profile, [])


def build_tiles(
    geojson_path: Path,
    input_dir: Path,
    output_dir: Path,
    minzoom: int,
    maxzoom: int,
    profile: str,
    dry_run: bool,
) -> bool:
    dataset = geojson_path.stem
    relative_parent = geojson_path.parent.relative_to(input_dir)
    output_path = output_dir / relative_parent / f"{dataset}.mbtiles"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "tippecanoe",
        f"--minimum-zoom={minzoom}",
        f"--maximum-zoom={maxzoom}",
        "--output", str(output_path),
        "--force",
        "--no-tile-compression",
        "--layer", dataset,
    ] + extra_flags(dataset, profile) + [str(geojson_path)]

    print(f"\n[build:{profile}] {geojson_path.name} → {output_path.relative_to(ROOT)}")
    print("  " + " ".join(cmd))

    if dry_run:
        print("  [dry-run] skipped")
        return True

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] tippecanoe failed:\n{result.stderr}", file=sys.stderr)
        return False

    size_mb = output_path.stat().st_size / (1024 ** 2)
    print(f"  [OK] {size_mb:.1f} MB")
    _print_tile_stats(output_path)
    return True


def _print_tile_stats(mbtiles_path: Path) -> None:
    """ズーム別タイルサイズと feature 数サマリーを表示する。"""
    try:
        con = sqlite3.connect(mbtiles_path)

        # ズーム別タイルサイズ
        rows = con.execute(
            "SELECT zoom_level, COUNT(*), "
            "ROUND(AVG(LENGTH(tile_data))/1024.0,1), "
            "ROUND(MAX(LENGTH(tile_data))/1024.0,1) "
            "FROM tiles GROUP BY zoom_level ORDER BY zoom_level"
        ).fetchall()
        print("  zoom  tiles   avg_kb   max_kb")
        for z, cnt, avg, mx in rows:
            print(f"    {z:2d}  {cnt:5d}  {avg:7.1f}  {mx:7.1f}")

        # tippecanoe strategies から zoom ごとの tiny_polygons を取得
        meta = con.execute(
            "SELECT value FROM metadata WHERE name='strategies'"
        ).fetchone()
        if meta:
            strategies = json.loads(meta[0])
            print("  zoom  tiny_polygons  detail_reduced  tile_size_desired")
            for z_idx, s in enumerate(strategies):
                if s:
                    tp  = s.get("tiny_polygons", "-")
                    dr  = s.get("detail_reduced", "-")
                    tsd = s.get("tile_size_desired", "-")
                    print(f"    {z_idx:2d}  {str(tp):>13}  {str(dr):>14}  {str(tsd):>17}")

        con.close()
    except Exception as e:
        print(f"  [warn] stats unavailable: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="ハザード GeoJSON ファイルからベクタータイルを生成します。"
    )
    parser.add_argument("--minzoom", type=int, default=5)
    parser.add_argument("--maxzoom", type=int, default=16)
    parser.add_argument(
        "--profile",
        choices=["current", "drop"],
        default="current",
        help=(
            "ビルドプロファイル:\n"
            "  current = --no-tile-compression のみ（baseline）\n"
            "  drop    = current + --drop-densest-as-needed（描画削減）\n"
            "(デフォルト: current)"
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data_lake" / "normalized" / "tokyo",
        help="GeoJSON ファイルが置かれたディレクトリ",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data_lake" / "tiles" / "tokyo",
        help=".mbtiles ファイルの出力ディレクトリ",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not shutil.which("tippecanoe"):
        print(
            "ERROR: tippecanoe がインストールされていないか、PATH に含まれていません。\n"
            "インストール方法:\n"
            "  macOS:  brew install tippecanoe\n"
            "  Ubuntu: sudo apt install tippecanoe\n"
            "  またはソースからビルド: https://github.com/felt/tippecanoe",
            file=sys.stderr,
        )
        sys.exit(1)

    input_dir: Path = args.input.resolve()
    output_dir: Path = args.output.resolve()

    if not input_dir.exists():
        print(f"ERROR: input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    geojson_files = find_geojson_files(input_dir)
    if not geojson_files:
        msg = f"No .geojson files found in {input_dir.relative_to(ROOT)}"
        legacy_processed = ROOT / "data" / "processed" / "hazard"
        fallback = ROOT / "frontend" / "hazard"
        if legacy_processed.exists() and list(legacy_processed.glob("*.geojson")):
            msg += (
                "\n\nヒント: data/processed/hazard/ に GeoJSON ファイルが見つかりました（旧処理済み置き場）。"
                "\n  移行スクリプト:      ./scripts/migrate/migrate_to_data_lake.sh"
                "\n  一時的に使用する場合: python scripts/build_tiles.py --input data/processed/hazard"
            )
        elif fallback.exists() and list(fallback.glob("*.geojson")):
            msg += (
                "\n\nヒント: frontend/hazard/ に GeoJSON ファイルが見つかりました（レガシーの場所）。"
                "\n  今すぐ使用する場合:  python scripts/build_tiles.py --input frontend/hazard"
                "\n  推奨対応:           ./scripts/migrate/migrate_to_data_lake.sh で data_lake に集約してください"
            )
        print(msg, file=sys.stderr)
        sys.exit(1)

    print(f"Input:    {input_dir.relative_to(ROOT)}")
    print(f"Output:   {output_dir.relative_to(ROOT)}")
    print(f"Zoom:     {args.minzoom} – {args.maxzoom}")
    print(f"Profile:  {args.profile}")
    print(f"Datasets: {[f.name for f in geojson_files]}")

    results = []
    for geojson_path in geojson_files:
        ok = build_tiles(
            geojson_path, input_dir, output_dir,
            args.minzoom, args.maxzoom, args.profile, args.dry_run,
        )
        results.append((geojson_path.name, ok))

    print("\n--- Summary ---")
    all_ok = True
    for name, ok in results:
        status = "OK" if ok else "FAILED"
        print(f"  [{status}] {name}")
        if not ok:
            all_ok = False

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
