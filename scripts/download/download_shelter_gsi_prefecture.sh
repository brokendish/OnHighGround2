#!/usr/bin/env bash
# download_shelter_gsi_prefecture.sh — GSI都道府県別 指定緊急避難場所/指定避難所データ取得
# （Phase 2-D Round 2、P2D-HAZARD-PROVENANCE / HAZ-SHELTER対応）
#
# 国土地理院「指定緊急避難場所・指定避難所データダウンロードサイト」
# （https://hinanmap.gsi.go.jp/）の都道府県別GeoJSONを直接取得する。
#
# 重要な発見（Round 2で判明）:
#   このサイトの都道府県別ファイル名末尾（_1 / _2）は、当初
#   scripts/download/download_emergency_shelter.sh・download_shelter.sh が
#   前提としていた対応関係（_1=指定緊急避難場所, _2=指定避難所）とは
#   実際には逆である。2026-08-21時点でGSIから実際に取得・検証した結果:
#     {pref_code}_1.geojson のプロパティ = 指定避難所スキーマ
#       （受入対象者・その他市町村長が必要と認める事項・指定緊急避難場所との住所同一）
#     {pref_code}_2.geojson のプロパティ = 指定緊急避難場所スキーマ
#       （洪水・崖崩れ、土石流及び地滑り・高潮・地震・津波・大規模な火事・
#         内水氾濫・火山現象・指定避難所との住所同一）
#   既存の tracked artifact
#   （data_runtime/backend/shelters/tokyo_emergency_evacuation_sites.geojson）の
#   スキーマは後者（指定緊急避難場所）と一致するため、本scriptは既定で
#   category=2 を取得する。GSI側の命名規則が将来変わる可能性があるため、
#   取得後は必ずスキーマ（プロパティキー集合）を確認すること。
#
# 使い方:
#   scripts/download/download_shelter_gsi_prefecture.sh <pref_code> <category> <output_dir>
#   例: scripts/download/download_shelter_gsi_prefecture.sh 13000 2 /tmp/gsi_shelter
#
# 出力:
#   {output_dir}/{pref_code}_{category}.geojson
#   {output_dir}/{pref_code}_{category}.geojson.sha256
#   {output_dir}/{pref_code}_{category}.fetch_metadata.json
#
# 公式利用条件: https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html
#              https://www.gsi.go.jp/bousaichiri/hinanbasho-menseki.html
#   （「ご利用上の注意」に同意した場合のみ利用可。最新かつ詳細な状況は
#     必ず当該市町村に確認すること。データは随時更新される。）

set -euo pipefail

PREF_CODE="${1:?prefecture code required (例: 13000)}"
CATEGORY="${2:?category required (1 or 2)}"
OUTPUT_DIR="${3:?output directory required}"

if [[ "${CATEGORY}" != "1" && "${CATEGORY}" != "2" ]]; then
    echo "ERROR: category must be 1 or 2" >&2
    exit 1
fi

BASE_URL="https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/geoJSON"
FILENAME="${PREF_CODE}_${CATEGORY}.geojson"
URL="${BASE_URL}/${FILENAME}"
USER_AGENT="OnHighGround2/1.0 (project-data-provisioning)"

mkdir -p "${OUTPUT_DIR}"
OUT_FILE="${OUTPUT_DIR}/${FILENAME}"
HEADERS_FILE="${OUTPUT_DIR}/${FILENAME}.headers.txt"

FETCH_TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

HTTP_STATUS=$(curl -sL --max-time 60 -A "${USER_AGENT}" \
    -D "${HEADERS_FILE}" \
    -o "${OUT_FILE}" \
    -w "%{http_code}" \
    "${URL}")

if [[ "${HTTP_STATUS}" != "200" ]]; then
    echo "ERROR: HTTP ${HTTP_STATUS} fetching ${URL}" >&2
    rm -f "${OUT_FILE}"
    exit 1
fi

# content-type / 最低限のGeoJSON構造検証（fail-closed）
if ! python3 -c "
import json, sys
with open('${OUT_FILE}', encoding='utf-8') as f:
    data = json.load(f)
assert data.get('type') == 'FeatureCollection', 'not a FeatureCollection'
assert len(data.get('features', [])) > 0, 'zero features'
print(f'features={len(data[\"features\"])}')
"; then
    echo "ERROR: downloaded file failed structural validation (fail-closed, not accepting)" >&2
    exit 1
fi

SHA256=$(shasum -a 256 "${OUT_FILE}" | awk '{print $1}')
echo "${SHA256}" > "${OUT_FILE}.sha256"

CONTENT_LENGTH=$(grep -i '^content-length:' "${HEADERS_FILE}" | tr -d '\r' | awk '{print $2}' || echo "")
ACTUAL_BYTES=$(wc -c < "${OUT_FILE}" | tr -d ' ')

cat > "${OUTPUT_DIR}/${PREF_CODE}_${CATEGORY}.fetch_metadata.json" <<EOF
{
  "source_url": "${URL}",
  "fetch_timestamp_utc": "${FETCH_TS}",
  "http_status": ${HTTP_STATUS},
  "content_length_header": "${CONTENT_LENGTH}",
  "actual_bytes": ${ACTUAL_BYTES},
  "sha256": "${SHA256}",
  "official_terms_pages": [
    "https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html",
    "https://www.gsi.go.jp/bousaichiri/hinanbasho-menseki.html"
  ]
}
EOF

echo "OK: ${OUT_FILE} (${ACTUAL_BYTES} bytes, sha256=${SHA256})"
