#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

OUTPUT_DIR="${1:-${PROJECT_ROOT}/data_lake/raw/tokyo/osm}"

mkdir -p "${OUTPUT_DIR}"
log_info "OSM download placeholder. Output directory prepared at ${OUTPUT_DIR}"
log_info "TODO: fetch Tokyo extract and build routing graph in a later phase."
