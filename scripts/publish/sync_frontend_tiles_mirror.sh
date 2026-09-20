#!/usr/bin/env bash
# sync_frontend_tiles_mirror.sh
#
# RUNTIME-MBTILES-GROUP-CONTRACT: Martin向け flat mirror
# （data_runtime/frontend/tiles/<region>/<hazard>/*.mbtiles）の同期と、
# backend-public から読める permission contract の保証。
#
# 背景（実機で確認済みの root cause）:
#   backend-public（uid 10001、supplemental gid 20001）は
#   GET /api/hazards/{type}/{region}/meta の tileset 解決（hazards.py::
#   _find_tileset_for_region）で mbtiles を sqlite で開く。operator container
#   （uid 10002:10002、supplemental gid 20001、umask 0007）には rsync が無く、
#   従来の同期は `cp -r --remove-destination` に縮退していた。`cp -r` は
#   source の group を保持せず、新規作成ファイルの group を作成 process の
#   primary gid（10002）にする（directory は既存なら 20001 のまま）。結果、
#   flat mirror のファイルだけが 10002:10002 mode 0640 となり、Martin（root）は
#   配信できるが backend-public は sqlite を開けず、meta の
#   tileset_source_layer が null になっていた。
#
# 正式 permission contract（既存の init_data_runtime_backend.py が
# 「data_runtime/current 側の VPS 実機 stat 値の踏襲」として定義しているものと同一。
# setgid には依存せず、明示的な chgrp/chmod で保証する）:
#   file:      owner=operator(10002), group=leases_gid(20001), mode 0640
#   directory: owner=operator(10002), group=leases_gid(20001), mode 0750
#              （既存directoryが他ownerの場合は「public が traverse できる」ことを必須とする）
#
# 使い方（operator container 内、または同等の環境で）:
#   sync_frontend_tiles_mirror.sh <src_dir> <dst_dir>
#       src_dir の内容を dst_dir へ追加専用（--deleteなし）で同期し、
#       src に含まれる directory/file を契約どおりに正規化・検証する。
#   sync_frontend_tiles_mirror.sh --check <dst_dir>
#       READ ONLY。dst_dir 配下の全 directory/*.mbtiles が backend-public
#       から読めるかを検証する（何も変更しない）。
#
# 環境変数: OHG2_LEASES_GID（既定 20001）
#
# 終了コード:
#   0 = 成功（契約を満たしている）
#   2 = 同期自体に失敗（publish自体は成功済みの前提。呼び出し側は warning 扱い）
#   4 = 同期後の正規化・検証で契約を満たせない（backend-public が読めない状態）
#   1 = --check で backend-public から読めないものが見つかった

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common/log.sh"

umask 0007

LEASES_GID="${OHG2_LEASES_GID:-20001}"
FILE_MODE="640"
DIR_MODE="750"

# GNU coreutils（container）を第一に、BSD stat（開発機での単体テスト）へ縮退する。
_gid_mode() {
    stat -c '%g %a' "$1" 2>/dev/null || stat -f '%g %Lp' "$1"
}

# backend-public（uid=other, supplemental gid=LEASES_GID）から
# 読める（directory は traverse できる）か。$3 = "dir" | "file"
_public_can_access() {
    local path="$1" kind="$2" gm gid mode need_g need_o
    gm="$(_gid_mode "${path}")" || return 1
    gid="${gm%% *}"
    mode="${gm##* }"
    mode=$(( 8#${mode} ))
    if [[ "${kind}" == "dir" ]]; then
        need_g=$(( 8#050 )); need_o=$(( 8#005 ))   # r-x
    else
        need_g=$(( 8#040 )); need_o=$(( 8#004 ))   # r--
    fi
    if [[ "${gid}" == "${LEASES_GID}" ]] && (( (mode & need_g) == need_g )); then
        return 0
    fi
    (( (mode & need_o) == need_o ))
}

# path を LEASES_GID / want_mode へ揃える（setgid/setuid は明示的に落とす）。
# 揃った（または既に揃っている）場合に 0。
_normalize_exact() {
    local path="$1" want="$2"
    if [[ "$(_gid_mode "${path}" 2>/dev/null || true)" == "${LEASES_GID} ${want}" ]]; then
        return 0
    fi
    chgrp "${LEASES_GID}" "${path}" 2>/dev/null || true
    chmod g-s,u-s "${path}" 2>/dev/null || true
    chmod "${want}" "${path}" 2>/dev/null || true
    [[ "$(_gid_mode "${path}" 2>/dev/null || true)" == "${LEASES_GID} ${want}" ]]
}

_report_violation() {
    log_error "VIOLATION $1 (actual='$(_gid_mode "$2" 2>/dev/null || echo '?')' expected='${LEASES_GID} $3' kind=$4)"
}

# ── --check: READ ONLY 検証 ─────────────────────────────────────────────
if [[ "${1:-}" == "--check" ]]; then
    dst="${2:?usage: $0 --check <dst_dir>}"
    [[ -d "${dst}" ]] || { log_error "check対象が存在しない: ${dst}"; exit 1; }
    bad=0
    while IFS= read -r -d '' d; do
        if ! _public_can_access "${d}" dir; then
            log_error "NOT-TRAVERSABLE-BY-PUBLIC ${d} ($(_gid_mode "${d}" || echo '?'))"; bad=1
        fi
    done < <(find "${dst}" -type d -print0)
    while IFS= read -r -d '' f; do
        if ! _public_can_access "${f}" file; then
            log_error "NOT-READABLE-BY-PUBLIC ${f} ($(_gid_mode "${f}" || echo '?'))"; bad=1
        fi
    done < <(find "${dst}" -type f -name '*.mbtiles' -print0)
    if (( bad )); then exit 1; fi
    log_info "OK: ${dst} 配下の directory / *.mbtiles はすべて backend-public から読める（gid=${LEASES_GID}）"
    exit 0
fi

# ── 同期 + 正規化 + 検証 ────────────────────────────────────────────────
src="${1:?usage: $0 <src_dir> <dst_dir>}"
dst="${2:?usage: $0 <src_dir> <dst_dir>}"
src="${src%/}"
dst="${dst%/}"
[[ -d "${src}" ]] || { log_error "同期元が存在しない: ${src}"; exit 2; }

mkdir -p "${dst}" || { log_error "同期先を作成できない: ${dst}"; exit 2; }

# 追加専用の同期（--delete なし。旧世代ファイルを消さない）。
# operator image には rsync が無いため通常は cp 側を通る。--remove-destination は、
# Martin が open 中のファイルを in-place で書き換えないための unlink+create。
# 注意: `cp -a` は使わない。-a は既存 directory の timestamp 保持（utime）まで試みるため、
# operator 所有でない既存 directory があると同期自体が失敗する（従来の `cp -r` は成功していた）。
# group/mode の保証はコピー方法に依存させず、下の明示的な正規化で行う。
if command -v rsync &>/dev/null; then
    rsync -a "${src}/" "${dst}/" || { log_warn "rsync 同期に失敗: ${src} -> ${dst}"; exit 2; }
else
    cp -r --remove-destination "${src}/." "${dst}/" || { log_warn "cp 同期に失敗: ${src} -> ${dst}"; exit 2; }
fi

# コピー方法（cp/rsync、umask）に依存しない明示的な正規化。
# 対象は「今回 source に含まれていた directory/file」のみ（inventory-based、
# 無関係な既存ファイルには触れない）。
violations=0
while IFS= read -r -d '' f; do
    rel="${f#"${src}"/}"
    if ! _normalize_exact "${dst}/${rel}" "${FILE_MODE}"; then
        _report_violation "file" "${dst}/${rel}" "${FILE_MODE}" "file"; violations=$((violations + 1))
    fi
done < <(find "${src}" -type f -print0)

# directory: 正規形（0750/leases）へ揃える。既存directoryが他ownerで揃えられない場合は、
# public が traverse できれば許容し（情報として warn）、できなければ違反。
while IFS= read -r -d '' d; do
    rel="${d#"${src}"}"; rel="${rel#/}"
    target="${dst}${rel:+/${rel}}"
    if ! _normalize_exact "${target}" "${DIR_MODE}"; then
        if _public_can_access "${target}" dir; then
            log_warn "directory が正規形（${LEASES_GID} ${DIR_MODE}）ではないが public は traverse 可: ${target} ($(_gid_mode "${target}"))"
        else
            _report_violation "dir" "${target}" "${DIR_MODE}" "dir"; violations=$((violations + 1))
        fi
    fi
done < <(find "${src}" -type d -print0)

# 親 directory（data_runtime/frontend。従来 deploy_to_runtime.sh の frontend root 正規化は
# staging 側を指すため、実際の flat mirror root はどこからも正規化されていなかった）。
parent="$(dirname "${dst}")"
if [[ "$(basename "${parent}")" == "frontend" ]]; then
    if ! _normalize_exact "${parent}" "${DIR_MODE}" && ! _public_can_access "${parent}" dir; then
        _report_violation "frontend-root" "${parent}" "${DIR_MODE}" "dir"; violations=$((violations + 1))
    fi
fi

# 診断（警告のみ）: source 由来ではない既存の *.mbtiles で public から読めないもの
# （手動配置・旧世代・rsync 持ち込み等）。tileset_source_layer が null になる原因になる。
while IFS= read -r -d '' f; do
    if ! _public_can_access "${f}" file; then
        log_warn "backend-public から読めない既存 mbtiles（tileset_source_layer が null になる）: ${f} ($(_gid_mode "${f}" || echo '?'))"
    fi
done < <(find "${dst}" -type f -name '*.mbtiles' -print0)

if (( violations > 0 )); then
    log_error "flat mirror の permission contract を満たせない項目が ${violations} 件ある（backend-public から読めない）。"
    log_error "current は既に有効。operator は上記 VIOLATION の owner/group を確認し、是正後に再度 publish すること。"
    exit 4
fi
log_info "flat mirror permission contract OK: ${dst}（file ${LEASES_GID}:${FILE_MODE} / dir ${LEASES_GID}:${DIR_MODE}）"
