#!/usr/bin/env bash
set -euo pipefail

timestamp() {
  date +"%Y-%m-%dT%H:%M:%S%z"
}

log_info() {
  printf '[%s] [INFO] %s\n' "$(timestamp)" "$*"
}

log_warn() {
  printf '[%s] [WARN] %s\n' "$(timestamp)" "$*" >&2
}

log_error() {
  printf '[%s] [ERROR] %s\n' "$(timestamp)" "$*" >&2
}
