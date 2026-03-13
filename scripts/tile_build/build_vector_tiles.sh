#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

INPUT_DIR="${1:-${PROJECT_ROOT}/data_lake/validated/tokyo}"
OUTPUT_DIR="${2:-${PROJECT_ROOT}/data_lake/tiles/tokyo}"

mkdir -p "${OUTPUT_DIR}"
log_info "Vector tile build placeholder. Input=${INPUT_DIR} Output=${OUTPUT_DIR}"
log_info "TODO: build MVT from validated or derived datasets only."
