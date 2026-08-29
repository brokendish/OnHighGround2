#!/usr/bin/env bash
# download_emergency_shelter.sh — 指定緊急避難場所（category 2）取得
# Phase 2-D Round 3（P2D-SHELTER-LEGACY-001、
# tasks/public-release/phase2d_claude_round3_snapshot_remediation_instruction.md 第9.1節）
#
# Phase 2-D Round 2で判明: 国土地理院「指定緊急避難場所・指定避難所データダウンロード
# サイト」（https://hinanmap.gsi.go.jp/）の都道府県別ファイル名末尾の実際の対応は
#   {code}_1.geojson = 指定避難所スキーマ、{code}_2.geojson = 指定緊急避難場所スキーマ
# であり、本scriptが以前前提としていた「_1 = 指定緊急避難場所」とは逆であった。
# 本scriptはRound 2で新設した正本fetch script
# （scripts/download/download_shelter_gsi_prefecture.sh、category=2を指定して呼ぶ）の
# 薄いwrapperとし、legacy local-copy fallback（旧: 開発者ローカルraw folderからのcp）は
# 完全に廃止する。
#
# 使い方:
#   scripts/download/download_emergency_shelter.sh [prefecture_code] [output_dir]
#   例: scripts/download/download_emergency_shelter.sh 13000
#
# 出力:
#   {output_dir}/tokyo_emergency_shelters.geojson
#   {output_dir}/tokyo_emergency_shelters.geojson.sha256
#   {output_dir}/tokyo_emergency_shelters.fetch_metadata.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

CATEGORY="2"  # 指定緊急避難場所（Round 2でGSI公式サイトから実測確認済み）

PREF_CODE="${1:-13000}"
OUTPUT_DIR="${2:-${PROJECT_ROOT}/data_lake/raw/tokyo/emergency_shelters}"

if [[ ! "${PREF_CODE}" =~ ^[0-9]{5}$ ]]; then
    log_error "invalid prefecture code (expected 5 digits, e.g. 13000): ${PREF_CODE}"
    exit 1
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ohg2_emergency_shelter.XXXXXX")"
trap 'rm -rf "${WORK_DIR}"' EXIT

log_info "fetching category=${CATEGORY} (指定緊急避難場所) for prefecture ${PREF_CODE} via download_shelter_gsi_prefecture.sh"
"${SCRIPT_DIR}/download_shelter_gsi_prefecture.sh" "${PREF_CODE}" "${CATEGORY}" "${WORK_DIR}"

FETCHED="${WORK_DIR}/${PREF_CODE}_${CATEGORY}.geojson"
if [[ ! -f "${FETCHED}" ]]; then
    log_error "fetch script did not produce expected output: ${FETCHED}"
    exit 1
fi

# schema検証（fail-closed）: category=2は指定緊急避難場所であり、8種類のhazard flag
# property（洪水・崖崩れ、土石流及び地滑り・高潮・地震・津波・大規模な火事・
# 内水氾濫・火山現象）を全て持つ。誤ってcategory=1（指定避難所）相当のデータが
# 返された場合はこれらのkeyが欠落するため非0終了する。
if ! python3 - "${FETCHED}" <<'PYEOF'
import json
import sys

REQUIRED_HAZARD_FIELDS = [
    "洪水", "崖崩れ、土石流及び地滑り", "高潮", "地震", "津波",
    "大規模な火事", "内水氾濫", "火山現象",
]

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)

if data.get("type") != "FeatureCollection":
    sys.exit(f"unexpected GeoJSON type: {data.get('type')!r}")

features = data.get("features", [])
if not features:
    sys.exit("zero features — refusing to accept an empty emergency-shelter dataset")

props = features[0].get("properties", {})
missing = [k for k in REQUIRED_HAZARD_FIELDS if k not in props]
if missing:
    sys.exit(
        "category=2 schema validation failed (expected 指定緊急避難場所 hazard-flag "
        f"fields, but missing: {missing} — GSI may have reversed its category naming "
        "again; do not accept this data as emergency-shelter content)"
    )

print(f"schema OK: features={len(features)}")
PYEOF
then
    log_error "downloaded data failed category=${CATEGORY} (指定緊急避難場所) schema validation — refusing to publish"
    exit 1
fi

mkdir -p "${OUTPUT_DIR}"
OUTPUT_FILE="${OUTPUT_DIR}/tokyo_emergency_shelters.geojson"

# 一時fileへ確定してからatomic renameで配置する（部分fileを最終pathへ晒さない）。
mv -f "${FETCHED}" "${OUTPUT_FILE}.partial"
mv -f "${OUTPUT_FILE}.partial" "${OUTPUT_FILE}"
[[ -f "${WORK_DIR}/${PREF_CODE}_${CATEGORY}.geojson.sha256" ]] && \
    cp "${WORK_DIR}/${PREF_CODE}_${CATEGORY}.geojson.sha256" "${OUTPUT_FILE}.sha256"
[[ -f "${WORK_DIR}/${PREF_CODE}_${CATEGORY}.fetch_metadata.json" ]] && \
    cp "${WORK_DIR}/${PREF_CODE}_${CATEGORY}.fetch_metadata.json" "${OUTPUT_DIR}/tokyo_emergency_shelters.fetch_metadata.json"

log_info "Emergency shelter data staged at ${OUTPUT_FILE}"
