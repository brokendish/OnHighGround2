#!/usr/bin/env bash
# deploy_to_runtime.sh
# data_lake から data_runtime へ必要なデータを配備する publish ステップ。
#
# 用途:
#   data_lake/validated/ (または normalized/) の成果物を data_runtime/ にコピーし、
#   backend / frontend が直接参照できる状態にする。
#
# 使い方:
#   scripts/publish/deploy_to_runtime.sh [--region tokyo] [--dry-run] [--skip-frontend]
#
# オプション:
#   --region REGION      対象地域 (デフォルト: tokyo)
#   --dry-run            実際のコピーは行わず、対象ファイルを表示するのみ
#   --skip-frontend      frontend/layers と frontend/tiles の配備をスキップ

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

# --- 引数パース ---
REGION="tokyo"
DRY_RUN=false
SKIP_FRONTEND=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)        REGION="$2"; shift 2 ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --skip-frontend) SKIP_FRONTEND=true; shift ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

# --- ディレクトリ定義 ---
DATA_LAKE="${PROJECT_ROOT}/data_lake"
DATA_RUNTIME="${PROJECT_ROOT}/data_runtime"
MANIFESTS_DIR="${DATA_RUNTIME}/manifests"

VALIDATED="${DATA_LAKE}/validated/${REGION}"
NORMALIZED="${DATA_LAKE}/normalized/${REGION}"
TILES="${DATA_LAKE}/tiles/${REGION}"

RUNTIME_BACKEND="${DATA_RUNTIME}/backend"
RUNTIME_FRONTEND_LAYERS="${DATA_RUNTIME}/frontend/layers"
RUNTIME_FRONTEND_TILES="${DATA_RUNTIME}/frontend/tiles/${REGION}"
FRONTEND_LAYERS_DIR="${PROJECT_ROOT}/frontend/layers"

TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="${MANIFESTS_DIR}/deploy_${TIMESTAMP}.log"

mkdir -p "${MANIFESTS_DIR}"

log_info "=== deploy_to_runtime.sh ==="
log_info "Region        : ${REGION}"
log_info "DryRun        : ${DRY_RUN}"
log_info "SkipFrontend  : ${SKIP_FRONTEND}"
log_info "Source        : ${DATA_LAKE}"
log_info "Target        : ${DATA_RUNTIME}"

# --- 追跡用配列 ---
BACKEND_FILES=()
FRONTEND_LAYERS=()
FRONTEND_TILES=()
SKIPPED_FILES=()
MISSING_FILES=()

# --- コピーヘルパー ---
deploy_file() {
    local src="$1"
    local dst="$2"
    local category="${3:-backend}"
    local dst_dir
    dst_dir="$(dirname "${dst}")"

    if [[ ! -f "${src}" ]]; then
        log_warn "Source not found (skip): ${src}"
        echo "SKIP\t${src}" >> "${LOG_FILE}"
        MISSING_FILES+=("${src}")
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

    case "${category}" in
        backend)          BACKEND_FILES+=("${dst}") ;;
        frontend_layers)  FRONTEND_LAYERS+=("${dst}") ;;
        frontend_tiles)   FRONTEND_TILES+=("${dst}") ;;
    esac
}

deploy_dir() {
    local src_dir="$1"
    local dst_dir="$2"
    local pattern="${3:-*.geojson}"
    local category="${4:-backend}"

    if [[ ! -d "${src_dir}" ]]; then
        log_warn "Source dir not found (skip): ${src_dir}"
        echo "SKIP_DIR\t${src_dir}" >> "${LOG_FILE}"
        SKIPPED_FILES+=("${src_dir}")
        return
    fi

    local found=false
    while IFS= read -r -d '' src_file; do
        found=true
        local rel="${src_file#${src_dir}/}"
        deploy_file "${src_file}" "${dst_dir}/${rel}" "${category}"
    done < <(find "${src_dir}" -name "${pattern}" -print0 2>/dev/null)

    if ! "${found}"; then
        log_warn "No files matched '${pattern}' in ${src_dir}"
        SKIPPED_FILES+=("${src_dir}/${pattern}")
    fi
}

echo "deploy_to_runtime.sh started at ${TIMESTAMP}" > "${LOG_FILE}"
echo "region=${REGION} dry_run=${DRY_RUN} skip_frontend=${SKIP_FRONTEND}" >> "${LOG_FILE}"

# ─── backend: elevation (DEM) ─────────────────────────────────────────────────
log_info "--- DEM ---"
deploy_file \
    "${VALIDATED}/dem/elevation.tif" \
    "${RUNTIME_BACKEND}/elevation/elevation.tif" \
    "backend"

# ─── backend: hazard / flood ──────────────────────────────────────────────────
log_info "--- flood ---"
deploy_file \
    "${NORMALIZED}/flood/tokyo_flood_check.geojsonl" \
    "${RUNTIME_BACKEND}/hazard/flood/tokyo_flood_check.geojsonl" \
    "backend"

# ─── backend: hazard / storm_surge ───────────────────────────────────────────
log_info "--- storm_surge ---"
deploy_file \
    "${NORMALIZED}/storm_surge/tokyo_storm_surge.geojson" \
    "${RUNTIME_BACKEND}/hazard/storm_surge/tokyo_storm_surge.geojson" \
    "backend"

# ─── backend: hazard / tsunami ────────────────────────────────────────────────
log_info "--- tsunami ---"
for target in tokyo kanagawa chiba; do
    filename="tsunami_${target}.geojson"
    # validated を優先、なければ normalized
    if [[ -f "${VALIDATED}/tsunami/${filename}" ]]; then
        deploy_file \
            "${VALIDATED}/tsunami/${filename}" \
            "${RUNTIME_BACKEND}/hazard/tsunami/${filename}" \
            "backend"
    else
        deploy_file \
            "${NORMALIZED}/tsunami/${filename}" \
            "${RUNTIME_BACKEND}/hazard/tsunami/${filename}" \
            "backend"
    fi
done

# ─── backend: hazard / inland_flood ──────────────────────────────────────────
# normalized/ を正規参照先とする。未配置の場合は legacy sample にフォールバック。
# 正規化: python scripts/normalize/normalize_inland_flood.py
log_info "--- inland_flood ---"
if [[ -d "${NORMALIZED}/inland_flood" ]] && compgen -G "${NORMALIZED}/inland_flood/*.geojson" > /dev/null 2>&1; then
    # デプロイ前に既存 GeoJSON を削除（旧ファイル名が残ってアルファベット順で誤選択されるのを防ぐ）
    if ! "${DRY_RUN}" && [[ -d "${RUNTIME_BACKEND}/hazard/inland_flood" ]]; then
        find "${RUNTIME_BACKEND}/hazard/inland_flood" -maxdepth 1 -name "*.geojson" -delete
        log_info "Cleared stale GeoJSON from ${RUNTIME_BACKEND}/hazard/inland_flood"
    fi
    deploy_dir \
        "${NORMALIZED}/inland_flood" \
        "${RUNTIME_BACKEND}/hazard/inland_flood" \
        "*.geojson" \
        "backend"
else
    log_warn "inland_flood normalized data not found — deploying legacy sample"
    deploy_file \
        "${PROJECT_ROOT}/data/hazard/inland_flood_sample.geojson" \
        "${RUNTIME_BACKEND}/hazard/inland_flood/inland_flood_sample.geojson" \
        "backend"
fi

# ─── backend: hazard / landslide (Phase 4 sample) ────────────────────────────
log_info "--- landslide (Phase 4 sample) ---"
deploy_file \
    "${PROJECT_ROOT}/data/hazard/landslide_sample.geojson" \
    "${RUNTIME_BACKEND}/hazard/landslide/landslide_sample.geojson" \
    "backend"

# ─── backend: shelters ────────────────────────────────────────────────────────
log_info "--- shelters ---"
deploy_dir "${VALIDATED}/shelter" "${RUNTIME_BACKEND}/shelters" "*.geojson" "backend"
deploy_dir "${VALIDATED}/shelter" "${RUNTIME_BACKEND}/shelters" "*.csv"     "backend"

# ─── frontend 配備 ─────────────────────────────────────────────────────────────
if "${SKIP_FRONTEND}"; then
    log_info "--- frontend: skipped (--skip-frontend) ---"
else
    # ── frontend: layers (GeoJSON fallback 用) ────────────────────────────────
    # Martin vector tiles が主配信。GeoJSON はベクタータイル未整備時のフォールバック。
    # 対象: storm_surge, tsunami_tokyo（表示速度が比較的速いもの）
    # 注意: flood_max.geojson (138 MB+) はサイズが大きいため明示的に除外。
    log_info "--- frontend layers ---"
    mkdir -p "${RUNTIME_FRONTEND_LAYERS}"

    deploy_file \
        "${NORMALIZED}/storm_surge/tokyo_storm_surge.geojson" \
        "${RUNTIME_FRONTEND_LAYERS}/tokyo_storm_surge.geojson" \
        "frontend_layers"

    # tsunami: tokyo のみ（kanagawa/chiba はサイズ大のため除外）
    deploy_file \
        "${NORMALIZED}/tsunami/tsunami_tokyo.geojson" \
        "${RUNTIME_FRONTEND_LAYERS}/tsunami_tokyo.geojson" \
        "frontend_layers"

    # flood fallback: normalized の軽量 GeoJSON が存在する場合のみ
    if [[ -f "${NORMALIZED}/flood/tokyo_flood_max.geojson" ]]; then
        deploy_file \
            "${NORMALIZED}/flood/tokyo_flood_max.geojson" \
            "${RUNTIME_FRONTEND_LAYERS}/tokyo_flood_max.geojson" \
            "frontend_layers"
    fi

    # inland_flood: normalized を優先、未配置なら legacy sample
    if [[ -d "${NORMALIZED}/inland_flood" ]] && compgen -G "${NORMALIZED}/inland_flood/*.geojson" > /dev/null 2>&1; then
        # 複数ファイルがある場合は最初のものを inland_flood_tokyo.geojson として配備
        _if_src="$(find "${NORMALIZED}/inland_flood" -maxdepth 1 -name "*.geojson" | sort | head -1)"
        deploy_file "${_if_src}" "${RUNTIME_FRONTEND_LAYERS}/inland_flood_tokyo.geojson" "frontend_layers"
    else
        deploy_file \
            "${PROJECT_ROOT}/data/hazard/inland_flood_sample.geojson" \
            "${RUNTIME_FRONTEND_LAYERS}/inland_flood_tokyo.geojson" \
            "frontend_layers"
    fi
    deploy_file \
        "${PROJECT_ROOT}/data/hazard/landslide_sample.geojson" \
        "${RUNTIME_FRONTEND_LAYERS}/landslide_tokyo.geojson" \
        "frontend_layers"

    # ── frontend: tiles (Martin が使用する .mbtiles) ──────────────────────────
    # data_lake/tiles/{region}/ → data_runtime/frontend/tiles/{region}/
    log_info "--- frontend tiles ---"
    mkdir -p "${RUNTIME_FRONTEND_TILES}"

    for hazard_type in flood tsunami storm_surge urban_flood; do
        TILE_SRC="${TILES}/${hazard_type}"
        TILE_DST="${RUNTIME_FRONTEND_TILES}/${hazard_type}"
        if [[ -d "${TILE_SRC}" ]]; then
            deploy_dir "${TILE_SRC}" "${TILE_DST}" "*.mbtiles" "frontend_tiles"
        else
            log_warn "Tile dir not found (skip): ${TILE_SRC}"
            SKIPPED_FILES+=("${TILE_SRC}")
        fi
    done

    # ── frontend/layers へ同期 ─────────────────────────────────────────────────
    # data_runtime/frontend/layers/ → frontend/layers/ (nginx が /layers/ として配信)
    log_info "--- sync frontend/layers ---"
    if [[ -d "${RUNTIME_FRONTEND_LAYERS}" ]]; then
        mkdir -p "${FRONTEND_LAYERS_DIR}"
        if "${DRY_RUN}"; then
            log_info "[dry-run] rsync ${RUNTIME_FRONTEND_LAYERS}/ -> ${FRONTEND_LAYERS_DIR}/"
        else
            # rsync が使えない環境でも cp で代替
            if command -v rsync &>/dev/null; then
                rsync -a --ignore-existing "${RUNTIME_FRONTEND_LAYERS}/" "${FRONTEND_LAYERS_DIR}/"
            else
                find "${RUNTIME_FRONTEND_LAYERS}" -name "*.geojson" -print0 |
                    while IFS= read -r -d '' f; do
                        dst="${FRONTEND_LAYERS_DIR}/$(basename "${f}")"
                        [[ -f "${dst}" ]] || cp "${f}" "${dst}"
                    done
            fi
            log_info "Synced: ${RUNTIME_FRONTEND_LAYERS}/ -> ${FRONTEND_LAYERS_DIR}/"
        fi
    else
        log_warn "data_runtime/frontend/layers/ not found — skipping sync to frontend/layers/"
    fi
fi

# ─── manifest: latest.json ─────────────────────────────────────────────────────
LATEST_JSON="${MANIFESTS_DIR}/latest.json"
log_info "Writing manifest: ${LATEST_JSON}"

if ! "${DRY_RUN}"; then
    # JSON 配列ヘルパー
    _json_array() {
        local arr=("$@")
        local out="["
        local first=true
        for item in "${arr[@]+"${arr[@]}"}"; do
            "${first}" || out+=","
            out+="\"${item}\""
            first=false
        done
        out+="]"
        echo "${out}"
    }

    cat > "${LATEST_JSON}" <<JSON
{
  "region": "${REGION}",
  "deployed_at": "${TIMESTAMP}",
  "backend_files": $(_json_array "${BACKEND_FILES[@]+"${BACKEND_FILES[@]}"}"),
  "frontend_layers": $(_json_array "${FRONTEND_LAYERS[@]+"${FRONTEND_LAYERS[@]}"}"),
  "frontend_tiles": $(_json_array "${FRONTEND_TILES[@]+"${FRONTEND_TILES[@]}"}"),
  "skipped_files": $(_json_array "${SKIPPED_FILES[@]+"${SKIPPED_FILES[@]}"}"),
  "missing_files": $(_json_array "${MISSING_FILES[@]+"${MISSING_FILES[@]}"}")
}
JSON
fi

log_info "=== deploy_to_runtime.sh done ==="
log_info "Log : ${LOG_FILE}"
log_info "Manifest: ${LATEST_JSON}"
