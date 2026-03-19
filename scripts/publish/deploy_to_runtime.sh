#!/usr/bin/env bash
# deploy_to_runtime.sh
# data_lake から data_runtime へ必要なデータを配備する publish ステップ。
#
# 用途:
#   data_lake/validated/ (または normalized/) の成果物を data_runtime/ にコピーし、
#   backend / frontend が直接参照できる状態にする。
#
# 使い方:
#   scripts/publish/deploy_to_runtime.sh [--region tokyo] [--dry-run]
#
# オプション:
#   --region REGION   対象地域 (デフォルト: tokyo)
#   --dry-run         実際のコピーは行わず、対象ファイルを表示するのみ

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

# --- 引数パース ---
REGION="tokyo"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region) REGION="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

# --- ディレクトリ定義 ---
DATA_LAKE="${PROJECT_ROOT}/data_lake"
DATA_RUNTIME="${PROJECT_ROOT}/data_runtime"
MANIFESTS_DIR="${DATA_RUNTIME}/manifests"

VALIDATED="${DATA_LAKE}/validated/${REGION}"
NORMALIZED="${DATA_LAKE}/normalized/${REGION}"

RUNTIME_BACKEND="${DATA_RUNTIME}/backend"
RUNTIME_FRONTEND_LAYERS="${DATA_RUNTIME}/frontend/layers"

TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="${MANIFESTS_DIR}/deploy_${TIMESTAMP}.log"

mkdir -p "${MANIFESTS_DIR}"

log_info "=== deploy_to_runtime.sh ==="
log_info "Region : ${REGION}"
log_info "DryRun : ${DRY_RUN}"
log_info "Source : ${DATA_LAKE}"
log_info "Target : ${DATA_RUNTIME}"

# --- コピーヘルパー ---
deploy_file() {
    local src="$1"
    local dst="$2"
    local dst_dir
    dst_dir="$(dirname "${dst}")"

    if [[ ! -f "${src}" ]]; then
        log_warn "Source not found (skip): ${src}"
        echo "SKIP\t${src}" >> "${LOG_FILE}"
        return
    fi

    if "${DRY_RUN}"; then
        log_info "[dry-run] cp ${src} -> ${dst}"
        echo "DRY\t${src}\t${dst}" >> "${LOG_FILE}"
        return
    fi

    mkdir -p "${dst_dir}"
    cp "${src}" "${dst}"
    log_info "Deployed: $(basename "${src}") -> ${dst}"
    echo "OK\t${src}\t${dst}" >> "${LOG_FILE}"
}

deploy_dir() {
    local src_dir="$1"
    local dst_dir="$2"
    local pattern="${3:-*.geojson}"

    if [[ ! -d "${src_dir}" ]]; then
        log_warn "Source dir not found (skip): ${src_dir}"
        echo "SKIP_DIR\t${src_dir}" >> "${LOG_FILE}"
        return
    fi

    while IFS= read -r -d '' src_file; do
        local rel="${src_file#${src_dir}/}"
        deploy_file "${src_file}" "${dst_dir}/${rel}"
    done < <(find "${src_dir}" -name "${pattern}" -print0 2>/dev/null)
}

echo "deploy_to_runtime.sh started at ${TIMESTAMP}" > "${LOG_FILE}"
echo "region=${REGION} dry_run=${DRY_RUN}" >> "${LOG_FILE}"

# ─── backend: elevation (DEM) ─────────────────────────────────────────────────
log_info "--- DEM ---"
deploy_file \
    "${VALIDATED}/dem/elevation.tif" \
    "${RUNTIME_BACKEND}/elevation/elevation.tif"

# ─── backend: hazard / flood ──────────────────────────────────────────────────
log_info "--- flood ---"
deploy_file \
    "${NORMALIZED}/flood/tokyo_flood_check.geojsonl" \
    "${RUNTIME_BACKEND}/hazard/flood/tokyo_flood_check.geojsonl"

# ─── backend: hazard / storm_surge ───────────────────────────────────────────
log_info "--- storm_surge ---"
deploy_file \
    "${NORMALIZED}/storm_surge/tokyo_storm_surge.geojson" \
    "${RUNTIME_BACKEND}/hazard/storm_surge/tokyo_storm_surge.geojson"

# ─── backend: hazard / tsunami ────────────────────────────────────────────────
log_info "--- tsunami ---"
for target in tokyo kanagawa chiba; do
    filename="tsunami_${target}.geojson"
    # validated を優先、なければ normalized
    if [[ -f "${VALIDATED}/tsunami/${filename}" ]]; then
        deploy_file \
            "${VALIDATED}/tsunami/${filename}" \
            "${RUNTIME_BACKEND}/hazard/tsunami/${filename}"
    else
        deploy_file \
            "${NORMALIZED}/tsunami/${filename}" \
            "${RUNTIME_BACKEND}/hazard/tsunami/${filename}"
    fi
done

# ─── backend: shelters ────────────────────────────────────────────────────────
log_info "--- shelters ---"
deploy_dir \
    "${VALIDATED}/shelter" \
    "${RUNTIME_BACKEND}/shelters" \
    "*.geojson"
deploy_dir \
    "${VALIDATED}/shelter" \
    "${RUNTIME_BACKEND}/shelters" \
    "*.csv"

# ─── frontend: layers (fallback GeoJSON for /layers/) ─────────────────────────
# TODO: Phase 2 で tippecanoe → Martin 配信が整備されたら、このコピーは廃止予定。
# 現時点では frontend/hazard/ の代替として data_runtime/frontend/layers/ に配置し、
# さらに frontend/layers/ へシンボリックリンクまたはコピーで配信する。
log_info "--- frontend layers (GeoJSON fallback) ---"
log_info "(Phase 1: frontend/layers/ は空のままでよい。Martin vector tiles が主配信。)"
log_info "(Phase 2 以降: data_runtime/frontend/layers/ → frontend/layers/ へ同期する)"

# ─── manifest: latest.json ────────────────────────────────────────────────────
LATEST_JSON="${MANIFESTS_DIR}/latest.json"
log_info "Writing manifest: ${LATEST_JSON}"

if ! "${DRY_RUN}"; then
    {
        echo "{"
        echo "  \"deployed_at\": \"${TIMESTAMP}\","
        echo "  \"region\": \"${REGION}\","
        echo "  \"files\": ["
        first=true
        while IFS=$'\t' read -r status src dst; do
            [[ "${status}" == "OK" ]] || continue
            if ! "${first}"; then echo "    ,"; fi
            echo "    {\"src\": \"${src}\", \"dst\": \"${dst}\"}"
            first=false
        done < "${LOG_FILE}"
        echo "  ]"
        echo "}"
    } > "${LATEST_JSON}"
fi

log_info "=== deploy_to_runtime.sh done ==="
log_info "Log: ${LOG_FILE}"
