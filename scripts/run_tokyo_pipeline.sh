#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

log_info "Initializing Tokyo data lake and script directories"
"${PROJECT_ROOT}/init_data_lake.sh"
"${PROJECT_ROOT}/init_scripts.sh"

log_info "Step 1/4: registry check"
python3 "${PROJECT_ROOT}/scripts/registry/check_registry.py" \
  --registry "${PROJECT_ROOT}/data_lake/registry/tokyo_hazard_registry.csv"

log_info "Step 2/4: shelter download"
"${PROJECT_ROOT}/scripts/download/download_shelter.sh" \
  "${PROJECT_ROOT}/data_lake/raw/tokyo/shelter"

log_info "Step 3/4: shelter normalize"
python3 "${PROJECT_ROOT}/scripts/normalize/normalize_shelter.py" \
  --input "${PROJECT_ROOT}/data_lake/raw/tokyo/shelter/tokyo_shelter.geojson" \
  --output "${PROJECT_ROOT}/data_lake/normalized/tokyo/shelter/tokyo_shelter.geojson"

log_info "Step 4/4: shelter geometry validate"
python3 "${PROJECT_ROOT}/scripts/validate/validate_geometry.py" \
  --input "${PROJECT_ROOT}/data_lake/normalized/tokyo/shelter/tokyo_shelter.geojson" \
  --output "${PROJECT_ROOT}/data_lake/validated/tokyo/shelter/tokyo_shelter.geojson"

log_info "Tokyo pipeline completed successfully"
