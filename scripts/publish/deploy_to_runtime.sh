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
# operator container内ではscripts/が/scriptsへmountされるため、ここで
# PROJECT_ROOTは"/"に解決される。以降"${PROJECT_ROOT}/xxx"の連結が常に
# 二重先頭slash"//xxx"になるのを防ぐ（deploy_to_runtime_atomic.shの同名
# 対処と同じ理由。詳細はそちらのコメント参照）。
PROJECT_ROOT="${PROJECT_ROOT%/}"
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

# Phase 2-B.5限定修正（CODEX P2B5-CX-002対応）: 「直接cp/in-place更新が
# runtime publish成功経路として残っている」ことが実装FAILとして指摘された。
# OHG2_STAGING_ROOT未設定での実書込（--dry-run以外）は、稼働中currentへの
# 直接cp／stale file deleteという非atomicな成功経路になるため、明示的に
# fail-closedとする。実運用は必ず scripts/publish/deploy_to_runtime_atomic.sh
# （OHG2_STAGING_ROOTを設定してこのscriptを呼ぶwrapper）を経由すること。
if [[ -z "${OHG2_STAGING_ROOT:-}" ]] && ! "${DRY_RUN}"; then
    log_error "OHG2_STAGING_ROOT が未設定です。data_runtimeへの直接書込（非atomic）は禁止されています。"
    log_error "scripts/publish/deploy_to_runtime_atomic.sh 経由で実行するか、--dry-run を指定してください。"
    exit 1
fi
DATA_RUNTIME="${OHG2_STAGING_ROOT:-${PROJECT_ROOT}/data_runtime}"
# manifestsは常にdata_runtime直下（非versioned運用領域）に書く。
MANIFESTS_DIR="${PROJECT_ROOT}/data_runtime/manifests"

VALIDATED="${DATA_LAKE}/validated/${REGION}"
NORMALIZED="${DATA_LAKE}/normalized/${REGION}"
TILES="${DATA_LAKE}/tiles/${REGION}"

RUNTIME_BACKEND="${DATA_RUNTIME}/backend"
RUNTIME_FRONTEND="${DATA_RUNTIME}/frontend"
RUNTIME_FRONTEND_LAYERS="${RUNTIME_FRONTEND}/layers"
RUNTIME_FRONTEND_TILES="${RUNTIME_FRONTEND}/tiles/${REGION}"
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

# HAZARD-META-TILESET-READ-PERMISSION-GAP修復: frontend runtime directory
# （backend-publicがhazard meta API（GET /api/hazards/{type}/{region}/meta）
# のtileset解決のためtraverse/list/readする唯一のpublic-readable
# data_runtime subtree）は、operator主体で作成される際、実行者のprimary
# group（ohg2operator, GID 10002）のままgroup driftしうる（実機調査で
# 発見: /data_runtime/frontendのみgroup=ohg2operatorのまま取り残され、
# backend-publicがtraverse不能→meta APIが500になっていた。兄弟の
# layers/tilesは既にgroup=ohg2leasesで正しかった）。leases gid（20001、
# backend-publicのsupplemental groupかつlayers/tiles/versions/logs等の
# 既存確立contract）へ明示的に揃え、backend-publicのtraverse契約を
# publishのたびに恒久的に維持する（owner/modeは変更しない——既存の
# operator uid・0750契約はそのまま、write権限もbackend-publicへは付与
# しない）。chgrp/chmod失敗は致命的としない（既存contractのままでも
# 直後の処理は継続できるため、警告のみでpublish自体は止めない）。
RUNTIME_FRONTEND_LEASES_GID="${OHG2_LEASES_GID:-20001}"
mkdir -p "${RUNTIME_FRONTEND}"
chgrp "${RUNTIME_FRONTEND_LEASES_GID}" "${RUNTIME_FRONTEND}" 2>/dev/null || \
    log_warn "frontend root directoryのgroup正規化に失敗（gid=${RUNTIME_FRONTEND_LEASES_GID}）: ${RUNTIME_FRONTEND}"
chmod 0750 "${RUNTIME_FRONTEND}" 2>/dev/null || \
    log_warn "frontend root directoryのmode正規化に失敗: ${RUNTIME_FRONTEND}"

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

# ─── backend: hazard / flood, storm_surge, pseudo_inland_flood（registry-resolved） ──
# Dual Storage Remediation Phase C1（ATOMIC-PUBLISH-COVERAGE-GAP）: 従来ここは
# 旧underscore命名（${REGION}_flood_check.geojsonl、${REGION}_storm_surge.geojson）を
# ハードコードしてdeploy_fileしていたが、admin dataset pipelineが実際に生成する
# validated artifactはhyphen/registry命名（例: tokyo-river-001.geojson、
# tokyo-surge-001.geojson）であるため常にSource not foundでsilent skipしており、
# atomic publish（data_runtime/current/backend/hazard/）にflood/storm_surgeが
# 一度も反映されていなかった（実機調査で確認済み）。pseudo_inland_flood に
# 至ってはbackend deploy対応がこのscriptに一度も追加されていなかった。
# resolve_hazard_sources.py（resolve_shelter_sources.pyと同じ設計思想）で
# registry（active_mappings.json + dataset_definitions.json + DatasetState）
# からsourceを動的に解決する。destinationはbackend/hazard/{type}/{region}/{file}
# という既存versioned hazard構造（tsunami/inland_flood/landslide/
# lowland_poor_drainageが既に使っている構造）に合わせる。
#
# 「activeなのにsourceが解決できない」場合はresolverがfail-closedで即座に
# 失敗する（今回のremediation対象そのものである「サイレントスキップ」を
# 再発させないため）。resolverはprocess substitutionではなく明示的な
# exit code検査で失敗を検出する（`< <(...)` はサブシェルの終了コードを
# 呼び出し元へ伝播しないため）。
log_info "--- flood / storm_surge / pseudo_inland_flood (registry-resolved) ---"
_hazard_gap_resolve_output="$(mktemp)"
trap 'rm -f "${_hazard_gap_resolve_output}"' RETURN EXIT
if ! python3 "${SCRIPT_DIR}/resolve_hazard_sources.py" \
        --region "${REGION}" \
        --layer-type flood \
        --layer-type storm_surge \
        --layer-type pseudo_inland_flood \
        > "${_hazard_gap_resolve_output}"; then
    log_error "hazard source resolver (flood/storm_surge/pseudo_inland_flood) が失敗しました（region=${REGION}）"
    exit 1
fi
_hazard_gap_resolved_count=0
while IFS=$'\t' read -r _hz_layer_type _hz_dataset_id _hz_src_path; do
    [[ -z "${_hz_layer_type:-}" ]] && continue
    _hz_dst_dir="${RUNTIME_BACKEND}/hazard/${_hz_layer_type}/${REGION}"
    if [[ -f "${_hz_src_path}" ]]; then
        deploy_file "${_hz_src_path}" "${_hz_dst_dir}/$(basename "${_hz_src_path}")" "backend"
    elif [[ -d "${_hz_src_path}" ]]; then
        deploy_dir "${_hz_src_path}" "${_hz_dst_dir}" "*.geojson" "backend"
    else
        log_error "hazard dataset ${_hz_dataset_id} (${_hz_layer_type}): resolved pathが存在しません: ${_hz_src_path}"
        exit 1
    fi
    _hazard_gap_resolved_count=$((_hazard_gap_resolved_count + 1))
done < "${_hazard_gap_resolve_output}"
rm -f "${_hazard_gap_resolve_output}"
trap - RETURN EXIT
log_info "flood/storm_surge/pseudo_inland_flood: registryから${_hazard_gap_resolved_count}件のactive datasetをpublish対象として解決（region=${REGION}）"

# ─── backend: hazard / tsunami ────────────────────────────────────────────────
# 標準名 tsunami_{target}.geojson を優先検索。
# 見つからない場合は {target}-tsunami-*.geojson など別名ファイルを探して同名でデプロイ。
# これにより kanagawa-tsunami-001.geojson → tsunami_kanagawa.geojson のリネームに対応。
#
# CODEX P2B5-CX-003（第18ラウンド）対応: target集合の正本を
# backend/app.properties の hazard.tsunami.targets 1本に一本化する
# （backend/app_config_properties.py / backend/app_public.py が読む
# 設定fileと同一fileを直接読む）。従来は`for target in tokyo kanagawa
# chiba`とhardcodeしており、region指定に関わらず常に3 targetを配備して
# いた。chibaはtsunami_chiba.geojsonが139MB/約175K featureでメモリ約1GB
# を消費するため、consumer設定（hazard.tsunami.targets=tokyo,kanagawa）
# からは意図的に除外されている——「deploy可能なtarget」と「consumerが
# 実際に読み込むtarget」を混同すると、consumerが読まないtargetの無駄な
# 配備（かつては見過ごされたが、runtime_dataset_validate.pyのtsunami
# 参照整合性検証がstaging側target集合とconsumer設定のexact-matchを
# 要求するようになったため、放置すると publish 自体が拒否される）。
# CODEX同等指摘（Claude自己検証で発見）: 本scriptがoperator container内
# （backend/ が /app へmountされ、PROJECT_ROOTが"/"に解決される環境）で実行
# されると、host実行前提の"${PROJECT_ROOT}/backend/app.properties"は存在せず、
# 常にTSUNAMI_TARGETS既定値（tokyoのみ）へ静かにfallbackしていた。一方
# activate_version.py側のvalidator（runtime_dataset_validate.py
# `_resolve_configured_tsunami_targets()` → app_config_properties.
# resolve_config_path()）は`backend/`が/appへmountされる同一container内から
# 正しく`/app/app.properties`を解決し、`hazard.tsunami.targets=tokyo,kanagawa`
# を得る。producerとconsumer/validatorが異なる設定fileを見てしまい、
# tsunami参照整合性検証（欠落target拒否）が常にfailする実バグを引き起こして
# いた。`APP_PROPERTIES_FILE`環境変数とhost/container両レイアウトを
# consumer側と同じ優先順位で解決する。
APP_PROPERTIES_FILE_PATH="${APP_PROPERTIES_FILE:-}"
if [[ -z "${APP_PROPERTIES_FILE_PATH}" ]]; then
    if [[ -f "${PROJECT_ROOT}/backend/app.properties" ]]; then
        APP_PROPERTIES_FILE_PATH="${PROJECT_ROOT}/backend/app.properties"
    elif [[ -f "/app/app.properties" ]]; then
        # backend-operator/backend-public container慣行: backend/ が /app へmount
        # される（PROJECT_ROOTは"/scripts"の親として"/"に解決されるため
        # "${PROJECT_ROOT}/app.properties"は"/app.properties"という別物になり、
        # 実際の"/app/app.properties"を指さない）。
        APP_PROPERTIES_FILE_PATH="/app/app.properties"
    else
        APP_PROPERTIES_FILE_PATH="${PROJECT_ROOT}/backend/app.properties"
    fi
fi
_tsunami_targets_raw=""
if [[ -f "${APP_PROPERTIES_FILE_PATH}" ]]; then
    # 同一keyが複数出現した場合は最後の行を採用する（Java .properties の
    # 一般的な後勝ち規約。backend/app_config_properties.pyのload_properties()
    # も同じ規約——同一辞書keyへの代入で自然に後勝ちになる）。
    _tsunami_targets_raw="$(grep -E '^[[:space:]]*hazard\.tsunami\.targets[[:space:]]*=' "${APP_PROPERTIES_FILE_PATH}" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//; s/^[[:space:]]+//; s/[[:space:]]+$//')"
fi
TSUNAMI_TARGETS=()
if [[ -n "${_tsunami_targets_raw}" ]]; then
    IFS=',' read -ra _tsunami_target_parts <<< "${_tsunami_targets_raw}"
    for _part in "${_tsunami_target_parts[@]}"; do
        _trimmed="$(echo "${_part}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
        [[ -n "${_trimmed}" ]] && TSUNAMI_TARGETS+=("${_trimmed}")
    done
fi
if [[ ${#TSUNAMI_TARGETS[@]} -eq 0 ]]; then
    # backend/app_public.pyの既定値（APP_CONFIG.get("hazard.tsunami.targets",
    # "tokyo") → parse_csv(..., ["tokyo"])）と同一のfallback。
    TSUNAMI_TARGETS=("tokyo")
fi
log_info "tsunami targets (${APP_PROPERTIES_FILE_PATH} の hazard.tsunami.targets より解決): ${TSUNAMI_TARGETS[*]}"

log_info "--- tsunami ---"
for target in "${TSUNAMI_TARGETS[@]}"; do
    filename="tsunami_${target}.geojson"
    # 1. validated 標準名
    if [[ -f "${VALIDATED}/tsunami/${filename}" ]]; then
        deploy_file \
            "${VALIDATED}/tsunami/${filename}" \
            "${RUNTIME_BACKEND}/hazard/tsunami/${filename}" \
            "backend"
    # 2. normalized 標準名
    elif [[ -f "${NORMALIZED}/tsunami/${filename}" ]]; then
        deploy_file \
            "${NORMALIZED}/tsunami/${filename}" \
            "${RUNTIME_BACKEND}/hazard/tsunami/${filename}" \
            "backend"
    else
        # 3. 別名フォールバック: {target}-tsunami-*.geojson または {target}_tsunami_*.geojson
        _tsrc=""
        _tsrc_v="$(find "${VALIDATED}/tsunami" -maxdepth 1 \( -name "${target}-tsunami-*.geojson" -o -name "${target}_tsunami_*.geojson" \) 2>/dev/null | sort | head -1)"
        if [[ -n "${_tsrc_v}" ]]; then
            _tsrc="${_tsrc_v}"
        else
            _tsrc="$(find "${NORMALIZED}/tsunami" -maxdepth 1 \( -name "${target}-tsunami-*.geojson" -o -name "${target}_tsunami_*.geojson" \) 2>/dev/null | sort | head -1)"
        fi
        if [[ -n "${_tsrc}" ]]; then
            deploy_file "${_tsrc}" "${RUNTIME_BACKEND}/hazard/tsunami/${filename}" "backend"
        else
            log_warn "tsunami ${target}: ファイルが見つかりません (skip)"
        fi
    fi
done

# ─── backend: hazard / inland_flood ──────────────────────────────────────────
# region サブディレクトリ（hazard/inland_flood/{region}/）にデプロイする。
# これにより複数リージョンが共存でき、クリア操作が同一リージョン内に限定される。
# 正規化: python scripts/normalize/normalize_inland_flood.py
log_info "--- inland_flood ---"
if [[ -d "${NORMALIZED}/inland_flood" ]] && compgen -G "${NORMALIZED}/inland_flood/*.geojson" > /dev/null 2>&1; then
    # デプロイ前に同一リージョンのサブディレクトリのみクリア（他リージョンには影響しない）
    if ! "${DRY_RUN}" && [[ -d "${RUNTIME_BACKEND}/hazard/inland_flood/${REGION}" ]]; then
        find "${RUNTIME_BACKEND}/hazard/inland_flood/${REGION}" -maxdepth 1 -name "*.geojson" -delete
        log_info "Cleared stale GeoJSON from ${RUNTIME_BACKEND}/hazard/inland_flood/${REGION}"
    fi
    deploy_dir \
        "${NORMALIZED}/inland_flood" \
        "${RUNTIME_BACKEND}/hazard/inland_flood/${REGION}" \
        "*.geojson" \
        "backend"
else
    log_warn "inland_flood normalized data not found — deploying legacy sample"
    deploy_file \
        "${PROJECT_ROOT}/data/hazard/inland_flood_sample.geojson" \
        "${RUNTIME_BACKEND}/hazard/inland_flood/${REGION}/inland_flood_sample.geojson" \
        "backend"
fi

# ─── backend: hazard / landslide ─────────────────────────────────────────────
# region サブディレクトリ（hazard/landslide/{region}/）にデプロイする。
# 正規化: python scripts/normalize/normalize_landslide.py
# データ: 国土数値情報 A33（土砂災害警戒区域）→ data_lake/raw/{region}/landslide/
log_info "--- landslide ---"
if [[ -d "${NORMALIZED}/landslide" ]] && compgen -G "${NORMALIZED}/landslide/*.geojson" > /dev/null 2>&1; then
    if ! "${DRY_RUN}" && [[ -d "${RUNTIME_BACKEND}/hazard/landslide/${REGION}" ]]; then
        find "${RUNTIME_BACKEND}/hazard/landslide/${REGION}" -maxdepth 1 -name "*.geojson" -delete
        log_info "Cleared stale GeoJSON from ${RUNTIME_BACKEND}/hazard/landslide/${REGION}"
    fi
    deploy_dir \
        "${NORMALIZED}/landslide" \
        "${RUNTIME_BACKEND}/hazard/landslide/${REGION}" \
        "*.geojson" \
        "backend"
else
    log_warn "landslide normalized data not found — deploying legacy sample"
    deploy_file \
        "${PROJECT_ROOT}/data/hazard/landslide_sample.geojson" \
        "${RUNTIME_BACKEND}/hazard/landslide/${REGION}/landslide_sample.geojson" \
        "backend"
fi

# ─── backend: hazard / lowland_poor_drainage ─────────────────────────────────
# region サブディレクトリ（hazard/lowland_poor_drainage/{region}/）にデプロイする。
# 正規化: python scripts/normalize/normalize_lowland_poor_drainage.py
# データ: 国土数値情報 G08（低位地帯）→ data_lake/raw/{region}/lowland_poor_drainage/
#
# Phase 2-B.5 CODEX P2B5-CX-004（第8ラウンド）対応: 従来この補助hazard
# typeはfrontend tile（frontend/tiles配下）としてのみ配備され、backend
# 側（app_public.pyのHazardService）はatomic publish対象外のdata_lake
# validatedを直接読んでいた。atomic lease機構が有効な環境では
# app_public.py側の対称的なsnapshot混在防止（第22.2節）により、この
# 型が常にskipされる状態になっていた。他のhazard typeと同じく
# backend/hazard配下へも配備し、atomic publish/lease経由でloadできる
# ようにする。
log_info "--- lowland_poor_drainage ---"
if [[ -d "${NORMALIZED}/lowland_poor_drainage" ]] && compgen -G "${NORMALIZED}/lowland_poor_drainage/*.geojson" > /dev/null 2>&1; then
    if ! "${DRY_RUN}" && [[ -d "${RUNTIME_BACKEND}/hazard/lowland_poor_drainage/${REGION}" ]]; then
        find "${RUNTIME_BACKEND}/hazard/lowland_poor_drainage/${REGION}" -maxdepth 1 -name "*.geojson" -delete
        log_info "Cleared stale GeoJSON from ${RUNTIME_BACKEND}/hazard/lowland_poor_drainage/${REGION}"
    fi
    deploy_dir \
        "${NORMALIZED}/lowland_poor_drainage" \
        "${RUNTIME_BACKEND}/hazard/lowland_poor_drainage/${REGION}" \
        "*.geojson" \
        "backend"
else
    log_warn "lowland_poor_drainage normalized data not found (skip backend deploy)"
fi

# ─── backend: shelters ────────────────────────────────────────────────────────
# shelter_atomic_publish修復: 従来は`${VALIDATED}/shelter`というハードコードされた
# 単一directory名だけをcopyしており、active_mappings.json登録済みの避難所系
# datasetのうち一部（例: TOKYO-EVAC-001, KANAGAWA-EVAC-001、正式pathの
# TOKYO-SHELTER-001）がdirectory名不一致のため常に欠落していた
# （tasks/public-release/shelter_count_difference_investigation_claude.md）。
# registry（active_mappings.json + dataset_definitions.json + DatasetState）を
# 正本とし、scripts/publish/resolve_shelter_sources.pyが
# backend/app/services/shelter_service.SHELTER_LAYER_TYPES
# （読み取り側 ShelterRegistry._resolve_paths() と共有する単一の定数）に
# 一致するactive datasetを列挙する。dataset_idごとにsubdirectoryへ分離して
# 配備することでfilename collisionを構造的に排除する
# （consumer側のload_emergency_shelters()は既にdirectoryをrglobする実装のため、
# 追加のconsumer変更は不要）。
log_info "--- shelters (registry-resolved) ---"
mkdir -p "${RUNTIME_BACKEND}/shelters"
# 注意: 旧ロジック（${VALIDATED}/shelterをshelters直下へflatに展開）が
# 過去のpublishで残したtop-level file（registryに紐付かない非公式dataset）は、
# ここでは意図的に削除しない。incremental publishのvalidator
# （runtime_dataset_validate.py の件数整合性検証）は「前versionに存在した
# rel-pathが新staging側から消失」をdata損失の疑いとしてfail-closedで拒否する
# 設計であり、実際にこの削除を試みたところ拒否された（実機確認済み）。
# これらのfileを本当に廃止すべきかはtasks/public-release/
# shelter_atomic_publish_repair_claude.mdで報告し、削除するかどうかはOWNER判断に
# 委ねる（勝手に削除しない、第4節参照）。dataset_idサブディレクトリ
# （下記ループ）と共存させ、load_emergency_shelters()のdedupに委ねる。
_shelter_resolved_count=0
while IFS=$'\t' read -r _shelter_dataset_id _shelter_src_path; do
    [[ -z "${_shelter_dataset_id:-}" ]] && continue
    _shelter_dst_dir="${RUNTIME_BACKEND}/shelters/${_shelter_dataset_id}"
    if [[ -d "${_shelter_src_path}" ]]; then
        deploy_dir "${_shelter_src_path}" "${_shelter_dst_dir}" "*.geojson" "backend"
        deploy_dir "${_shelter_src_path}" "${_shelter_dst_dir}" "*.csv"     "backend"
    elif [[ -f "${_shelter_src_path}" ]]; then
        deploy_file "${_shelter_src_path}" "${_shelter_dst_dir}/$(basename "${_shelter_src_path}")" "backend"
    else
        log_warn "shelter dataset ${_shelter_dataset_id}: resolved pathが存在しません: ${_shelter_src_path}"
        continue
    fi
    _shelter_resolved_count=$((_shelter_resolved_count + 1))
done < <(python3 "${SCRIPT_DIR}/resolve_shelter_sources.py" --region "${REGION}")
log_info "shelters: registryから${_shelter_resolved_count}件のactive datasetをpublish対象として解決（region=${REGION}）"

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

    # storm_surge GeoJSON fallback（region 対応）
    deploy_file \
        "${NORMALIZED}/storm_surge/${REGION}_storm_surge.geojson" \
        "${RUNTIME_FRONTEND_LAYERS}/${REGION}_storm_surge.geojson" \
        "frontend_layers"

    # tsunami: region ファイルのみ（kanagawa/chiba はサイズ大のため GeoJSON fallback は region のみ）
    # 標準名 tsunami_{REGION}.geojson を優先し、なければ別名ファイルを探す
    _tsunami_fe_src=""
    if [[ -f "${NORMALIZED}/tsunami/tsunami_${REGION}.geojson" ]]; then
        _tsunami_fe_src="${NORMALIZED}/tsunami/tsunami_${REGION}.geojson"
    else
        _tsunami_fe_found="$(find "${NORMALIZED}/tsunami" -maxdepth 1 \( -name "${REGION}-tsunami-*.geojson" -o -name "${REGION}_tsunami_*.geojson" \) 2>/dev/null | sort | head -1)"
        [[ -n "${_tsunami_fe_found}" ]] && _tsunami_fe_src="${_tsunami_fe_found}"
    fi
    if [[ -n "${_tsunami_fe_src}" ]]; then
        deploy_file "${_tsunami_fe_src}" "${RUNTIME_FRONTEND_LAYERS}/tsunami_${REGION}.geojson" "frontend_layers"
    else
        log_warn "tsunami frontend fallback for ${REGION}: ファイルが見つかりません (skip)"
    fi

    # flood fallback: normalized の軽量 GeoJSON が存在する場合のみ
    if [[ -f "${NORMALIZED}/flood/${REGION}_flood_max.geojson" ]]; then
        deploy_file \
            "${NORMALIZED}/flood/${REGION}_flood_max.geojson" \
            "${RUNTIME_FRONTEND_LAYERS}/${REGION}_flood_max.geojson" \
            "frontend_layers"
    fi

    # inland_flood: normalized を優先、未配置なら legacy sample（tokyo のみ）
    if [[ -d "${NORMALIZED}/inland_flood" ]] && compgen -G "${NORMALIZED}/inland_flood/*.geojson" > /dev/null 2>&1; then
        # 最初のファイルを inland_flood_{REGION}.geojson として配備
        _if_src="$(find "${NORMALIZED}/inland_flood" -maxdepth 1 -name "*.geojson" | sort | head -1)"
        deploy_file "${_if_src}" "${RUNTIME_FRONTEND_LAYERS}/inland_flood_${REGION}.geojson" "frontend_layers"
    elif [[ "${REGION}" == "tokyo" ]]; then
        deploy_file \
            "${PROJECT_ROOT}/data/hazard/inland_flood_sample.geojson" \
            "${RUNTIME_FRONTEND_LAYERS}/inland_flood_${REGION}.geojson" \
            "frontend_layers"
    fi
    # landslide: normalized を優先、未配置なら legacy sample（tokyo のみ）
    if [[ -d "${NORMALIZED}/landslide" ]] && compgen -G "${NORMALIZED}/landslide/*.geojson" > /dev/null 2>&1; then
        _ls_src="$(find "${NORMALIZED}/landslide" -maxdepth 1 -name "*.geojson" | sort | head -1)"
        deploy_file "${_ls_src}" "${RUNTIME_FRONTEND_LAYERS}/landslide_${REGION}.geojson" "frontend_layers"
    elif [[ "${REGION}" == "tokyo" ]]; then
        deploy_file \
            "${PROJECT_ROOT}/data/hazard/landslide_sample.geojson" \
            "${RUNTIME_FRONTEND_LAYERS}/landslide_${REGION}.geojson" \
            "frontend_layers"
    fi

    # ── frontend: tiles (Martin が使用する .mbtiles) ──────────────────────────
    # data_lake/tiles/{region}/ → data_runtime/frontend/tiles/{region}/
    log_info "--- frontend tiles ---"
    mkdir -p "${RUNTIME_FRONTEND_TILES}"

    for hazard_type in flood tsunami storm_surge urban_flood pseudo_inland_flood lowland_poor_drainage; do
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
    # Phase 2-B.5: staging mode（OHG2_STAGING_ROOT設定時）では、まだvalidate/
    # atomic publishを経ていない内容をnginx配信先へ同期してはならないため、
    # ここではskipし、scripts/publish/deploy_to_runtime_atomic.sh が
    # activate_version.py成功後に data_runtime/current/frontend/layers/ から
    # 同期する。
    if [[ -n "${OHG2_STAGING_ROOT:-}" ]]; then
        log_info "--- sync frontend/layers: staging modeのためskip（publish成功後に別途実施） ---"
    elif [[ -d "${RUNTIME_FRONTEND_LAYERS}" ]]; then
        mkdir -p "${FRONTEND_LAYERS_DIR}"
        if "${DRY_RUN}"; then
            log_info "[dry-run] rsync ${RUNTIME_FRONTEND_LAYERS}/ -> ${FRONTEND_LAYERS_DIR}/"
        else
            # rsync が使えない環境でも cp で代替
            if command -v rsync &>/dev/null; then
                rsync -a "${RUNTIME_FRONTEND_LAYERS}/" "${FRONTEND_LAYERS_DIR}/"
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
