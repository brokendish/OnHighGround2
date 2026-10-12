#!/usr/bin/env python3
"""
audit_dem_elevation.py — DEM（elevation.tif）の標高値と、backend の読み取り位置を監査する（read-only）。

DEM-ELEVATION-INTEGRITY-AUDIT（2026-10-12）で確定した座標契約:

  data_processing/convert_dem.py は基盤地図情報 DEM の 3 次メッシュ GML（1 file = 緯度 150 × 経度 225 格子、
  sequenceRule +x-y）を、tile 内部は正しい向き（行 = 北→南の緯度、列 = 西→東の経度）で配列にする。
  ところが tile の transform は gml:lowerCorner/upperCorner（緯度 経度の順）を west/south/east/north として
  作るため、rasterio.merge は tile の「配置」だけを転置して並べる:

    mosaic の列 block = 緯度方向の tile index（南→北）
    mosaic の行 block = 経度方向の tile index（東→西、行 0 が経度最大）

  したがって (lat, lon) の正しい画素は
    tc = floor((lat - lat0) / tile_dlat)            緯度方向の tile index
    tl = floor((lon - lon0) / tile_dlon)            経度方向の tile index
    row_in = floor((tile_dlat - (lat - lat0 - tc*tile_dlat)) / (tile_dlat / tile_rows))
    col_in = floor((lon - lon0 - tl*tile_dlon) / (tile_dlon / tile_cols))
    row = (n_tiles_lon - 1 - tl) * tile_rows + row_in
    col = tc * tile_cols + col_in
  geotransform をそのまま使う読み方（x=緯度・y=経度。backend の ElevationService と PSEUDO generator）は、
  正しい tile を引くが tile 内では緯度の割合を列・経度の割合を行に使うため、最大で tile 1 枚分（約 0.9×1.1 km）
  ずれた画素を読む。

使い方（operator container 内）:
  python3 /scripts/validate/audit_dem_elevation.py --dem /data_lake/validated/tokyo/dem/elevation.tif \\
      --points points.json --tiles tiles/      # 地理院標高タイル（dem5a_png 等、z15）と比較
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class FgdMosaic:
    """convert_dem.py が作った mosaic の格子（1 次メッシュ単位）。"""
    lat0: float          # 南端
    lon0: float          # 西端
    tile_dlat: float     # 3 次メッシュの緯度幅
    tile_dlon: float     # 3 次メッシュの経度幅
    n_tiles_lat: int
    n_tiles_lon: int
    tile_rows: int       # tile 内の緯度方向の格子数
    tile_cols: int       # tile 内の経度方向の格子数

    @property
    def shape(self) -> Tuple[int, int]:
        return self.n_tiles_lon * self.tile_rows, self.n_tiles_lat * self.tile_cols


# 基盤地図情報 DEM 5m・1 次メッシュ 5339（3 次メッシュ 30″ × 45″、格子 0.2″ = 1/18000°）
MESH_5339 = FgdMosaic(lat0=35 + 1 / 3, lon0=139.0, tile_dlat=1 / 120, tile_dlon=1 / 80,
                      n_tiles_lat=80, n_tiles_lon=80, tile_rows=150, tile_cols=225)


def fgd_mosaic_rowcol(m: FgdMosaic, lat: float, lon: float) -> Optional[Tuple[int, int]]:
    """(lat, lon) を含む格子の (row, col)。範囲外は None。格子は北西角を原点とする cell（floor）。"""
    tc = int(math.floor((lat - m.lat0) / m.tile_dlat))
    tl = int(math.floor((lon - m.lon0) / m.tile_dlon))
    if not (0 <= tc < m.n_tiles_lat and 0 <= tl < m.n_tiles_lon):
        return None
    lat_off = lat - (m.lat0 + tc * m.tile_dlat)
    lon_off = lon - (m.lon0 + tl * m.tile_dlon)
    row_in = min(int(math.floor((m.tile_dlat - lat_off) / (m.tile_dlat / m.tile_rows))), m.tile_rows - 1)
    col_in = min(int(math.floor(lon_off / (m.tile_dlon / m.tile_cols))), m.tile_cols - 1)
    return (m.n_tiles_lon - 1 - tl) * m.tile_rows + row_in, tc * m.tile_cols + col_in


def gsi_tile_pixel(lat: float, lon: float, z: int = 15) -> Tuple[int, int, int, int]:
    """地理院タイル（Web メルカトル）の (tile x, tile y, pixel x, pixel y)。"""
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return int(x), int(y), int((x % 1) * 256), int((y % 1) * 256)


def decode_gsi_png_height(r: int, g: int, b: int) -> Optional[float]:
    """地理院標高タイル（PNG）の画素値 → 標高 m（無効値は None）。"""
    v = r * 65536 + g * 256 + b
    if v == 2 ** 23:
        return None
    return (v if v < 2 ** 23 else v - 2 ** 24) * 0.01


def _main() -> int:  # pragma: no cover - 監査 CLI（operator container で実行）
    import argparse
    import json
    import os
    import sys

    import numpy as np
    import rasterio
    from PIL import Image

    p = argparse.ArgumentParser(description="DEM の標高値と backend の読み取り位置を地理院標高タイルと比較する")
    p.add_argument("--dem", required=True)
    p.add_argument("--points", required=True, help='[{"name", "lat", "lon"}]')
    p.add_argument("--tiles", required=True, help="{layer}_{x}_{y}.png（dem5a_png / dem5b_png、z15）")
    a = p.parse_args()
    sys.path.insert(0, "/app")
    from elevation_service import ElevationService

    svc = ElevationService(a.dem)
    arr = svc.elevation_data
    out = []
    for pt in json.load(open(a.points, encoding="utf-8")):
        tx, ty, px, py = gsi_tile_pixel(pt["lat"], pt["lon"])
        ref = None
        for layer in ("dem5a_png", "dem5b_png"):
            f = os.path.join(a.tiles, f"{layer}_{tx}_{ty}.png")
            if os.path.exists(f) and open(f, "rb").read(4) == b"\x89PNG":
                ref = decode_gsi_png_height(*Image.open(f).convert("RGB").getpixel((px, py)))
                if ref is not None:
                    break
        rc = fgd_mosaic_rowcol(MESH_5339, pt["lat"], pt["lon"])
        cor = float(arr[rc]) if rc else None
        out.append({**pt, "reference": ref, "backend": svc.get_elevation_interpolated(pt["lat"], pt["lon"]),
                    "corrected": None if cor is None or cor <= -9999 or np.isnan(cor) else cor})
    for key in ("backend", "corrected"):
        d = np.array([r[key] - r["reference"] for r in out if r[key] is not None and r["reference"] is not None])
        print(f"{key:9s} n={len(d)} median|d|={np.median(np.abs(d)):.2f} p95={np.percentile(np.abs(d), 95):.2f} "
              f"max={np.abs(d).max():.2f} bias={d.mean():+.2f}")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
