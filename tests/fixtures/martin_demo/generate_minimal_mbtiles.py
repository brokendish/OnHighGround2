#!/usr/bin/env python3
"""
generate_minimal_mbtiles.py — AT-17A demo profile用の最小・決定的MBTiles fixtureを
生成する（Phase 2-D、Martin AT-17A実機起動finding対応）。

このscriptが生成するMBTilesは合成（synthetic）データであり、実際の災害・地理
データではない。1x1ピクセルの完全透明PNGを唯一のtile（zoom=0, x=0, y=0）として
持つ、有効なMBTiles 1.3仕様準拠のラスタタイルセットである。目的はMartinが
実際に起動・読込み・tile応答できることを検証するためだけであり、地図表示上の
意味を持つコンテンツは一切含まない。

Python標準ライブラリ（sqlite3 / zlib / struct / binascii）のみで、外部ツール
（tippecanoe等）に依存せず決定的に生成する。同一Pythonバージョンで実行すれば、
毎回bit-identicalな.mbtilesファイルが生成される（SQLiteのvacuum後dumpで比較）。

使い方:
    python3 tests/fixtures/martin_demo/generate_minimal_mbtiles.py \\
        --output tests/fixtures/martin_demo/ohg2_demo_tile.mbtiles
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import sqlite3
import struct
import zlib
from pathlib import Path


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", binascii.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def _minimal_transparent_png_1x1() -> bytes:
    """1x1ピクセル、完全透明（alpha=0）のRGBA PNGを構築する。"""
    signature = b"\x89PNG\r\n\x1a\n"
    width, height = 1, 1
    bit_depth, color_type = 8, 6  # RGBA
    ihdr_data = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    # 1行 = filter type byte(0) + 4 bytes RGBA(全て0 = 透明黒)
    raw_scanline = b"\x00" + b"\x00\x00\x00\x00"
    compressed = zlib.compress(raw_scanline, level=9)
    idat = _png_chunk(b"IDAT", compressed)

    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def generate(output_path: Path) -> str:
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(str(output_path))
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        cur.execute(
            "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
            "tile_row INTEGER, tile_data BLOB)"
        )
        cur.execute(
            "CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)"
        )

        metadata = {
            "name": "ohg2_demo_tile",
            "format": "png",
            "type": "baselayer",
            "version": "1.0.0",
            "description": (
                "SYNTHETIC fixture for Phase 2-D AT-17A demo profile — "
                "NOT real hazard/geographic data. 1x1 transparent PNG placeholder tile."
            ),
            "attribution": "OnHighGround2 project (synthetic test fixture, no external source)",
            "minzoom": "0",
            "maxzoom": "0",
            "bounds": "139.0,35.0,140.0,36.0",
            "center": "139.5,35.5,0",
        }
        cur.executemany(
            "INSERT INTO metadata (name, value) VALUES (?, ?)", list(metadata.items())
        )

        png_bytes = _minimal_transparent_png_1x1()
        # MBTiles仕様のtile_row座標系はTMS（南から北）。zoom=0は1行1列のみなのでrow=0固定。
        cur.execute(
            "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (0, 0, 0, ?)",
            (sqlite3.Binary(png_bytes),),
        )
        conn.commit()
    finally:
        conn.close()

    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sha256 = generate(args.output)
    print(f"generated {args.output} sha256={sha256}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
