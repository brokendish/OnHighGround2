#!/usr/bin/env python3
"""
build_tiles.py — ハザード GeoJSON → ベクタータイル (MBTiles)

tippecanoe を使ってハザード GeoJSON ファイルをベクタータイルに変換します。

Usage:
    python scripts/build_tiles.py [options]

Options:
    --minzoom INT     最小ズームレベル (デフォルト: 5)
    --maxzoom INT     最大ズームレベル (デフォルト: 14)
    --input DIR       GeoJSON ファイルが置かれたディレクトリ (デフォルト: data/processed/hazard)
    --output DIR      .mbtiles 出力ディレクトリ (デフォルト: tiles)
    --dry-run         実行せずにコマンドを表示のみ

入力ディレクトリについて:
    デフォルト: data/processed/hazard/   ← 正規の GeoJSON ソースの場所
    暫定:       frontend/hazard/         ← 移行中は --input frontend/hazard で使用
    frontend/hazard/ は長期的なソースの置き場として使用しないこと。
    データパイプラインの方針については scripts/README.md を参照。

出力ディレクトリ構成について:
    現在:   tiles/{dataset}.mbtiles
    将来:   tiles/{region}/{hazard_type}/{dataset}.mbtiles
            例: tiles/japan/tokyo/tsunami/tsunami_tokyo.mbtiles
    長期的なレイアウトは scripts/README.md に記載。
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def find_geojson_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("*.geojson"))


def build_tiles(
    geojson_path: Path,
    output_dir: Path,
    minzoom: int,
    maxzoom: int,
    dry_run: bool,
) -> bool:
    dataset = geojson_path.stem  # 例: "tsunami_tokyo"
    output_path = output_dir / f"{dataset}.mbtiles"

    cmd = [
        "tippecanoe",
        f"--minimum-zoom={minzoom}",
        f"--maximum-zoom={maxzoom}",
        "--output", str(output_path),
        "--force",              # 既存の出力を上書き
        "--no-tile-compression",
        "--layer", dataset,
        str(geojson_path),
    ]

    print(f"\n[build] {geojson_path.name} → {output_path.relative_to(ROOT)}")
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
    return True


def main():
    parser = argparse.ArgumentParser(description="ハザード GeoJSON ファイルからベクタータイルを生成します。")
    parser.add_argument("--minzoom", type=int, default=5)
    parser.add_argument("--maxzoom", type=int, default=14)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "processed" / "hazard",
        help="GeoJSON ファイルが置かれたディレクトリ (デフォルト: data/processed/hazard)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tiles",
        help=".mbtiles ファイルの出力ディレクトリ",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # tippecanoe の存在確認（dry-run 時はスキップし、インストールなしでもパイプラインを検証できるようにする）
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
        # 旧来の場所を使用している場合はヒントを表示
        fallback = ROOT / "frontend" / "hazard"
        if fallback.exists() and list(fallback.glob("*.geojson")):
            msg += (
                "\n\nヒント: frontend/hazard/ に GeoJSON ファイルが見つかりました（レガシーの場所）。"
                "\n  今すぐ使用する場合:  python scripts/build_tiles.py --input frontend/hazard"
                "\n  推奨対応:           data/processed/hazard/ にコピーまたは移動してください"
            )
        print(msg, file=sys.stderr)
        sys.exit(1)

    print(f"Input:    {input_dir.relative_to(ROOT)}")
    print(f"Output:   {output_dir.relative_to(ROOT)}")
    print(f"Zoom:     {args.minzoom} – {args.maxzoom}")
    print(f"Datasets: {[f.name for f in geojson_files]}")

    results = []
    for geojson_path in geojson_files:
        ok = build_tiles(geojson_path, output_dir, args.minzoom, args.maxzoom, args.dry_run)
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
