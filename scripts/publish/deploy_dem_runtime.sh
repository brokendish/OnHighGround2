#!/usr/bin/env bash
# deploy_dem_runtime.sh — atomic version の外に置く DEM（flat runtime: data_runtime/backend/elevation/elevation.tif）を
# 安全に置き換える / 戻す（DEM-RUNTIME-REPAIR、2026-10-12）。
#
# DEM は backend-public が起動時に読み込む。置き換えは「同じ directory へ staging → sha256 照合 → 旧 file を
# superseded 名で残す（削除しない）→ rename で切替」の順に行うので、途中状態の file は elevation.tif に現れない。
# 切替後に backend-public を再起動すると新しい DEM が読まれる（再起動するまでは旧 DEM を保持したまま動く）。
#
#   deploy_dem_runtime.sh install  <新 DEM> <期待する sha256> <runtime の elevation directory>
#   deploy_dem_runtime.sh rollback <runtime の elevation directory> <戻す DEM の sha256>
set -euo pipefail

sha() { (sha256sum "$1" 2>/dev/null || shasum -a 256 "$1") | cut -c1-64; }
die() { echo "ERROR: $*" >&2; exit 2; }

keep_current() {  # 現在の elevation.tif を superseded 名で残す（同じ sha の控えがあれば作らない）
    local dir="$1" cur="$1/elevation.tif"
    [ -f "${cur}" ] || return 0
    local s; s="$(sha "${cur}")"
    local keep="${dir}/elevation.tif.superseded-${s:0:12}"
    if [ ! -f "${keep}" ]; then
        ln "${cur}" "${keep}" 2>/dev/null || cp -p "${cur}" "${keep}"
    fi
    [ "$(sha "${keep}")" = "${s}" ] || die "superseded copy の sha256 が一致しない: ${keep}"
    echo "kept: ${keep}"
}

switch_to() {  # $1=directory $2=入れる file $3=期待 sha256
    local dir="$1" src="$2" want="$3"
    local stage="${dir}/.elevation.tif.staging-${want:0:12}"
    cp -p "${src}" "${stage}"
    [ "$(sha "${stage}")" = "${want}" ] || { mv -f "${stage}" "${stage}.bad"; die "staging の sha256 が一致しない: ${stage}.bad"; }
    keep_current "${dir}"
    mv -f "${stage}" "${dir}/elevation.tif"
    [ "$(sha "${dir}/elevation.tif")" = "${want}" ] || die "切替後の sha256 が一致しない"
    echo "active: ${dir}/elevation.tif sha256=${want}"
}

case "${1:-}" in
    install)
        [ $# -eq 4 ] || die "usage: $0 install <新 DEM> <期待する sha256> <elevation directory>"
        new="$2"; want="$3"; dir="$4"
        [[ "${want}" =~ ^[0-9a-f]{64}$ ]] || die "sha256 は 64 桁の小文字 hex"
        [ -f "${new}" ] || die "新 DEM が無い: ${new}"
        [ -d "${dir}" ] || die "directory が無い: ${dir}"
        [ "$(sha "${new}")" = "${want}" ] || die "新 DEM の sha256 が期待値と一致しない"
        switch_to "${dir}" "${new}" "${want}"
        echo "rollback: $0 rollback ${dir} <旧 DEM の sha256>"
        ;;
    rollback)
        [ $# -eq 3 ] || die "usage: $0 rollback <elevation directory> <戻す DEM の sha256>"
        dir="$2"; want="$3"
        [[ "${want}" =~ ^[0-9a-f]{64}$ ]] || die "sha256 は 64 桁の小文字 hex"
        keep="${dir}/elevation.tif.superseded-${want:0:12}"
        [ -f "${keep}" ] || die "戻す DEM の控えが無い: ${keep}"
        switch_to "${dir}" "${keep}" "${want}"
        ;;
    *)
        die "usage: $0 install|rollback ..."
        ;;
esac
