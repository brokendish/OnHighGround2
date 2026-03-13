#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

INPUT_DIR="${1:-${PROJECT_ROOT}/data_lake/raw}"

log_info "Archive extraction placeholder for ${INPUT_DIR}"
log_info "TODO: support zip, 7z, and tar-based government data packages."
