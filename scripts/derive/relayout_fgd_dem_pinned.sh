#!/usr/bin/env bash
# relayout_fgd_dem_pinned.sh — relayout_fgd_dem.py を本番と同じ toolchain（linux/amd64・GDAL 3.9.3）で実行する。
# GeoTIFF（LZW）の byte 列は GDAL の版で変わりうるため、build node（Apple Silicon 等）でも同じ artifact を作る。
#   scripts/derive/relayout_fgd_dem_pinned.sh <旧 elevation.tif> <出力 elevation.tif>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
mkdir -p "$(dirname "$2")"
OUT="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
PINNED="rasterio==1.4.3 numpy==1.26.4 affine==3.0.1"
EXPECTED_GDAL="3.9.3"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
docker run --rm --platform linux/amd64 \
    -v "${ROOT}/scripts/derive:/src:ro" -v "$(dirname "${SRC}"):/in:ro" -v "${WORK}:/out" \
    python:3.11-slim sh -euc "
        apt-get update -qq >/dev/null && apt-get install -y -qq libexpat1 >/dev/null
        pip install -q ${PINNED} >/dev/null 2>&1
        python -c 'import rasterio, platform, sys; g = rasterio.__gdal_version__; print(platform.machine(), g); sys.exit(0 if g == \"${EXPECTED_GDAL}\" else 3)'
        python /src/relayout_fgd_dem.py /in/$(basename "${SRC}") /out/elevation.tif"
mv "${WORK}/elevation.tif" "${OUT}.tmp.$$" && mv -f "${OUT}.tmp.$$" "${OUT}"
echo "generated: ${OUT} sha256=$( (sha256sum "${OUT}" 2>/dev/null || shasum -a 256 "${OUT}") | cut -c1-64)"
