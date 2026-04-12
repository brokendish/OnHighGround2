#!/usr/bin/env bash
# build_tiles_flood.sh — 洪水浸水想定区域 GeoJSON → MBTiles 変換
#
# 使い方:
#   build_tiles_flood.sh <INPUT_GEOJSON> <OUTPUT_MBTILES> <LAYER_NAME>
#
# 引数:
#   INPUT_GEOJSON   : 入力 GeoJSON ファイルパス（validated artifact）
#   OUTPUT_MBTILES  : 出力 .mbtiles ファイルパス
#   LAYER_NAME      : タイル内レイヤー名（例: flood）
#
# 設計方針:
#   - ズーム 5-16: 広域概観から街区レベルまでカバー
#   - drop-densest-as-needed: 低ズームでの過密を自動間引き（メモリ安全）
#   - detect-shared-borders: 隣接ポリゴン境界の重複頂点を共有（ファイルサイズ削減）
#   - 一時ファイルへ書き出し後に移動（書き込み中断しても既存ファイルを壊さない）
#
# 終了コード:
#   0 : 成功
#   1 : 引数不足
#   2 : 入力ファイルなし
#   3 : tippecanoe 未インストール
#  10 : tippecanoe 実行エラー

set -euo pipefail

INPUT="${1:-}"
OUTPUT="${2:-}"
LAYER_NAME="${3:-flood}"

# ── 引数チェック ──────────────────────────────────────────────────────────────
if [[ -z "$INPUT" || -z "$OUTPUT" ]]; then
    echo "[ERROR] 使い方: $(basename "$0") <INPUT_GEOJSON> <OUTPUT_MBTILES> [LAYER_NAME]" >&2
    exit 1
fi

if [[ ! -f "$INPUT" ]]; then
    echo "[ERROR] 入力ファイルが見つかりません: $INPUT" >&2
    exit 2
fi

if ! command -v tippecanoe &>/dev/null; then
    echo "[ERROR] tippecanoe がインストールされていません。" >&2
    echo "        macOS: brew install tippecanoe" >&2
    echo "        Linux: https://github.com/felt/tippecanoe" >&2
    exit 3
fi

# ── 出力ディレクトリ作成 ──────────────────────────────────────────────────────
mkdir -p "$(dirname "$OUTPUT")"

# ── 一時ファイルへビルド（アトミック置換のため）─────────────────────────────
TMP_OUTPUT="${OUTPUT}.tmp.mbtiles"
trap 'rm -f "$TMP_OUTPUT"' EXIT

INPUT_SIZE_MB=$(du -m "$INPUT" | cut -f1)
echo "[INFO] tile build 開始"
echo "       入力: $INPUT (${INPUT_SIZE_MB} MB)"
echo "       出力: $OUTPUT"
echo "       レイヤー名: $LAYER_NAME"
echo "       ズーム: 5-14"

tippecanoe \
    -o "$TMP_OUTPUT" \
    -l "$LAYER_NAME" \
    --minimum-zoom=5 \
    --maximum-zoom=14 \
    --drop-densest-as-needed \
    --force \
    "$INPUT"

# ── 既存ファイルをアトミックに置換 ───────────────────────────────────────────
mv "$TMP_OUTPUT" "$OUTPUT"

OUTPUT_SIZE_MB=$(du -m "$OUTPUT" | cut -f1)
echo "[INFO] tile build 完了: $OUTPUT (${OUTPUT_SIZE_MB} MB)"
