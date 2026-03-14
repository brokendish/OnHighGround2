#!/usr/bin/env bash
set -euo pipefail

# Legacy filename retained for compatibility. Canonical data category is flood.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

OUTPUT_DIR="${1:-${PROJECT_ROOT}/data_lake/raw/tokyo/flood}"

mkdir -p "${OUTPUT_DIR}"
log_info "Flood download placeholder. Output directory prepared at ${OUTPUT_DIR}"
log_info "TODO: wire authoritative Tokyo flood sources into raw storage."
