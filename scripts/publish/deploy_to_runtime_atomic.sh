#!/usr/bin/env bash
# deploy_to_runtime_atomic.sh
#
# Phase 2-B.5: 既存 deploy_to_runtime.sh のdataset生成ロジックをそのまま使い、
# 出力先をdata_runtime直接ではなくstaging directoryへ向け、生成完了後に
# activate_version.py でatomic publish（validate→fsync→no-replace rename→
# symlink atomic swap）を実行する。
#
# operator container内（backend-operator、UID 10002:10002）での実行を
# 前提とする。既存operator CLI経路として提供し、新しいpublic route／
# operator HTTP routeは追加しない。
#
# 使い方:
#   scripts/publish/deploy_to_runtime_atomic.sh [--region tokyo] [--skip-frontend]
#
# (--dry-run は本atomic wrapperでは非対応。dry-runしたい場合は
#  既存 deploy_to_runtime.sh を直接呼ぶこと。)

set -euo pipefail

# Phase 2-B.5: activate_version.py のidentity検証（第4.2節）が期待する
# umask 0007をこのpublish処理全体に対して明示設定する。
umask 0007

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"

REGION="tokyo"
SKIP_FRONTEND_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)        REGION="$2"; shift 2 ;;
        --skip-frontend) SKIP_FRONTEND_ARG="--skip-frontend"; shift ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

DATA_RUNTIME="${PROJECT_ROOT}/data_runtime"
CURRENT_LINK="${DATA_RUNTIME}/current"
STAGING_ROOT_BASE="${DATA_RUNTIME}/.staging"

# version ID生成: backend/app/services/runtime_atomic.py の
# validate_version_id() が受理する形式（YYYYMMDDTHHMMSSZ-<8 hex>）に合わせる。
VERSION_ID="$(date -u '+%Y%m%dT%H%M%SZ')-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n' | cut -c1-8)"
STAGING_DIR="${STAGING_ROOT_BASE}/${VERSION_ID}"

log_info "=== deploy_to_runtime_atomic.sh ==="
log_info "version_id = ${VERSION_ID}"
log_info "staging    = ${STAGING_DIR}"

mkdir -p "${STAGING_ROOT_BASE}"
if [[ -e "${STAGING_DIR}" ]]; then
    log_error "staging directoryが既に存在する（version ID衝突）: ${STAGING_DIR}"
    exit 1
fi
mkdir -p "${STAGING_DIR}"
chmod 0750 "${STAGING_DIR}"

# currentが既に存在する場合、その内容をstagingへ種として複製する
# （deploy_to_runtime.sh は既存の一部ファイルだけを選択的に更新する
# incremental方式のため、未更新分をそのままstagingへ引き継ぐ必要がある）。
if [[ -L "${CURRENT_LINK}" ]]; then
    CURRENT_TARGET="$(readlink "${CURRENT_LINK}")"
    CURRENT_REAL="${DATA_RUNTIME}/${CURRENT_TARGET}"
    if [[ -d "${CURRENT_REAL}" ]]; then
        log_info "seeding staging from current: ${CURRENT_REAL}"
        cp -a "${CURRENT_REAL}/." "${STAGING_DIR}/"
    fi
else
    log_info "current未設定（初回publish）。staging を空から生成する。"
fi

# 既存 deploy_to_runtime.sh をstaging modeで実行する。
OHG2_STAGING_ROOT="${STAGING_DIR}" \
    "${SCRIPT_DIR}/deploy_to_runtime.sh" --region "${REGION}" ${SKIP_FRONTEND_ARG}

chmod -R u+rX,g+rX,o-rwx "${STAGING_DIR}" 2>/dev/null || true
find "${STAGING_DIR}" -type d -exec chmod 0750 {} \; 2>/dev/null || true
find "${STAGING_DIR}" -type f -exec chmod 0640 {} \; 2>/dev/null || true

# CODEX P2B5-CX-007（第2ラウンド）permission matrix拡張作業中に発見した実バグ:
# operator（primary gid 10002）が生成したfileはgroupが10002のままとなり、
# publicはこのgroupに属さない（publicのsupplemental gidは20001のみ）ため、
# mode 0640であってもpublicは実Linux環境（named volume等の真のfilesystem）で
# published version treeを一切read出来なかった（named volumeで実証・修正済み）。
# operator/public双方が持つ共有supplemental group（leases gid）へ明示的に
# chgrpし、実際にpublicから読めるようにする。
STAGING_LEASES_GID="${OHG2_LEASES_GID:-20001}"
chgrp -R "${STAGING_LEASES_GID}" "${STAGING_DIR}" 2>/dev/null || true

log_info "activating version via activate_version.py ..."
# CODEX P2B5-CX-006（第4ラウンド）対応: activate_version.pyがexit 3
# （EXIT_DURABILITY_UNKNOWN、currentは切替済みだが耐久性未確認）を返す
# ケースを、通常のexit 1（真の公開失敗）と区別して扱う必要がある。
# `set -e`の下では非0 exitで即座にscriptが終了してしまうため、この
# 呼び出しだけ一時的に無効化し、exit codeを明示的に分岐させる。
set +e
python3 "${SCRIPT_DIR}/activate_version.py" \
    --data-runtime-root "${DATA_RUNTIME}" \
    --version-id "${VERSION_ID}"
ACTIVATE_EXIT_CODE=$?
set -e

if [[ "${ACTIVATE_EXIT_CODE}" -eq 3 ]]; then
    log_error "=================================================================="
    log_error "警告: publishのcurrent切替自体は成功したが、耐久性（クラッシュ後の"
    log_error "生存）を確認できなかった（activate_version.py exit 3）。"
    log_error "current -> versions/${VERSION_ID} は既にactiveである。"
    log_error "operatorは実際のdata_runtime状態を確認し、必要であれば手動で"
    log_error "再publishまたはrollbackを判断すること。この状態を「公開成功」"
    log_error "としても「公開失敗」としても自動的には扱わない（fail-silentも"
    log_error "fail-closedも行わない、明示的な要operator判断状態）。"
    log_error "=================================================================="
    exit 3
elif [[ "${ACTIVATE_EXIT_CODE}" -ne 0 ]]; then
    log_error "activate_version.py failed (exit ${ACTIVATE_EXIT_CODE})。current は変更されていない。"
    exit "${ACTIVATE_EXIT_CODE}"
fi

log_info "publish succeeded: current -> versions/${VERSION_ID}"

if [[ -z "${SKIP_FRONTEND_ARG}" ]]; then
    LAYERS_SRC="${DATA_RUNTIME}/current/frontend/layers"
    LAYERS_DST="${PROJECT_ROOT}/frontend/layers"
    if [[ -d "${LAYERS_SRC}" ]]; then
        mkdir -p "${LAYERS_DST}"
        if command -v rsync &>/dev/null; then
            rsync -a "${LAYERS_SRC}/" "${LAYERS_DST}/"
        else
            cp -a "${LAYERS_SRC}/." "${LAYERS_DST}/"
        fi
        log_info "synced current/frontend/layers -> frontend/layers"
    fi
fi

log_info "=== deploy_to_runtime_atomic.sh done ==="
