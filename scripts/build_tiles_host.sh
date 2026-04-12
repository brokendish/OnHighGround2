#!/usr/bin/env bash
# build_tiles_host.sh — ホスト Mac で Vector Tile を生成するスクリプト
#
# 使い方:
#   ./scripts/build_tiles_host.sh              # 全レイヤーをビルド
#   ./scripts/build_tiles_host.sh flood        # flood のみ
#   ./scripts/build_tiles_host.sh inland_flood # inland_flood のみ
#   ./scripts/build_tiles_host.sh storm_surge  # storm_surge のみ
#
# 背景:
#   tippecanoe はメモリを大量消費するため backend コンテナ内では OOM が発生する。
#   このスクリプトをホスト Mac 上で直接実行することで安定したタイル生成を実現する。
#   生成した .mbtiles は data_runtime/frontend/tiles/ に配置され、
#   Martin が docker compose restart martin で認識する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── 定数 ───────────────────────────────────────────────────────────────────
VALIDATED_BASE="${PROJECT_ROOT}/data_lake/validated/tokyo"
TILES_BASE="${PROJECT_ROOT}/data_runtime/frontend/tiles/tokyo"
MIN_ZOOM=5
MAX_ZOOM=14

# ── ユーティリティ ─────────────────────────────────────────────────────────
log()  { echo "[$(date -u '+%H:%M:%S')] $*"; }
warn() { echo "[$(date -u '+%H:%M:%S')] WARN: $*" >&2; }
die()  { echo "[$(date -u '+%H:%M:%S')] ERROR: $*" >&2; exit 1; }

check_tippecanoe() {
    if ! command -v tippecanoe &>/dev/null; then
        die "tippecanoe がインストールされていません。\n  macOS: brew install tippecanoe"
    fi
    log "tippecanoe: $(tippecanoe --version 2>&1 | head -1)"
}

build_layer() {
    local layer_name="$1"    # レイヤー名（tippecanoe -l に渡す）
    local input="$2"         # 入力 GeoJSON パス
    local output_dir="$3"    # 出力ディレクトリ
    local output_stem="$4"   # 出力ファイル名（stem）

    if [[ ! -f "$input" ]]; then
        warn "${layer_name}: 入力ファイルが見つかりません: ${input} → スキップ"
        return 0
    fi

    mkdir -p "$output_dir"
    local output="${output_dir}/${output_stem}.mbtiles"
    local tmp="${output}.tmp"

    local size_mb
    size_mb=$(du -m "$input" | cut -f1)
    log "${layer_name}: ビルド開始 (入力 ${size_mb}MB → zoom ${MIN_ZOOM}-${MAX_ZOOM})"

    tippecanoe \
        -o "$tmp" \
        -l "$layer_name" \
        --minimum-zoom="${MIN_ZOOM}" \
        --maximum-zoom="${MAX_ZOOM}" \
        --drop-densest-as-needed \
        --force \
        "$input"

    mv "$tmp" "$output"

    local out_mb
    out_mb=$(du -m "$output" | cut -f1)
    log "${layer_name}: 完了 → ${output} (${out_mb}MB)"
}

# ── レイヤー定義 ────────────────────────────────────────────────────────────
build_flood() {
    build_layer \
        "flood" \
        "${VALIDATED_BASE}/flood/tokyo-river-001.geojson" \
        "${TILES_BASE}/flood" \
        "tokyo_river_001"
}

build_inland_flood() {
    build_layer \
        "inland_flood" \
        "${VALIDATED_BASE}/inland_flood/tokyo-urban-001.geojson" \
        "${TILES_BASE}/inland_flood" \
        "tokyo_urban_001"
}

build_storm_surge() {
    # storm_surge は既存ファイルが zoom 5-16 で完成済みのためスキップ
    log "storm_surge: 既存 tokyo_storm_surge.mbtiles を使用（再ビルド不要）"
}

# ── メイン ─────────────────────────────────────────────────────────────────
main() {
    local target="${1:-all}"

    check_tippecanoe

    case "$target" in
        all)
            build_flood
            build_inland_flood
            build_storm_surge
            ;;
        flood)
            build_flood
            ;;
        inland_flood)
            build_inland_flood
            ;;
        storm_surge)
            build_storm_surge
            ;;
        *)
            die "不明なターゲット: ${target}\n  使い方: $0 [all|flood|inland_flood|storm_surge]"
            ;;
    esac

    log "全ビルド完了。Martin を再起動してタイルを反映させてください:"
    log "  docker compose restart martin"
}

main "$@"
