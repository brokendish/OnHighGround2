#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

SOURCE_DIR="${1:-${PROJECT_ROOT}/data_lake/tiles/tokyo}"
DEST_DIR="${2:-${PROJECT_ROOT}/frontend/hazard}"

mkdir -p "${DEST_DIR}"
log_info "Publish placeholder. Ready to sync ${SOURCE_DIR} -> ${DEST_DIR}"
log_info "TODO: copy or rsync built frontend assets in a later phase."
