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
#   scripts/publish/deploy_to_runtime_atomic.sh [--region tokyo] [--region kanagawa] [--skip-frontend]
#
# --region は複数回指定できる（例: --region tokyo --region kanagawa）。
# 同一staging directoryへ region 分だけ deploy_to_runtime.sh を順に実行してから
# 一度だけ validate/activateする。tsunami consumer設定
# （backend/app.properties の hazard.tsunami.targets）は複数regionを要求する
# ため、初回publish（currentが未設定でseedできない）では対象regionすべてを
# 単一versionへ含めないと参照整合性検証（第6節 runtime_dataset_validate.py）
# を通過できない。
#
# (--dry-run は本atomic wrapperでは非対応。dry-runしたい場合は
#  既存 deploy_to_runtime.sh を直接呼ぶこと。)

set -euo pipefail

# Phase 2-B.5: activate_version.py のidentity検証（第4.2節）が期待する
# umask 0007をこのpublish処理全体に対して明示設定する。
umask 0007

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# Claude自己検証で発見した実バグ: operator container内ではscripts/が/scriptsへ
# mountされるため、ここでPROJECT_ROOTは"/"（末尾スラッシュそのもの）に解決
# される。以降"${PROJECT_ROOT}/xxx"という連結を単純に行うと常に"//xxx"という
# 二重先頭slashになる。通常のfilesystem呼び出し（open/mkdir/stat等）は
# 二重slashを単一slashと同一視するため無害に見えるが、少なくとも2つの
# 実害を確認した: (1) sqlite3のfile: URIパーサが"//"直後の最初のsegmentを
# authorityとして誤解釈しfail-closedで拒否する（runtime_dataset_validate.py
# 側で別途対処済み）、(2) 本scriptの`chmod`/`find -exec chmod`が、二重slash
# path経由では対象directoryのmode変更を実際にはpersistさせない
# （同一directoryを単一slash pathで触ると即座に反映されることを実機で確認
# 済み——Docker Desktop named volume背後のvirtiofs/9pがpath文字列の"//"を
# 特別扱いしている挙動と推測される）。これによりstaging directory自身が
# `.staging`の設定gid setgid（0o2750）を引き継いだまま`0750`へ実際には
# 変更されず、activate_version.pyのpermission検証が
# 「許可外のdirectory mode: mode=0o2750」で毎回failしていた。
# PROJECT_ROOTが厳密に"/"の場合だけ末尾を落とし、以降のpath連結を
# 常に単一先頭slashにする（他のhost実行時のPROJECT_ROOTは元々"/"以外の
# 通常pathであり、この行は無害）。
PROJECT_ROOT="${PROJECT_ROOT%/}"
source "${PROJECT_ROOT}/scripts/common/log.sh"

REGIONS=()
SKIP_FRONTEND_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)        REGIONS+=("$2"); shift 2 ;;
        --skip-frontend) SKIP_FRONTEND_ARG="--skip-frontend"; shift ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done
if [[ "${#REGIONS[@]}" -eq 0 ]]; then
    REGIONS=("tokyo")
fi

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
log_info "regions    = ${REGIONS[*]}"

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

# 既存 deploy_to_runtime.sh を region ごとにstaging modeで実行する（同一
# staging directoryへ積み重ねる）。各regionのdataset出力先はregion名を含む
# ため（backend/hazard/<type>/<region>[...], frontend/tiles/<region>/...）、
# 複数回の呼び出しが互いを上書きすることはない。
for _region in "${REGIONS[@]}"; do
    log_info "--- region: ${_region} ---"
    OHG2_STAGING_ROOT="${STAGING_DIR}" \
        "${SCRIPT_DIR}/deploy_to_runtime.sh" --region "${_region}" ${SKIP_FRONTEND_ARG}
done

# Claude自己検証で発見した実バグ（macOS Docker Desktop named volume、
# virtiofs/gRPC-FUSE経由での実機確認）: `.staging`自身がsetgid（0o2750、
# init_lease_volume.py STAGING_DIR_MODE）のため、その配下に新規作成される
# `${STAGING_DIR}`はmkdir時点でsetgidを自動継承する（POSIX標準の setgid
# 伝播、これ自体は正常）。ところがこの環境では、その後の**絶対8進数
# `chmod 0750`（setgidビットを含まない値）を指定してもsetgidビットが
# 一切clearされず残り続ける**ことを実機で確認した（同一directoryに対し
# `chmod 0700`→stat結果が`2700`のまま、という形で再現）。一方、setgidを
# 明示的に落とす symbolic `chmod g-s` は同じ環境で確実に機能する
# （`chmod g-s`→`755`、その後の絶対`chmod 0750`→`750`が正しく反映される
# ことを確認済み）。これを行わないと、staging directory自身（version root）
# が`activate_version.py`のpermission検証（第5.1節: 公開済みversion
# directoryは許可mode`0750`のみ）に`0o2750`のまま失敗し続ける。
# 絶対chmodの前に必ずsymbolicでsetgid/setuidを明示的に落とす。
find "${STAGING_DIR}" -exec chmod g-s,u-s {} \; 2>/dev/null || true
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
    # currentは既にswap済みのため、以降の同期stepが失敗してもpublish自体を
    # 失敗として扱わない（`|| log_warn`でset -eの即時終了を防ぐ）。
    # operator containerのmountがhost実運用と完全一致しない環境（例:
    # frontend/layers/railwaysのみbind mountするbackend-operator）では
    # このsyncが書込み不能になり得るが、それは「atomic data_runtime
    # publishが失敗した」こととは別問題であるため区別する。
    if [[ -d "${LAYERS_SRC}" ]]; then
        mkdir -p "${LAYERS_DST}" 2>/dev/null || true
        if command -v rsync &>/dev/null; then
            if rsync -a "${LAYERS_SRC}/" "${LAYERS_DST}/"; then
                log_info "synced current/frontend/layers -> frontend/layers"
            else
                log_warn "current/frontend/layers -> frontend/layers 同期に失敗（publish自体は成功済み。書込み先mount未整備の可能性）"
            fi
        else
            if cp -a "${LAYERS_SRC}/." "${LAYERS_DST}/"; then
                log_info "synced current/frontend/layers -> frontend/layers"
            else
                log_warn "current/frontend/layers -> frontend/layers 同期に失敗（publish自体は成功済み。書込み先mount未整備の可能性）"
            fi
        fi
    fi

    # local runtime publish基盤修復で追加: Martin（config/martin-local.yaml、
    # production側はconfig/martin.yaml）は/data_runtime/frontend/tiles/
    # <region>/<hazard>を直接scanし、atomic版の`current`は一切参照しない
    # （Martin 1.14.0はmbtiles.pathsに列挙したpathが存在しないとfatal終了する
    # ため、`current`配下だけを参照先にすると、一度もpublishしていない
    # fresh volumeでMartinが起動できなくなる）。この非atomic・常時存在する
    # flat mirrorを、publish成功のたびにcurrentの内容で上書きし直すことで、
    # Martinに新しいtileを反映させる（`docker compose restart martin`が
    # 別途必要——config自体の変更ではなくファイル追加のため）。
    TILES_SRC="${DATA_RUNTIME}/current/frontend/tiles"
    TILES_DST="${DATA_RUNTIME}/frontend/tiles"
    if [[ -d "${TILES_SRC}" ]]; then
        mkdir -p "${TILES_DST}" 2>/dev/null || true
        if command -v rsync &>/dev/null; then
            if rsync -a "${TILES_SRC}/" "${TILES_DST}/"; then
                log_info "synced current/frontend/tiles -> data_runtime/frontend/tiles (Martin向けflat mirror)"
            else
                log_warn "current/frontend/tiles -> data_runtime/frontend/tiles 同期に失敗（publish自体は成功済み。Martin向けmirror未整備の可能性、frontend/tiles配下のoperator write権限を確認すること）"
            fi
        else
            if cp -a "${TILES_SRC}/." "${TILES_DST}/"; then
                log_info "synced current/frontend/tiles -> data_runtime/frontend/tiles (Martin向けflat mirror)"
            else
                log_warn "current/frontend/tiles -> data_runtime/frontend/tiles 同期に失敗（publish自体は成功済み。Martin向けmirror未整備の可能性、frontend/tiles配下のoperator write権限を確認すること）"
            fi
        fi
    fi
fi

log_info "=== deploy_to_runtime_atomic.sh done ==="
