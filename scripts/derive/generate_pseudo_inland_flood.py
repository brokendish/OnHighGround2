#!/usr/bin/env python3
"""
generate_pseudo_inland_flood.py

DEM（数値標高モデル）から低地・内水リスク推定レイヤーを生成する。

出力:
  data_lake/validated/tokyo/pseudo_inland_flood/pseudo_inland_flood.geojson

アルゴリズム:
  risk_score = elevation_score + slope_score + depression_score
  score >= 70 → high / >= 45 → medium / >= 25 → low / < 25 → 出力しない

Usage:
  python scripts/derive/generate_pseudo_inland_flood.py [--dem PATH] [--output PATH]
  python scripts/derive/generate_pseudo_inland_flood.py --help
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.features import shapes as rasterio_shapes
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parent.parent.parent

# ── 定数（定数化: 将来の高精細化に対応） ──────────────────────────────────────
GRID_SIZE_M: int = 50           # 初期メッシュサイズ（将来 25m へ変更可）
DEPRESSION_WINDOW_M: int = 150  # 凹地判定ウィンドウ（m）

# DEM 検索パス（優先順）
_DEM_SEARCH_PATHS = [
    ROOT / "data_runtime" / "backend" / "elevation" / "elevation.tif",
    ROOT / "data" / "elevation.tif",
    ROOT / "data_lake" / "validated" / "tokyo" / "dem" / "elevation.tif",
]

OUTPUT_DIR = ROOT / "data_lake" / "validated" / "tokyo" / "pseudo_inland_flood"
OUTPUT_FILE = OUTPUT_DIR / "pseudo_inland_flood.geojson"

# 東京地域に適した平面直角座標系（1 unit = 1 m）
METRIC_EPSG: int = 6677   # JGD2011 / Japan Plane Rectangular CS IX
OUTPUT_EPSG: int = 4326   # WGS84 地理座標

RISK_LEVEL_MAP = {1: "low", 2: "medium", 3: "high"}
BUFFER_M = {"low": 5, "medium": 10, "high": 15}
# risk_score の代表値（レベル中間値）
RISK_SCORE_REP = {"low": 30, "medium": 55, "high": 80}


# ── ユーティリティ ──────────────────────────────────────────────────────────

def _find_dem(custom_path: str | None) -> Path | None:
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p
        print(f"WARNING: 指定 DEM パスが存在しません: {p}", file=sys.stderr)
    for p in _DEM_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def _box_mean_2d(arr: np.ndarray, window: int) -> np.ndarray:
    """2D ボックス平均フィルタ（積算和による O(n) 実装）。"""
    if window < 3:
        return arr.astype(np.float32)
    pad = window // 2
    padded = np.pad(arr.astype(np.float64), pad, mode="reflect")
    cs = np.pad(
        np.cumsum(np.cumsum(padded, axis=0), axis=1),
        ((1, 0), (1, 0)),
        mode="constant",
        constant_values=0,
    )
    result = (
        cs[window:, window:]
        - cs[:-window, window:]
        - cs[window:, :-window]
        + cs[:-window, :-window]
    ) / (window * window)
    return result.astype(np.float32)


def _is_axis_swapped_geographic(bounds) -> bool:
    """既存DEMにある lat/lon 軸入れ替わり GeoTIFF を検出する。"""
    return (
        -90 <= bounds.left <= 90
        and -90 <= bounds.right <= 90
        and -180 <= bounds.bottom <= 180
        and -180 <= bounds.top <= 180
        and abs(bounds.bottom) > 90
        and abs(bounds.top) > 90
    )


def _canonicalize_swapped_geographic(src) -> tuple[np.ndarray, object, CRS]:
    """
    GSI DEM 変換由来の軸入れ替わりラスタを通常の lon/lat 配列へ補正する。

    元データは x=lat, y=lon として保存されているため、配列を転置し、
    north-up / west-east の通常配置に反転してから lon/lat bounds を付け直す。
    """
    arr = src.read(1)
    canonical = np.flip(arr.T, axis=(0, 1)).astype(np.float32, copy=False)
    b = src.bounds
    transform = from_bounds(
        b.bottom,  # west  (lon min)
        b.left,    # south (lat min)
        b.top,     # east  (lon max)
        b.right,   # north (lat max)
        canonical.shape[1],
        canonical.shape[0],
    )
    return canonical, transform, CRS.from_epsg(OUTPUT_EPSG)


# ── スコア計算（ベクタライズ） ───────────────────────────────────────────────

def _elevation_scores(elev: np.ndarray, valid: np.ndarray) -> np.ndarray:
    scores = np.zeros(elev.shape, dtype=np.int16)
    scores[valid & (elev < 5)] = 40
    scores[valid & (elev >= 5) & (elev < 10)] = 25
    scores[valid & (elev >= 10) & (elev < 20)] = 10
    return scores


def _slope_scores(elev: np.ndarray, cell_m: int, valid: np.ndarray) -> np.ndarray:
    # numpy.gradient は NaN を含む場合 NaN を伝播するため、無効セルを 0 で埋める
    elev_fill = np.where(valid, elev, 0.0).astype(np.float64)
    dy, dx = np.gradient(elev_fill, cell_m, cell_m)
    slope_deg = np.degrees(np.arctan(np.sqrt(dx ** 2 + dy ** 2)))
    scores = np.zeros(elev.shape, dtype=np.int16)
    scores[valid & (slope_deg < 1)] = 25
    scores[valid & (slope_deg >= 1) & (slope_deg < 3)] = 15
    scores[valid & (slope_deg >= 3) & (slope_deg < 5)] = 5
    return scores


def _depression_scores(
    elev: np.ndarray, window_m: int, cell_m: int, valid: np.ndarray
) -> np.ndarray:
    window_cells = max(3, int(window_m / cell_m))
    if window_cells % 2 == 0:
        window_cells += 1
    local_mean = _box_mean_2d(np.where(valid, elev, 0.0).astype(np.float32), window_cells)
    depression = elev.astype(np.float32) - local_mean
    scores = np.zeros(elev.shape, dtype=np.int16)
    scores[valid & (depression <= -2.0)] = 25
    scores[valid & (depression > -2.0) & (depression <= -1.0)] = 15
    scores[valid & (depression > -1.0) & (depression <= -0.5)] = 5
    return scores


# ── メイン ──────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="DEM から低地・内水リスク推定 GeoJSON を生成する"
    )
    parser.add_argument("--dem", help="DEM GeoTIFF パス（省略時は自動検索）")
    parser.add_argument("--output", help=f"出力 GeoJSON パス（デフォルト: {OUTPUT_FILE}）")
    parser.add_argument(
        "--grid-size-m", type=int, default=GRID_SIZE_M,
        help=f"メッシュサイズ（メートル、デフォルト: {GRID_SIZE_M}）",
    )
    parser.add_argument(
        "--depression-window-m", type=int, default=DEPRESSION_WINDOW_M,
        help=f"凹地判定ウィンドウ（メートル、デフォルト: {DEPRESSION_WINDOW_M}）",
    )
    parser.add_argument(
        "--no-buffer", action="store_true", help="バッファ処理をスキップ"
    )
    args = parser.parse_args()

    grid_m: int = args.grid_size_m
    depr_window_m: int = args.depression_window_m

    dem_path = _find_dem(args.dem)
    if not dem_path:
        print(
            "ERROR: DEM ファイルが見つかりません。\n"
            "  - data/elevation.tif を配置するか\n"
            "  - --dem でパスを指定してください。",
            file=sys.stderr,
        )
        return 1

    output_file = Path(args.output) if args.output else OUTPUT_FILE
    output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"DEM          : {dem_path}")
    print(f"Grid         : {grid_m} m")
    print(f"Depr. window : {depr_window_m} m")
    print(f"Buffer       : {'なし' if args.no_buffer else 'あり'}")
    print(f"Output       : {output_file}")

    # ── DEM を metric CRS にリプロジェクト ─────────────────────────────────
    metric_crs = CRS.from_epsg(METRIC_EPSG)

    with rasterio.open(dem_path) as src:
        src_crs = src.crs
        src_transform = src.transform
        source_data = rasterio.band(src, 1)
        if src_crs and src_crs.is_geographic and _is_axis_swapped_geographic(src.bounds):
            print("DEM axis     : swapped lat/lon detected; canonicalizing to lon/lat")
            source_data, src_transform, src_crs = _canonicalize_swapped_geographic(src)
            src_bounds = rasterio.transform.array_bounds(
                source_data.shape[0], source_data.shape[1], src_transform
            )
            src_width = source_data.shape[1]
            src_height = source_data.shape[0]
        else:
            src_bounds = src.bounds
            src_width = src.width
            src_height = src.height

        metric_transform, width, height = calculate_default_transform(
            src_crs, metric_crs, src_width, src_height, *src_bounds,
            resolution=grid_m,
        )
        _NODATA_FILL = -9999.0
        elev_data = np.full((height, width), _NODATA_FILL, dtype=np.float32)

        reproject(
            source=source_data,
            destination=elev_data,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=metric_transform,
            dst_crs=metric_crs,
            resampling=Resampling.bilinear,
            dst_nodata=_NODATA_FILL,
        )

    print(f"Resampled    : {width} × {height} = {width * height:,} cells")

    # ── ノイズ・無効値マスク ────────────────────────────────────────────────
    nodata_mask = (elev_data <= -9999.0) | np.isnan(elev_data)
    valid = ~nodata_mask & (elev_data >= 0.0)

    # ── スコア計算 ──────────────────────────────────────────────────────────
    print("Calculating elevation scores...")
    e_scores = _elevation_scores(elev_data, valid)

    print("Calculating slope scores...")
    s_scores = _slope_scores(elev_data, grid_m, valid)

    print("Calculating depression scores...")
    d_scores = _depression_scores(elev_data, depr_window_m, grid_m, valid)

    total = e_scores + s_scores + d_scores

    # ── リスク分類 ──────────────────────────────────────────────────────────
    risk_int = np.zeros(total.shape, dtype=np.uint8)
    risk_int[(total >= 25) & (total < 45) & valid] = 1   # low
    risk_int[(total >= 45) & (total < 70) & valid] = 2   # medium
    risk_int[(total >= 70)               & valid] = 3   # high

    n_low    = int(np.sum(risk_int == 1))
    n_medium = int(np.sum(risk_int == 2))
    n_high   = int(np.sum(risk_int == 3))
    print(f"Risk cells   : low={n_low:,}  medium={n_medium:,}  high={n_high:,}")

    if (n_low + n_medium + n_high) == 0:
        print("WARNING: リスクセルが 0 件です。DEM の範囲・品質を確認してください。")

    # ── ベクタライズ（rasterio.features.shapes で隣接同値セルを自動結合） ──
    print("Vectorizing (dissolving adjacent cells)...")
    risk_mask = (risk_int > 0).astype(np.uint8)

    transformer = Transformer.from_crs(METRIC_EPSG, OUTPUT_EPSG, always_xy=True)

    features: list[dict] = []
    for geom_dict, value in rasterio_shapes(
        risk_int, mask=risk_mask, transform=metric_transform
    ):
        level = RISK_LEVEL_MAP[int(value)]
        geom = shape(geom_dict)

        # バッファ（metric CRS 内でメートル単位）
        if not args.no_buffer:
            buf = BUFFER_M[level]
            if buf > 0:
                geom = geom.buffer(buf, join_style=2)  # mitre join

        # WGS84 に変換
        geom_wgs84 = shp_transform(transformer.transform, geom)

        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom_wgs84),
                "properties": {
                    "layer_type": "pseudo_inland_flood",
                    "risk_level": level,
                    "risk_score": RISK_SCORE_REP[level],
                    "source": "dem_estimated",
                    "official": False,
                    "grid_size_m": grid_m,
                },
            }
        )

    print(f"Features     : {len(features):,}")

    # ── GeoJSON 出力 ────────────────────────────────────────────────────────
    fc = {"type": "FeatureCollection", "features": features}
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)

    size_mb = output_file.stat().st_size / (1024 ** 2)
    print(f"\n完了: {output_file} ({size_mb:.1f} MB, {len(features):,} features)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
