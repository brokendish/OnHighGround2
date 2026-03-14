#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

copy_file_if_present() {
  if [[ "$#" -ne 2 ]]; then
    log_error "copy_file_if_present requires <source> <destination>"
    return 1
  fi

  local source_path="$1"
  local destination_path="$2"

  if [[ ! -f "${source_path}" ]]; then
    log_warn "Source file not found, skipping: ${source_path}"
    return 0
  fi

  mkdir -p "$(dirname "${destination_path}")"
  if [[ -f "${destination_path}" ]]; then
    log_info "Destination already exists, keeping: ${destination_path}"
    return 0
  fi

  cp "${source_path}" "${destination_path}"
  log_info "Copied file: ${source_path} -> ${destination_path}"
}

copy_tree_contents_if_present() {
  if [[ "$#" -ne 2 ]]; then
    log_error "copy_tree_contents_if_present requires <source_dir> <destination_dir>"
    return 1
  fi

  local source_dir="$1"
  local destination_dir="$2"

  if [[ ! -d "${source_dir}" ]]; then
    log_warn "Source directory not found, skipping: ${source_dir}"
    return 0
  fi

  mkdir -p "${destination_dir}"

  local file_path
  while IFS= read -r -d '' file_path; do
    local relative_path="${file_path#"${source_dir}/"}"
    local destination_path="${destination_dir}/${relative_path}"
    mkdir -p "$(dirname "${destination_path}")"
    if [[ -f "${destination_path}" ]]; then
      log_info "Destination already exists, keeping: ${destination_path}"
      continue
    fi
    cp "${file_path}" "${destination_path}"
    log_info "Copied file: ${file_path} -> ${destination_path}"
  done < <(find "${source_dir}" -type f -print0)
}

copy_matching_files() {
  if [[ "$#" -ne 3 ]]; then
    log_error "copy_matching_files requires <source_dir> <pattern> <destination_dir>"
    return 1
  fi

  local source_dir="$1"
  local pattern="$2"
  local destination_dir="$3"

  if [[ ! -d "${source_dir}" ]]; then
    log_warn "Source directory not found, skipping: ${source_dir}"
    return 0
  fi

  mkdir -p "${destination_dir}"

  local found=0
  local file_path
  while IFS= read -r -d '' file_path; do
    found=1
    local destination_path="${destination_dir}/$(basename "${file_path}")"
    if [[ -f "${destination_path}" ]]; then
      log_info "Destination already exists, keeping: ${destination_path}"
      continue
    fi
    cp "${file_path}" "${destination_path}"
    log_info "Copied file: ${file_path} -> ${destination_path}"
  done < <(find "${source_dir}" -maxdepth 1 -type f -name "${pattern}" -print0)

  if [[ "${found}" -eq 0 ]]; then
    log_warn "No files matched ${pattern} in ${source_dir}"
  fi
}

log_info "Initializing data lake structure"
"${PROJECT_ROOT}/init_data_lake.sh"

log_info "Migrating legacy DEM data"
copy_file_if_present \
  "${PROJECT_ROOT}/data/elevation.tif" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/dem/elevation.tif"
copy_file_if_present \
  "${PROJECT_ROOT}/data/elevation.tif" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/dem/elevation.tif"

log_info "Migrating shelter source data"
copy_file_if_present \
  "${PROJECT_ROOT}/国土地理院避難所データ/東京/13000_1/13000_1.geojson" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/shelter/tokyo_shelter.geojson"

log_info "Migrating legacy tsunami raw data"
copy_tree_contents_if_present \
  "${PROJECT_ROOT}/data/hazard" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/tsunami"

log_info "Migrating processed hazard GeoJSON into normalized data_lake"
copy_matching_files \
  "${PROJECT_ROOT}/data/processed/hazard" \
  "*flood*.geojson" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/flood"
copy_matching_files \
  "${PROJECT_ROOT}/data/processed/hazard" \
  "*tsunami*.geojson" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/tsunami"

log_info "Migrating legacy frontend hazard GeoJSON as compatibility sources"
copy_matching_files \
  "${PROJECT_ROOT}/frontend/hazard" \
  "*.geojson" \
  "${PROJECT_ROOT}/data_lake/normalized/tokyo/tsunami"

log_info "Migrating OSM source and OSRM outputs"
copy_file_if_present \
  "${PROJECT_ROOT}/data/kanto-260214.osm.pbf" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/osm/kanto-260214.osm.pbf"
copy_tree_contents_if_present \
  "${PROJECT_ROOT}/data/osrm/driving" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/osm/driving"
copy_tree_contents_if_present \
  "${PROJECT_ROOT}/data/osrm/walking" \
  "${PROJECT_ROOT}/data_lake/validated/tokyo/osm/walking"

log_info "Migrating existing root-level tiles into canonical tile storage"
copy_matching_files \
  "${PROJECT_ROOT}/tiles" \
  "*flood*.mbtiles" \
  "${PROJECT_ROOT}/data_lake/tiles/tokyo/flood"
copy_matching_files \
  "${PROJECT_ROOT}/tiles" \
  "*tsunami*.mbtiles" \
  "${PROJECT_ROOT}/data_lake/tiles/tokyo/tsunami"

log_info "Migration completed. Legacy data/ and tiles/ remain in place for compatibility."
