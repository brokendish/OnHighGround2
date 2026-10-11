#!/usr/bin/env bash
# rollback_runtime.sh — version rollback と Martin 用 tile mirror の整合を 1 手順で行う（TILE-AWARE-ROLLBACK）。
#
# 使い方（operator コンテナ内）:
#   scripts/publish/rollback_runtime.sh <version-id>
#   scripts/publish/rollback_runtime.sh <version-id> --allow-missing-required-tiles   # 緊急時専用
#
# REQUIRED-TILE-ROLLBACK-GUARD: current 切替前に rollback_preflight.py が、rollback 先 version の manifest と
# dataset registry の tile 契約（tile_requirement）から、表示に必須（required）の tile が rollback 先に揃って
# いるかを判定する。欠けていれば rollback を拒否する（current・mirror・state は一切変更しない）。
# version の新旧ではなく tile 契約で自動判定する。optional tile の欠落は WARNING のみで許可する。
# --allow-missing-required-tiles は緊急時専用で、欠ける dataset・tile path・target を WARNING として出力する。
#
# activate_version.py --rollback は current symlink だけを戻す。mirror（data_runtime/frontend/tiles）は
# publish 時の追加専用同期でしか更新されないため、rollback しても退役 tile は戻らず、差し替え前の tile にも
# 戻らなかった。本手順は rollback 先 version の manifest を正として mirror を合わせる。
#
# 順序（失敗時に「current だけ戻った / mirror は新しいまま」を残さない）:
#   0. preflight required tile の有無（REQUIRED-TILE-ROLLBACK-GUARD）。欠落・判定不能なら中止
#   1. plan     rollback 先 version の tile と mirror の差分（変更なし）。version が無い・manifest 不正なら中止
#   2. prepare  ADD/REPLACE する file を mirror 内の一時名へ用意し sha256 検証（失敗なら中止。current・mirror 不変）
#   3. switch   activate_version.py --rollback（manifest と disk の再照合を含む）。失敗なら一時 file を消して中止
#   4. commit   一時 file を atomic rename、旧 tile を削除（commit point。失敗しても再実行で収束する）
#   5. state    DatasetState を新 current へ同期
#   6. verify   mirror と version manifest の path / sha256 / mode / group の一致を確認
# 終了コード: 0=成功 / 1=失敗（current 未変更）/ 3=current は切替済みだが mirror 未収束（再実行で収束）/
#             5=成功だが Martin の再起動が必要（同じ tileset_id の tile が別 directory へ移った。
#               Martin 1.14.0 は再起動まで `<id>.1` として扱い、元の id で配信しない）
set -euo pipefail
umask 0007

VERSION_ID=""
ALLOW_MISSING_REQUIRED=0
for arg in "$@"; do
    case "${arg}" in
        --allow-missing-required-tiles) ALLOW_MISSING_REQUIRED=1 ;;
        -*) echo "Unknown option: ${arg}" >&2; exit 1 ;;
        *) [[ -n "${VERSION_ID}" ]] && { echo "version-id は 1 つだけ指定する" >&2; exit 1; }; VERSION_ID="${arg}" ;;
    esac
done
[[ -n "${VERSION_ID}" ]] || { echo "usage: rollback_runtime.sh <version-id> [--allow-missing-required-tiles]" >&2; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"
DATA_RUNTIME="${OHG2_DATA_RUNTIME_ROOT:-${PROJECT_ROOT}/data_runtime}"  # 既定は repo の data_runtime（operator では /data_runtime）
RECONCILE=(python3 "${SCRIPT_DIR}/reconcile_tile_mirror.py" --data-runtime-root "${DATA_RUNTIME}" --version "${VERSION_ID}")

log_info "=== rollback_runtime.sh: -> ${VERSION_ID}（current: $(readlink "${DATA_RUNTIME}/current" 2>/dev/null || echo none)）==="

PREFLIGHT=(python3 "${SCRIPT_DIR}/rollback_preflight.py" --data-runtime-root "${DATA_RUNTIME}" --version "${VERSION_ID}")
[[ "${ALLOW_MISSING_REQUIRED}" == "1" ]] && PREFLIGHT+=(--allow-missing-required-tiles)
set +e
"${PREFLIGHT[@]}"; rc=$?
set -e
if [[ ${rc} -eq 4 ]]; then
    log_error "rollback を拒否: rollback 先 ${VERSION_ID} に表示必須（required）の tile が無い（current・mirror は変更していない）"
    log_error "緊急時に限り --allow-missing-required-tiles で許可できる（該当 layer は表示できなくなる）"
    exit 1
elif [[ ${rc} -ne 0 ]]; then
    log_error "rollback preflight が判定できない（rollback を中止。current・mirror は変更していない）"; exit 1
fi
[[ "${ALLOW_MISSING_REQUIRED}" == "1" ]] && log_warn "--allow-missing-required-tiles 指定: required tile の欠落を許可して rollback する"

set +e
PLAN="$("${RECONCILE[@]}" --plan)"; rc=$?
set -e
if [[ ${rc} -eq 1 ]]; then
    log_error "tile mirror の計画を作れない（rollback を中止。current は変更していない）"; exit 1
fi
log_info "tile mirror plan: $(python3 -c 'import json,sys; print(json.load(sys.stdin)["summary"])' <<<"${PLAN}")"
[[ ${rc} -eq 2 ]] && log_warn "素性を確認できない mirror file は削除せず残す（plan の UNKNOWN を確認すること）"

if ! "${RECONCILE[@]}" --prepare; then
    log_error "tile mirror の準備に失敗（rollback を中止。current・mirror は変更していない）"; exit 1
fi

set +e
python3 "${SCRIPT_DIR}/activate_version.py" --data-runtime-root "${DATA_RUNTIME}" --rollback "${VERSION_ID}"
rc=$?
set -e
if [[ ${rc} -ne 0 ]]; then
    python3 -c "import sys; sys.path.insert(0, '${SCRIPT_DIR}'); import reconcile_tile_mirror as r; from pathlib import Path; r.cleanup(Path('${DATA_RUNTIME}'))"
    log_error "activate_version.py --rollback が失敗（exit ${rc}）。一時 file を消した。current・mirror は変更していない"; exit 1
fi

MARTIN_RESTART_REQUIRED=0
set +e
"${RECONCILE[@]}" --commit; rc=$?
set -e
if [[ ${rc} -eq 5 ]]; then
    MARTIN_RESTART_REQUIRED=1
elif [[ ${rc} -ne 0 && ${rc} -ne 2 ]]; then
    log_error "current は ${VERSION_ID} へ切替済みだが mirror の反映が未完了。'${RECONCILE[*]} --apply' で再実行すると収束する"
    exit 3
fi

if python3 "${SCRIPT_DIR}/reconcile_dataset_state.py" --data-runtime-root "${DATA_RUNTIME}"; then
    log_info "DatasetState を実 runtime へ同期しました"
else
    log_warn "DatasetState の同期に失敗または一部判定不能（rollback 自体は完了）"
fi

if ! "${RECONCILE[@]}" --verify; then
    log_error "mirror と version manifest が一致しない（上の problems を確認。'${RECONCILE[*]} --apply' で再実行できる）"
    exit 3
fi
log_info "=== rollback_runtime.sh done: current -> versions/${VERSION_ID}、tile mirror は manifest と一致 ==="
if [[ "${MARTIN_RESTART_REQUIRED}" == "1" ]]; then
    log_warn "MARTIN_RESTART_REQUIRED: tile の directory が変わったため、Martin を再起動するまで該当 tileset は元の id で配信されない（docker restart evacuation-navi-martin）"
    exit 5
fi
