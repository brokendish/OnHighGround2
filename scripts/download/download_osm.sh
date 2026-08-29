#!/usr/bin/env bash
set -euo pipefail

# Phase 2-D Round 2 (P2D-AT17-BOOTSTRAP): このscriptは以前
# "OSM download placeholder... TODO: fetch Tokyo extract..." という
# no-op プレースホルダーだった。実際にfail-closedで機能する
# scripts/download/download_osm_provision.py（Python、HTTPS domain allowlist・
# checksum検証・atomic write・manifest記録を実装）へ委譲する。
#
# region引数は必須（既定値なし、指示書第11.3節「既定値を設定する場合は
# 小規模なdocumented demoだけとする」に対応するため、暗黙の全国downloadは行わない）。
#
# 使い方:
#   scripts/download/download_osm.sh <region> [output_path]
#   例: scripts/download/download_osm.sh kanto data_lake/raw/tokyo/osm/kanto-latest.osm.pbf
#   利用可能なregion一覧: scripts/download/download_osm.sh --list-regions

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

if [[ "${1:-}" == "--list-regions" ]]; then
  python3 "${SCRIPT_DIR}/download_osm_provision.py" --list-regions
  exit 0
fi

if [[ $# -lt 1 ]]; then
  log_error "region引数が必要です（既定値なし）。利用可能なregionは --list-regions で確認できます。"
  exit 1
fi

REGION="$1"
OUTPUT_PATH="${2:-${PROJECT_ROOT}/data_lake/raw/tokyo/osm/${REGION}-latest.osm.pbf}"

log_info "OSM provisioning: region=${REGION} output=${OUTPUT_PATH}"
python3 "${SCRIPT_DIR}/download_osm_provision.py" --region "${REGION}" --output "${OUTPUT_PATH}"
