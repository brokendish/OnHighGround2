#!/usr/bin/env bash
# rollback_runtime.sh — version rollback と Martin 用 tile mirror の整合を 1 手順で行う（TILE-AWARE-ROLLBACK）。
#
# 使い方（operator コンテナ内）:
#   scripts/publish/rollback_runtime.sh <version-id>
#
# activate_version.py --rollback は current symlink だけを戻す。mirror（data_runtime/frontend/tiles）は
# publish 時の追加専用同期でしか更新されないため、rollback しても退役 tile は戻らず、差し替え前の tile にも
# 戻らなかった。本手順は rollback 先 version の manifest を正として mirror を合わせる。
#
# 順序（失敗時に「current だけ戻った / mirror は新しいまま」を残さない）:
#   1. plan     rollback 先 version の tile と mirror の差分（変更なし）。version が無い・manifest 不正なら中止
#   2. prepare  ADD/REPLACE する file を mirror 内の一時名へ用意し sha256 検証（失敗なら中止。current・mirror 不変）
#   3. switch   activate_version.py --rollback（manifest と disk の再照合を含む）。失敗なら一時 file を消して中止
#   4. commit   一時 file を atomic rename、旧 tile を削除（commit point。失敗しても再実行で収束する）
#   5. state    DatasetState を新 current へ同期
#   6. verify   mirror と version manifest の path / sha256 / mode / group の一致を確認
# 終了コード: 0=成功 / 1=失敗（current 未変更）/ 3=current は切替済みだが mirror 未収束（再実行で収束）
set -euo pipefail
umask 0007

VERSION_ID="${1:?usage: rollback_runtime.sh <version-id>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/scripts/common/log.sh"
DATA_RUNTIME="${OHG2_DATA_RUNTIME_ROOT:-${PROJECT_ROOT}/data_runtime}"  # 既定は repo の data_runtime（operator では /data_runtime）
RECONCILE=(python3 "${SCRIPT_DIR}/reconcile_tile_mirror.py" --data-runtime-root "${DATA_RUNTIME}" --version "${VERSION_ID}")

log_info "=== rollback_runtime.sh: -> ${VERSION_ID}（current: $(readlink "${DATA_RUNTIME}/current" 2>/dev/null || echo none)）==="

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

if ! "${RECONCILE[@]}" --commit; then
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
