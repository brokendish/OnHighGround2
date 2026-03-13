#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/log.sh"

download_file() {
  if [[ "$#" -ne 2 ]]; then
    log_error "download_file requires <url> <output_path>"
    return 1
  fi

  local url="$1"
  local output_path="$2"

  mkdir -p "$(dirname "${output_path}")"
  log_info "Downloading ${url} -> ${output_path}"
  curl -fL --retry 3 --connect-timeout 10 --output "${output_path}" "${url}"
}
