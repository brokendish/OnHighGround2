#!/usr/bin/env python3
"""
relayout_fgd_dem.py — 旧 convert_dem.py が作った DEM を、画素値を変えずに標準的な GeoTIFF 配置へ並べ替える
（DEM-RUNTIME-REPAIR、2026-10-12。build node 専用）。

旧 convert_dem.py は 3 次メッシュ tile の配置だけを転置して結合していた（tile 内は正しい向き）:
  旧 mosaic の列 block = 緯度方向の tile index（南→北）、行 block = 経度方向の tile index（行 0 が東端）
  geotransform は x = 緯度、y = 経度
基盤地図情報の原本 GML が残っていないため、修正版 convert_dem.py で作り直す代わりに、この並べ替えで
同じ結果（tests/test_dem_runtime_repair.py が修正版 convert_dem.py の出力と一致することを確認）を作る。

出力（標準的な GeoTIFF）:
  x = 経度、y = 緯度、行 = 北→南、列 = 西→東、画素 1/18000°（0.2″）、EPSG:6668、Float32、LZW
  nodata = -9999（原本 tile の無い 3 次メッシュ（旧 DEM では 0.0 埋め）と NaN を -9999 にする）

  python3 scripts/derive/relayout_fgd_dem.py <旧 elevation.tif> <出力 elevation.tif>
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np

NODATA = -9999.0
RELAYOUT_VERSION = "relayout-fgd-dem/1"


def legacy_to_standard(arr: np.ndarray, n_tiles_lat: int, n_tiles_lon: int, tile_rows: int, tile_cols: int):
    """旧 mosaic（行 block = 経度 tile（東→西）、列 block = 緯度 tile（南→北））を
    標準配置（行 block = 緯度 tile（北→南）、列 block = 経度 tile（西→東））へ並べ替える。
    戻り値: (新しい配列, 原本 tile が無かった（全 cell 0.0）の tile 数)"""
    assert arr.shape == (n_tiles_lon * tile_rows, n_tiles_lat * tile_cols), arr.shape
    old4 = arr.reshape(n_tiles_lon, tile_rows, n_tiles_lat, tile_cols)
    # new4[緯度 tile（北から）, 行, 経度 tile（西から）, 列] = old4[経度 tile（東から）, 行, 緯度 tile（南から）, 列]
    new4 = np.ascontiguousarray(old4[::-1, :, ::-1, :].transpose(2, 1, 0, 3))
    missing = (new4 == 0).all(axis=(1, 3))  # 旧 merge が 0 で埋めた tile（原本が無い）
    new4[missing[:, None, :, None].repeat(tile_rows, 1).repeat(tile_cols, 3)] = NODATA
    out = new4.reshape(n_tiles_lat * tile_rows, n_tiles_lon * tile_cols)
    out[np.isnan(out)] = NODATA
    return out.astype(np.float32, copy=False), int(missing.sum())


def data_checksum(arr: np.ndarray) -> str:
    """圧縮・metadata に依存しない画素値の checksum（little-endian float32 の sha256）。"""
    return hashlib.sha256(np.ascontiguousarray(arr, dtype="<f4").tobytes()).hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main(argv=None) -> int:
    import rasterio
    from rasterio.transform import from_bounds

    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    src_path, dst_path = Path(args[0]), Path(args[1])
    lat0, lon0 = 35 + 1 / 3, 139.0  # 1 次メッシュ 5339
    with rasterio.open(src_path) as src:
        legacy = from_bounds(lat0, lon0, lat0 + 2 / 3, lon0 + 1, 18000, 12000)  # 旧 convert_dem の署名（x = 緯度）
        t, lg = tuple(src.transform)[:6], tuple(legacy)[:6]
        # GML の座標は 9 桁（35.333333333）、画素幅も丸められているため、原点は 1e-7°、画素幅は相対 1e-6 で照合
        signature_ok = (abs(t[2] - lg[2]) < 1e-7 and abs(t[5] - lg[5]) < 1e-7 and t[1] == 0 and t[3] == 0
                        and abs(t[0] / lg[0] - 1) < 1e-6 and abs(t[4] / lg[4] - 1) < 1e-6)
        if (src.width, src.height) != (18000, 12000) or src.crs.to_epsg() != 6668 or not signature_ok:
            print(f"ERROR: 旧 convert_dem 配置（メッシュ 5339、x = 緯度）ではない: {src_path} "
                  f"size={src.width}x{src.height} crs={src.crs} transform={tuple(src.transform)[:6]}", file=sys.stderr)
            return 2
        arr = src.read(1)
    out, missing = legacy_to_standard(arr, 80, 80, 150, 225)
    del arr
    src_sha = _sha256(src_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst_path.with_name(f".{dst_path.name}.tmp")
    profile = dict(driver="GTiff", width=18000, height=12000, count=1, dtype="float32", crs="EPSG:6668",
                   transform=from_bounds(lon0, lat0, lon0 + 1, lat0 + 2 / 3, 18000, 12000),
                   nodata=NODATA, compress="lzw")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(out, 1)
        dst.update_tags(OHG2_LAYOUT="standard north-up; x=longitude y=latitude; row north->south, col west->east",
                        OHG2_RELAYOUT_VERSION=RELAYOUT_VERSION, OHG2_DERIVED_FROM_SHA256=src_sha,
                        OHG2_FGD_MESH="5339", AREA_OR_POINT="Area")
    tmp.replace(dst_path)
    valid = out[out > NODATA]
    print(f"input  {src_path} sha256={src_sha}")
    print(f"output {dst_path} sha256={_sha256(dst_path)} data_checksum={data_checksum(out)}")
    print(f"missing tiles (0-filled → nodata) = {missing}, nodata cells = {int((out <= NODATA).sum())}, "
          f"valid = {valid.size} ({valid.size / out.size:.2%}), min = {valid.min():.2f}, max = {valid.max():.2f}")
    print(f"toolchain: rasterio {rasterio.__version__}, GDAL {rasterio.__gdal_version__}, numpy {np.__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
