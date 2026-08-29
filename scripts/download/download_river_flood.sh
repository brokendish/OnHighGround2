#!/usr/bin/env bash
set -euo pipefail

# Legacy filename retained for compatibility. Canonical data category is flood.
#
# Phase 2-D Round 2 (P2D-AT17-BOOTSTRAP): このscriptは以前
# "Flood download placeholder... TODO: wire authoritative Tokyo flood sources..."
# というno-opプレースホルダーだった。
#
# 国土数値情報（KSJ）A31a/A31bのdistributionはHTMLフォーム送信を要し、
# 安定した直接download URLが確認できなかった（詳細は
# scripts/download/import_river_flood_manual.py のdocstring参照）。
# そのため本scriptはfake downloadを実装せず、operatorが
# https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html から
# 手動でダウンロードしたZIPをfail-closedで検証・importする
# scripts/download/import_river_flood_manual.py へ委譲する。
#
# 使い方:
#   scripts/download/download_river_flood.sh <manually_downloaded_zip> <prefecture_code> [output_dir]
#   例: scripts/download/download_river_flood.sh ~/Downloads/A31a-25_13_GML.zip 13

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

if [[ $# -lt 2 ]]; then
  log_error "使い方: $0 <manually_downloaded_zip> <prefecture_code> [output_dir]"
  log_error "国土数値情報A31は自動取得不能のため、公式サイトから手動ダウンロードしたZIPを指定してください:"
  log_error "  https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html"
  exit 1
fi

INPUT_ZIP="$1"
PREF_CODE="$2"
OUTPUT_DIR="${3:-${PROJECT_ROOT}/data_lake/raw/tokyo/flood}"

log_info "River flood manual import: input=${INPUT_ZIP} prefecture=${PREF_CODE} output_dir=${OUTPUT_DIR}"
python3 "${SCRIPT_DIR}/import_river_flood_manual.py" --input "${INPUT_ZIP}" --prefecture-code "${PREF_CODE}" --output-dir "${OUTPUT_DIR}"
