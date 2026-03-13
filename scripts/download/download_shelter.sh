#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

SOURCE_FILE="${PROJECT_ROOT}/国土地理院避難所データ/東京/13000_1/13000_1.geojson"
OUTPUT_DIR="${1:-${PROJECT_ROOT}/data_lake/raw/tokyo/shelter}"
OUTPUT_FILE="${OUTPUT_DIR}/tokyo_shelter.geojson"

mkdir -p "${OUTPUT_DIR}"

if [[ ! -f "${SOURCE_FILE}" ]]; then
  log_error "Local shelter source not found: ${SOURCE_FILE}"
  exit 1
fi

cp "${SOURCE_FILE}" "${OUTPUT_FILE}"
log_info "Shelter raw data staged at ${OUTPUT_FILE}"
log_info "TODO: replace local copy with authoritative download workflow."
