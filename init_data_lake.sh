#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p \
  "${PROJECT_ROOT}/data_lake/registry/manifests" \
  "${PROJECT_ROOT}/data_lake/registry/mappings" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/dem" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/flood" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/tsunami" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/storm_surge" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/urban_flood" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/shelter" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/boundary" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/osm" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/dem" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/flood" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/tsunami" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/storm_surge" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/urban_flood" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/shelter" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/boundary" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/osm" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/dem" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/flood" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/tsunami" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/storm_surge" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/urban_flood" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/shelter" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/boundary" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/osm" \
  "${PROJECT_ROOT}/data_lake/tiles/tokyo/flood" \
  "${PROJECT_ROOT}/data_lake/tiles/tokyo/tsunami" \
  "${PROJECT_ROOT}/data_lake/tiles/tokyo/storm_surge" \
  "${PROJECT_ROOT}/data_lake/tiles/tokyo/urban_flood" \
  "${PROJECT_ROOT}/data_lake/logs/download" \
  "${PROJECT_ROOT}/data_lake/logs/normalize" \
  "${PROJECT_ROOT}/data_lake/logs/validate" \
  "${PROJECT_ROOT}/data_lake/logs/tile_build"

printf 'Initialized data lake under %s\n' "${PROJECT_ROOT}/data_lake"
