#!/usr/bin/env bash
# build_tiles_host.sh — ホスト Mac で Vector Tile を生成するスクリプト
#
# 使い方:
#   ./scripts/build_tiles_host.sh                         # 全リージョン・全レイヤー
#   ./scripts/build_tiles_host.sh --region kanagawa       # kanagawa 全レイヤー
#   ./scripts/build_tiles_host.sh --region tokyo flood    # tokyo flood のみ
#   ./scripts/build_tiles_host.sh flood                   # (後方互換) tokyo flood
#   ./scripts/build_tiles_host.sh inland_flood            # (後方互換) tokyo inland_flood
#   ./scripts/build_tiles_host.sh storm_surge             # (後方互換) tokyo storm_surge
#
# 背景:
#   tippecanoe はメモリを大量消費するため backend コンテナ内では OOM が発生する。
#   このスクリプトをホスト Mac 上で直接実行することで安定したタイル生成を実現する。
#   生成した .mbtiles は data_runtime/frontend/tiles/ に配置され、
#   Martin が docker compose restart martin で認識する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
    local min_zoom="${5:-${MIN_ZOOM}}"
    local max_zoom="${6:-${MAX_ZOOM}}"

    if [[ ! -f "$input" ]]; then
        warn "${layer_name}: 入力ファイルが見つかりません: ${input} → スキップ"
        return 0
    fi

    mkdir -p "$output_dir"
    local output="${output_dir}/${output_stem}.mbtiles"
    local tmp="${output}.tmp"

    local size_mb
    size_mb=$(du -m "$input" | cut -f1)
    log "${layer_name}: ビルド開始 (入力 ${size_mb}MB → zoom ${min_zoom}-${max_zoom})"

    tippecanoe \
        -o "$tmp" \
        -l "$layer_name" \
        --minimum-zoom="${min_zoom}" \
        --maximum-zoom="${max_zoom}" \
        --drop-densest-as-needed \
        --force \
        "$input"

    mv "$tmp" "$output"

    local out_mb
    out_mb=$(du -m "$output" | cut -f1)
    log "${layer_name}: 完了 → ${output} (${out_mb}MB)"
}

# ── Tokyo レイヤー定義 ───────────────────────────────────────────────────────
MIN_ZOOM=5
MAX_ZOOM=14

build_tokyo_flood() {
    build_layer \
        "flood" \
        "${PROJECT_ROOT}/data_lake/validated/tokyo/flood/tokyo-river-001.geojson" \
        "${PROJECT_ROOT}/data_runtime/frontend/tiles/tokyo/flood" \
        "tokyo_river_001"
}

build_tokyo_inland_flood() {
    build_layer \
        "inland_flood" \
        "${PROJECT_ROOT}/data_lake/validated/tokyo/inland_flood/tokyo-urban-001.geojson" \
        "${PROJECT_ROOT}/data_runtime/frontend/tiles/tokyo/inland_flood" \
        "tokyo_urban_001"
}

build_tokyo_storm_surge() {
    # sourceLayer 命名ルール統一: -l storm_surge（セマンティック名）で再ビルド
    build_layer \
        "storm_surge" \
        "${PROJECT_ROOT}/data_lake/normalized/tokyo/storm_surge/tokyo_storm_surge.geojson" \
        "${PROJECT_ROOT}/data_runtime/frontend/tiles/tokyo/storm_surge" \
        "tokyo_storm_surge" \
        5 16
}

# ── Kanagawa レイヤー定義 ───────────────────────────────────────────────────
build_kanagawa_flood() {
    build_layer \
        "flood" \
        "${PROJECT_ROOT}/data_lake/normalized/kanagawa/flood/kanagawa_flood_max.geojson" \
        "${PROJECT_ROOT}/data_runtime/frontend/tiles/kanagawa/flood" \
        "kanagawa_flood_max"
}

build_kanagawa_inland_flood() {
    build_layer \
        "inland_flood" \
        "${PROJECT_ROOT}/data_lake/normalized/kanagawa/inland_flood/kanagawa-urban-001.geojson" \
        "${PROJECT_ROOT}/data_runtime/frontend/tiles/kanagawa/inland_flood" \
        "kanagawa_urban_001"
}

build_kanagawa_storm_surge() {
    build_layer \
        "storm_surge" \
        "${PROJECT_ROOT}/data_lake/normalized/kanagawa/storm_surge/kanagawa_storm_surge.geojson" \
        "${PROJECT_ROOT}/data_runtime/frontend/tiles/kanagawa/storm_surge" \
        "kanagawa_storm_surge" \
        5 16
}

# ── メイン ─────────────────────────────────────────────────────────────────
main() {
    # 引数パース: --region REGION [target]
    local region="tokyo"
    local positional=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --region) region="$2"; shift 2 ;;
            *) positional+=("$1"); shift ;;
        esac
    done

    local target="${positional[0]:-all}"

    check_tippecanoe

    case "${region}" in
        tokyo)
            case "$target" in
                all)
                    build_tokyo_flood
                    build_tokyo_inland_flood
                    build_tokyo_storm_surge
                    ;;
                flood)        build_tokyo_flood ;;
                inland_flood) build_tokyo_inland_flood ;;
                storm_surge)  build_tokyo_storm_surge ;;
                *)
                    die "不明なターゲット: ${target}\n  使い方: $0 [--region REGION] [all|flood|inland_flood|storm_surge]"
                    ;;
            esac
            ;;
        kanagawa)
            case "$target" in
                all)
                    build_kanagawa_flood
                    build_kanagawa_inland_flood
                    build_kanagawa_storm_surge
                    ;;
                flood)        build_kanagawa_flood ;;
                inland_flood) build_kanagawa_inland_flood ;;
                storm_surge)  build_kanagawa_storm_surge ;;
                *)
                    die "不明なターゲット: ${target}\n  使い方: $0 --region kanagawa [all|flood|inland_flood|storm_surge]"
                    ;;
            esac
            ;;
        *)
            die "不明なリージョン: ${region}\n  対応リージョン: tokyo, kanagawa"
            ;;
    esac

    log "全ビルド完了。Martin を再起動してタイルを反映させてください:"
    log "  docker compose restart martin"
}

main "$@"
