#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p \
  "${PROJECT_ROOT}/scripts/common" \
  "${PROJECT_ROOT}/scripts/registry" \
  "${PROJECT_ROOT}/scripts/download" \
  "${PROJECT_ROOT}/scripts/extract" \
  "${PROJECT_ROOT}/scripts/normalize" \
  "${PROJECT_ROOT}/scripts/validate" \
  "${PROJECT_ROOT}/scripts/derive" \
  "${PROJECT_ROOT}/scripts/tile_build" \
  "${PROJECT_ROOT}/scripts/publish"

printf 'Initialized script directories under %s\n' "${PROJECT_ROOT}/scripts"
