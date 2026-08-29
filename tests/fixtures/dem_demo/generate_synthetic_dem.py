#!/usr/bin/env python3
"""
generate_synthetic_dem.py — AT-17A demo profile用の最小・決定的synthetic DEM
fixtureを生成する（Phase 2-D Round 9、P2D-AT17-DEM-BOOTSTRAP対応）。

このscriptが生成するGeoTIFFは合成（synthetic）標高データであり、実際の
測量・地理標高データではない。値は本script内の明示的な数式（sin/cos合成、
固定係数）のみで決定的に計算され、乱数・外部network・実DEM由来の値は
一切使用しない。実際の災害判断・避難判断・標高評価には使用できない。

format / CRS / 軸順は`backend/elevation_service.py`が実運用DEM
（`data_runtime/backend/elevation/elevation.tif`、EPSG:6668、
「column軸(x)=緯度・row軸(y)=経度、東端を原点にrow増加で経度が減少する」
という座標swapped配置——`rasterio.open()`実測: transform c=35.33=lat_min,
transform f=140.00=lon_max, e<0）と同一の契約に合わせる。これは
`ElevationService._to_dataset_xy()`が本番DEMの軸swapを検出して補正する
分岐（`candidates = [(x,y), (y,x)]`）を、demo fixtureでも同じcode pathで
検証するための意図的な選択であり、実標高値の再現ではない（値は本script
のsynthetic formula由来）。

Python標準ライブラリ + rasterio（backendの既存依存、requirements.txt
`rasterio==1.4.3`と同一APIで読み書き可能なGeoTIFF）のみで、外部ツールに
依存せず決定的に生成する。同一rasterio/GDALバージョンで実行すれば、
毎回bit-identicalな.tifファイルが生成される（本fixtureのtest実行時に
2回生成しSHA-256一致を確認する）。timestampやhost固有情報はfileへ
埋め込まない。

使い方:
    python3 tests/fixtures/dem_demo/generate_synthetic_dem.py \\
        --output tests/fixtures/dem_demo/elevation_demo.tif
"""
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine

# demo OSM fixture（tests/fixtures/osm_demo/MANIFEST.json）のbboxを正本として
# 取得したTokyo駅周辺の範囲（west, south, east, north、WGS84度）。
DEMO_OSM_BBOX = (139.760, 35.676, 139.774, 35.686)

# demo OSM bboxの全範囲をmargin付きで覆うfixture自身のbbox。
MARGIN_DEG = 0.02
FIXTURE_WEST = DEMO_OSM_BBOX[0] - MARGIN_DEG
FIXTURE_SOUTH = DEMO_OSM_BBOX[1] - MARGIN_DEG
FIXTURE_EAST = DEMO_OSM_BBOX[2] + MARGIN_DEG
FIXTURE_NORTH = DEMO_OSM_BBOX[3] + MARGIN_DEG

# 0.001度刻み（緯度・経度ともに、実運用DEMの解像度とは無関係な
# demo専用の小さいgrid）。
CELL_SIZE_DEG = 0.001

# raster width = column軸 = 緯度方向の刻み数。
N_LAT_STEPS = round((FIXTURE_NORTH - FIXTURE_SOUTH) / CELL_SIZE_DEG)
# raster height = row軸 = 経度方向の刻み数。
N_LON_STEPS = round((FIXTURE_EAST - FIXTURE_WEST) / CELL_SIZE_DEG)

CRS = "EPSG:6668"  # JGD2011 geographic 2D。本番DEMと同一CRS（構造の忠実性のため、値は非実データ）。
NODATA_SENTINEL = -9999.0

# NoData contract検証用に、demo OSM bboxから離れた1隅（row/col原点付近）
# だけをNoDataにする（4.3節「nodataだけにしない」を満たすため、
# interior領域（demo OSM bboxをcoverするcell群）は必ず有効値を持つ）。
NODATA_BLOCK_ROWS = (0, 3)  # [start, end) — row軸 = 経度方向
NODATA_BLOCK_COLS = (0, 3)  # [start, end) — col軸 = 緯度方向


def _elevation_formula(row: int, col: int) -> float:
    """明示的なsynthetic formula。乱数不使用、row/colのみに依存する決定的な値。"""
    return 8.0 + 6.0 * math.sin(col * 0.35) + 4.0 * math.cos(row * 0.28) + 0.05 * (row + col)


def build_elevation_array() -> np.ndarray:
    """shape=(height, width)=(N_LON_STEPS, N_LAT_STEPS)。row=経度軸index、
    col=緯度軸index（rasterioのband配列規約: array[row, col]）。"""
    arr = np.empty((N_LON_STEPS, N_LAT_STEPS), dtype=np.float32)
    for row in range(N_LON_STEPS):
        for col in range(N_LAT_STEPS):
            arr[row, col] = _elevation_formula(row, col)

    arr[
        NODATA_BLOCK_ROWS[0]:NODATA_BLOCK_ROWS[1],
        NODATA_BLOCK_COLS[0]:NODATA_BLOCK_COLS[1],
    ] = NODATA_SENTINEL
    return arr


def build_transform() -> Affine:
    """本番DEM（`data_runtime/backend/elevation/elevation.tif`）と同一の軸
    swap配置を再現する: column軸(x)=緯度（南端(FIXTURE_SOUTH)が原点、
    column増加で北へ）、row軸(y)=経度（東端(FIXTURE_EAST)が原点、row増加
    でeが負のため経度が減少=西へ進む）。本番DEMの`transform`実測値
    （c=35.33=lat_min、f=140.00=lon_max、e<0）と同じ符号・原点の取り方
    であり、`ElevationService._to_dataset_xy()`の軸swap検出分岐
    （`candidates = [(x,y), (y,x)]`）を本番と同じcode pathで検証するための
    意図的な一致（値そのものはsynthetic）。"""
    return Affine(
        CELL_SIZE_DEG, 0.0, FIXTURE_SOUTH,
        0.0, -CELL_SIZE_DEG, FIXTURE_EAST,
    )


def generate(output_path: Path) -> str:
    if output_path.exists():
        output_path.unlink()

    elevation = build_elevation_array()
    transform = build_transform()

    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "count": 1,
        "width": N_LAT_STEPS,
        "height": N_LON_STEPS,
        "crs": CRS,
        "transform": transform,
        "nodata": NODATA_SENTINEL,
        "compress": None,
        "tiled": False,
        "interleave": "band",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(elevation, 1)

    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sha256 = generate(args.output)
    print(
        f"generated {args.output} sha256={sha256} "
        f"width={N_LAT_STEPS} height={N_LON_STEPS} crs={CRS}"
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
