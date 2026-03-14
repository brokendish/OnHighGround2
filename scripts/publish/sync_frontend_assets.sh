#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

SOURCE_DIR="${1:-${PROJECT_ROOT}/data_lake/tiles/tokyo}"
DEST_DIR="${2:-${PROJECT_ROOT}/frontend/hazard}"

mkdir -p "${DEST_DIR}"
log_info "Publish placeholder. Ready to sync canonical tiles ${SOURCE_DIR} -> legacy frontend path ${DEST_DIR}"
log_info "TODO: keep frontend/hazard as a temporary compatibility target while data_lake/tiles becomes the sole delivery source."
