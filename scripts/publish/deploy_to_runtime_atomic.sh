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
#       [--full-revalidate] [--allow-flood-routing-migration <OWNER承認の参照>] [--rebuild-from-sources]
#
# --rebuild-from-sources は current を種にせず、registry / data_lake の正式な成果物だけで version を組み立てる
# （region は自動で全 region。source から作られなくなった旧 artifact を current から外す環境再構築用）。
# 表示必須の tile・tsunami target の runtime が揃わなければ activate しない。外れる file は log に一覧する。
#
# 検証の再利用（VALIDATED-CONTENT-REUSE）は既定で有効。前 version と内容（sha256）・検証規則
# （validation_contract）が同一の file は再検証せず、変更された file だけを全検証する。
# 前 manifest が旧形式・検証規則の変更・migration 時は自動的に全検証になる（指定不要）。
# 全 file を必ず再検証したい場合だけ --full-revalidate（または環境変数
# OHG2_PUBLISH_FULL_REVALIDATION=1）を指定する。どちらで動いたかは log と manifest の
# validation_reuse に毎回記録される。
#
# --allow-flood-routing-migration は初回 flood routing migration 専用（legacy flood path
# backend/hazard/flood/<region>/<dataset>.geojson → <dataset>.routing.geojson）。
# OWNER の明示承認の参照文字列を必須とし、activate_version.py がそれを manifest に記録する。
# 前 version に legacy flood が無い（移行済み）場合は validator が拒否するため、通常 publish では
# 使用できない（docs/architecture/flood_canonical_routing_split.md）。
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
#
# 終了コード: 0=成功 / 1=publish失敗（currentは未変更）/ 3=耐久性未確認（current切替済み）/
#             4=publish成功（current切替済み）だがMartin向けflat mirrorのpermission contract
#               （file 10002:20001 0640。backend-publicがmbtilesを読めること）を満たせない
#               （RUNTIME-MBTILES-GROUP-CONTRACT、sync_frontend_tiles_mirror.sh）

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
FLOOD_MIGRATION_APPROVAL_REF=""
FULL_REVALIDATE="${OHG2_PUBLISH_FULL_REVALIDATION:-0}"
REBUILD_FROM_SOURCES=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)        REGIONS+=("$2"); shift 2 ;;
        --skip-frontend) SKIP_FRONTEND_ARG="--skip-frontend"; shift ;;
        --full-revalidate) FULL_REVALIDATE=1; shift ;;
        --rebuild-from-sources) REBUILD_FROM_SOURCES=1; shift ;;
        --allow-flood-routing-migration)
            if [[ -z "${2:-}" || "${2:-}" == --* ]]; then
                log_error "--allow-flood-routing-migration には OWNER 承認の参照文字列が必須です"
                exit 1
            fi
            FLOOD_MIGRATION_APPROVAL_REF="$2"; shift 2 ;;
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

# 工程別の経過秒（ATOMIC-PUBLISH-TIMING）。publish 時間・I/O の内訳を log から追えるようにする。
_STEP_T0="$(date +%s.%N)"
_STEP_PREV="${_STEP_T0}"
log_step() {
    local now; now="$(date +%s.%N)"
    log_info "[timing] $1: $(awk -v a="${_STEP_PREV}" -v b="${now}" 'BEGIN{printf "%.2f", b-a}')s" \
             "(total $(awk -v a="${_STEP_T0}" -v b="${now}" 'BEGIN{printf "%.2f", b-a}')s)"
    _STEP_PREV="${now}"
}

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
    if [[ "${REBUILD_FROM_SOURCES}" == "1" ]]; then
        # --rebuild-from-sources: current を種にせず、registry / data_lake の正式な成果物だけで組み立てる
        # （source から作られなくなった旧 artifact を current から外す。scripts/publish/rebuild_from_sources.py）
        log_warn "rebuild-from-sources: current を種にしない（staging を空から作る）: ${CURRENT_REAL}"
    elif [[ -d "${CURRENT_REAL}" ]]; then
        log_info "seeding staging from current: ${CURRENT_REAL}"
        # --reflink=auto: reflink 対応 filesystem（VPS: XFS reflink=1）では data block を共有する
        # copy-on-write clone になり、物理 write はほぼ発生しない。非対応 fs では通常 copy に縮退する。
        # GNU coreutils 9.0 以降の既定値と同じ（明示して意図を固定する）。hardlink は使わない
        # （version tree は link count 1 が契約: runtime_publish._verify_permissions）。
        cp -a --reflink=auto "${CURRENT_REAL}/." "${STAGING_DIR}/"
    fi
else
    log_info "current未設定（初回publish）。staging を空から生成する。"
fi
log_step "seed staging from current"

# TILE-PATH-MIGRATION: 移動が未完了の MIGRATED record（current に旧 path があり移動先が無い）の移動先 region を
# publish 対象へ自動で含める。含めないと staging で移動先が揃わず publish が中止になる（admin UI の publish
# region は active mapping 由来で、tile だけの region を含まない）。人が region を覚えなくてよい。
# 含めてよいのは registry の dataset の tile 契約と一致する移動先だけ（未知 region・不整合は publish 中止）。
if [[ -n "${CURRENT_REAL:-}" && -d "${CURRENT_REAL}" ]]; then
    if ! _pending_regions="$(python3 "${SCRIPT_DIR}/apply_tile_retirements.py" --pending-migration-regions --current "${CURRENT_REAL}")"; then
        log_error "tile 移動 record から publish region を決められない（publish を中止。current は変更されていない）"
        exit 1
    fi
    for _r in ${_pending_regions}; do
        if [[ ! "${_r}" =~ ^[a-z][a-z0-9_]*$ ]]; then
            log_error "tile 移動 record の region 名が不正: ${_r}（publish を中止）"
            exit 1
        fi
        if [[ " ${REGIONS[*]} " != *" ${_r} "* ]]; then
            log_info "tile 移動が未完了のため region=${_r} を publish 対象に追加（tile_dispositions.json の MIGRATED）"
            REGIONS+=("${_r}")
        fi
    done
    # TSUNAMI-REGION-OWNERSHIP: hazard.tsunami.targets にあるのに current に backend runtime file
    # （tsunami_<region>.geojson）が無い region も自動で含める（targets に region を加えた直後の publish）。
    # 含めないと activate の参照整合性検証が target 欠落で拒否する。registry に dataset が無い target は中止。
    if ! _target_regions="$(python3 "${SCRIPT_DIR}/resolve_tsunami_source.py" --missing-target-regions --current "${CURRENT_REAL}")"; then
        log_error "hazard.tsunami.targets から publish region を決められない（publish を中止。current は変更されていない）"
        exit 1
    fi
    for _r in ${_target_regions}; do
        if [[ ! "${_r}" =~ ^[a-z][a-z0-9_]*$ ]]; then
            log_error "hazard.tsunami.targets の region 名が不正: ${_r}（publish を中止）"
            exit 1
        fi
        if [[ " ${REGIONS[*]} " != *" ${_r} "* ]]; then
            log_info "hazard.tsunami.targets の region=${_r} が current に無いため publish 対象に追加"
            REGIONS+=("${_r}")
        fi
    done
fi

if [[ "${REBUILD_FROM_SOURCES}" == "1" ]]; then
    if ! _rebuild_regions="$(python3 "${SCRIPT_DIR}/rebuild_from_sources.py" --regions)"; then
        log_error "rebuild-from-sources: 再構築する region を決められない（publish を中止）"
        exit 1
    fi
    for _r in ${_rebuild_regions}; do
        if [[ " ${REGIONS[*]} " != *" ${_r} "* ]]; then
            log_info "rebuild-from-sources: region=${_r} を publish 対象に追加"
            REGIONS+=("${_r}")
        fi
    done
fi

# 既存 deploy_to_runtime.sh を region ごとにstaging modeで実行する（同一
# staging directoryへ積み重ねる）。各regionのdataset出力先はregion名を含む
# ため（backend/hazard/<type>/<region>[...], frontend/tiles/<region>/...）、
# 複数回の呼び出しが互いを上書きすることはない。
for _region in "${REGIONS[@]}"; do
    log_info "--- region: ${_region} ---"
    OHG2_STAGING_ROOT="${STAGING_DIR}" \
        "${SCRIPT_DIR}/deploy_to_runtime.sh" --region "${_region}" ${SKIP_FRONTEND_ARG}
    log_step "deploy region ${_region}"
done

if [[ "${REBUILD_FROM_SOURCES}" == "1" ]]; then
    if ! python3 "${SCRIPT_DIR}/rebuild_from_sources.py" --check-staging "${STAGING_DIR}" \
            ${CURRENT_REAL:+--current "${CURRENT_REAL}"}; then
        log_error "rebuild-from-sources: 再構築した staging に必須の artifact が無い（publish を中止。current は変更されていない）"
        exit 1
    fi
    log_step "rebuild-from-sources check"
fi

# RUNTIME-PROVENANCE: build node が書いた provenance record（data_lake/provenance/）を staging の
# provenance/<dataset_id>.json へ配置する（activate で _manifest.json に sha256 が載り、rollback と整合する）。
# record の有無は publish の成否に影響させない（無ければ Data Ops が LEGACY と表示する）。
_prov_regions=()
for _region in "${REGIONS[@]}"; do _prov_regions+=(--region "${_region}"); done
if ! python3 "${SCRIPT_DIR}/stage_runtime_provenance.py" --staging "${STAGING_DIR}" "${_prov_regions[@]}"; then
    log_warn "runtime provenance の配置に失敗（publish は続行。Data Ops では LEGACY_RUNTIME_PROVENANCE と表示される）"
fi
log_step "stage runtime provenance"

# TILE-RETIREMENT: tile_dispositions.json で RETIRED と明示した tile（rel_path 単位、wildcard なし）を
# staging から除く（新 version の manifest に入らない）。前 version は触らない。record 不正は publish を止める。
if ! python3 "${SCRIPT_DIR}/apply_tile_retirements.py" --staging "${STAGING_DIR}"; then
    log_error "tile retirement の適用に失敗（publish を中止。current は変更されていない）"
    exit 1
fi
log_step "apply tile retirements (staging)"

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
log_step "normalize staging permission"

log_info "activating version via activate_version.py ..."
# CODEX P2B5-CX-006（第4ラウンド）対応: activate_version.pyがexit 3
# （EXIT_DURABILITY_UNKNOWN、currentは切替済みだが耐久性未確認）を返す
# ケースを、通常のexit 1（真の公開失敗）と区別して扱う必要がある。
# `set -e`の下では非0 exitで即座にscriptが終了してしまうため、この
# 呼び出しだけ一時的に無効化し、exit codeを明示的に分岐させる。
ACTIVATE_EXTRA_ARGS=()
if [[ -n "${FLOOD_MIGRATION_APPROVAL_REF}" ]]; then
    log_warn "flood routing migration を OWNER 承認参照付きで実行します: ${FLOOD_MIGRATION_APPROVAL_REF}"
    ACTIVATE_EXTRA_ARGS=(--allow-flood-routing-migration --owner-approval-ref "${FLOOD_MIGRATION_APPROVAL_REF}")
elif [[ "${FULL_REVALIDATE}" == "1" ]]; then
    log_info "validated-content reuse: disabled（--full-revalidate 指定。全 file を再検証する）"
else
    # VALIDATED-CONTENT-REUSE（既定）: 前 version と sha256・検証契約が同一の file は再検証しない。
    # 再利用できない条件では activate_version.py 側で自動的に全検証へ戻る（理由は log / manifest に記録）。
    log_info "validated-content reuse: enabled（既定。全検証は --full-revalidate）"
    ACTIVATE_EXTRA_ARGS=(--reuse-validated-content)
fi
set +e
python3 "${SCRIPT_DIR}/activate_version.py" \
    --data-runtime-root "${DATA_RUNTIME}" \
    --version-id "${VERSION_ID}" \
    "${ACTIVATE_EXTRA_ARGS[@]+"${ACTIVATE_EXTRA_ARGS[@]}"}"
ACTIVATE_EXIT_CODE=$?
set -e
log_step "activate_version.py (validate + manifest + swap)"

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

# RUNTIME-STATE-RECONCILE: CLI publish でも管理画面の DatasetState を実 runtime（current + manifest）へ
# 同期する。publish 自体は成功済みのため、同期の失敗は warning に留め exit code を変えない
# （次回 operator 起動・publish-status / dataset detail 参照時に再同期される）。
if python3 "${SCRIPT_DIR}/reconcile_dataset_state.py" --data-runtime-root "${DATA_RUNTIME}"; then
    log_info "DatasetState を実 runtime へ同期しました（current -> versions/${VERSION_ID}）"
else
    log_warn "DatasetState の同期に失敗または一部判定不能（publish は成功済み。operator 再起動・管理画面参照時に再同期されます）"
fi
log_step "reconcile dataset state"

# TILE-RETIREMENT / TILE-PATH-MIGRATION: mirror 同期（追加専用）の前に、退役 tile と移動前の旧 path を除く
# （current に無く、record の sha256 と一致する file だけ。同じ tileset_id が 2 か所に同時に存在する時間を作らない）。
# tile が別 directory へ移った場合、Martin 1.14.0 は再起動まで新 path を `<id>.1` として扱う（2026-10-11 実測）ため、
# MARTIN_RESTART_REQUIRED を出したら Martin を再起動する。publish 自体は成功済みのため失敗は warning に留める。
if [[ -z "${SKIP_FRONTEND_ARG}" ]]; then
    set +e
    _retire_out="$(python3 "${SCRIPT_DIR}/apply_tile_retirements.py" --mirror "${DATA_RUNTIME}" --current "${DATA_RUNTIME}/current" 2>&1)"
    _retire_rc=$?
    set -e
    printf '%s\n' "${_retire_out}"
    if [[ ${_retire_rc} -ne 0 ]]; then
        log_warn "mirror からの退役 tile・旧 path の除去に失敗（publish は成功済み。Data Ops の退役一覧で残存を確認すること）"
    elif grep -q "MARTIN_RESTART_REQUIRED" <<<"${_retire_out}"; then
        log_warn "MARTIN_RESTART_REQUIRED: tile の directory が変わったため Martin を再起動すること（docker restart evacuation-navi-martin）"
    fi
fi
log_step "apply tile retirements / migrations (mirror)"

if [[ -z "${SKIP_FRONTEND_ARG}" ]]; then
    # Finding 9（VPS in-place再構築 2026-09-06）: LAYERS post-publish flat mirror
    # syncは今回いったん無効化する。GeoJSON fallbackの実readerはnginxが配信する
    # git管理下の ./frontend/layers であり、backend-operatorにはrailways以外の
    # ./frontend/layers への書込みmountが存在しないため、このsync自体が実際の
    # 配信先へ到達しない（publish destination / serving path architecture gap
    # として別途追跡する）。atomic version内のcurrent/frontend/layers生成自体
    # （deploy_to_runtime.sh側）は維持し、post-publishのflat mirror syncのみを
    # 停止する。
    log_warn "frontend layers static fallback sync skipped: serving destination is not writable/reachable from backend-operator; tracked as Finding 9"

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
        # RUNTIME-MBTILES-GROUP-CONTRACT: 同期と permission contract（file
        # 10002:20001 0640 / dir 0750。backend-publicがmbtilesをsqliteで開けること）の
        # 保証は sync_frontend_tiles_mirror.sh に集約している。operator imageには
        # rsyncが無く、従来の`cp -r --remove-destination`はfileのgroupをoperatorの
        # primary gid（10002）にしてしまい、backend-publicがmbtilesを読めず
        # meta の tileset_source_layer が null になっていた。
        # 終了コード: 0=OK / 2=同期失敗（publish自体は成功済みのためwarning）/
        #             4=契約を満たせない（publish済みだがbackend-publicが読めない状態。要operator対応）
        set +e
        bash "${SCRIPT_DIR}/sync_frontend_tiles_mirror.sh" "${TILES_SRC}" "${TILES_DST}"
        MIRROR_EXIT_CODE=$?
        set -e
        if [[ "${MIRROR_EXIT_CODE}" -eq 0 ]]; then
            log_info "synced current/frontend/tiles -> data_runtime/frontend/tiles (Martin向けflat mirror)"
        elif [[ "${MIRROR_EXIT_CODE}" -eq 4 ]]; then
            log_error "current -> versions/${VERSION_ID} は既にactiveだが、flat mirrorのpermission contractを満たせていない。"
            log_error "backend-publicがmbtilesを読めず、meta APIのtileset_source_layerがnullになる。上記VIOLATIONを是正すること。"
            exit 4
        else
            log_warn "current/frontend/tiles -> data_runtime/frontend/tiles 同期に失敗（publish自体は成功済み。Martin向けmirror未整備の可能性、frontend/tiles配下のoperator write権限を確認すること）"
        fi
    fi
fi

log_step "frontend tile mirror sync"

log_info "=== deploy_to_runtime_atomic.sh done ==="
