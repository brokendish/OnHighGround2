#!/usr/bin/env bash
# generate_pseudo_inland_flood_pinned.sh — TOKYO-PSEUDO-INLAND-FLOOD-001 を本番と同じ toolchain で生成する。
#
# generate_pseudo_inland_flood.py の出力は GDAL の再投影結果に依存し、toolchain が違うとバイト列が変わる
# （2026-10-12 確認: x86_64 / GDAL 3.9.3 → 本番 canonical fffc6041…、aarch64 / GDAL 3.10.3 → 別の結果）。
# build node が Apple Silicon 等でも本番と同じ canonical を作れるよう、linux/amd64 の container で
# 本番 operator と同じ版の library を使って実行する（Docker Desktop の amd64 emulation を使用）。
#
#   scripts/derive/generate_pseudo_inland_flood_pinned.sh <DEM GeoTIFF> <出力 GeoJSON>
#   既定: data_lake/validated/tokyo/dem/elevation.tif → data_lake/validated/tokyo/pseudo_inland_flood/pseudo_inland_flood.geojson
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEM="${1:-${ROOT}/data_lake/validated/tokyo/dem/elevation.tif}"
OUT="${2:-${ROOT}/data_lake/validated/tokyo/pseudo_inland_flood/pseudo_inland_flood.geojson}"
DEM="$(cd "$(dirname "${DEM}")" && pwd)/$(basename "${DEM}")"   # docker -v は絶対 path が必要
mkdir -p "$(dirname "${OUT}")"
OUT="$(cd "$(dirname "${OUT}")" && pwd)/$(basename "${OUT}")"
# 本番 backend-operator（x86_64）と同じ版（2026-10-12 確認）
PINNED="rasterio==1.4.3 shapely==2.1.2 numpy==1.26.4 pyproj==3.7.2 affine==3.0.1"
EXPECTED_GDAL="3.9.3"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
docker run --rm --platform linux/amd64 \
    -v "${ROOT}/scripts/derive:/src:ro" -v "$(dirname "${DEM}"):/dem:ro" -v "${WORK}:/out" \
    python:3.11-slim sh -euc "
        apt-get update -qq >/dev/null && apt-get install -y -qq libexpat1 >/dev/null
        pip install -q ${PINNED} >/dev/null 2>&1
        python -c 'import rasterio, platform, sys; g = rasterio.__gdal_version__; print(platform.machine(), g); sys.exit(0 if g == \"${EXPECTED_GDAL}\" else 3)'
        python /src/generate_pseudo_inland_flood.py --dem /dem/$(basename "${DEM}") --output /out/pseudo_inland_flood.geojson"
mkdir -p "$(dirname "${OUT}")"
mv "${WORK}/pseudo_inland_flood.geojson" "${OUT}.tmp.$$" && mv -f "${OUT}.tmp.$$" "${OUT}"
echo "generated: ${OUT} sha256=$( (sha256sum "${OUT}" 2>/dev/null || shasum -a 256 "${OUT}") | cut -c1-64)"
