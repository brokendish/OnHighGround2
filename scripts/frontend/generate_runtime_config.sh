#!/bin/sh
# generate_runtime_config.sh — frontend コンテナ起動時に window.OHG2_RUNTIME_CONFIG
# （ブラウザ向けランタイム公開設定）を生成する。
#
# 配置契約: frontend service の /docker-entrypoint.d/ へ read-only mount する
# （公式 nginx image の docker-entrypoint.sh が起動時に自動実行する）。
# nginx の command/entrypoint は変更しない。
#
# 出力先は frontend root（./frontend、read-only bind mount）の外側にある
# コンテナ自身の書き込み可能な layer（/run/ohg2/）とし、nginx.conf の
# `location = /js/shared/runtime-config.js` がそこへ alias する
# （frontend root への書き込みは一切行わない）。
#
# 値の優先順位:
#   1. .env の CARTO_BASEMAP_API_KEY（新方式・単一の設定入口）
#   2. 旧方式（config/runtime-config.local.js を docker-compose.override.yml で
#      /usr/share/nginx/html/js/shared/runtime-config.js へ bind mount）が
#      既に設定した値。1 が空の場合のみ、そのファイルから直接読み取って
#      後方互換のフォールバックとして使う。
#   3. どちらも無ければ空文字（OSM フォールバック。フロント側の既存ロジックが
#      判定する。本スクリプトはここでは placeholder 判定をしない）。
#
# 実行時に失敗しても frontend コンテナの起動を止めない（exit は常に 0）。

TEMPLATE=/etc/ohg2/runtime-config.template.js
LEGACY_SOURCE=/usr/share/nginx/html/js/shared/runtime-config.js
OUT_DIR=/run/ohg2
OUT_FILE="$OUT_DIR/runtime-config.js"

# CARTO_BASEMAP_API_KEY はブラウザへ直接埋め込まれる公開設定値であり、
# 単純な shell 文字列連結で任意文字列を JS 文字列リテラルへそのまま
# 埋め込むと injection の危険がある。想定される CARTO API キーの文字種
# （英数字・ドット・アンダースコア・ハイフン）のみを許可し、それ以外の
# 文字が含まれる値は安全側で「未設定」（空文字 = OSM フォールバック）扱いにする。
sanitize_key() {
  v="$1"
  case "$v" in
    *[!A-Za-z0-9._-]*) printf '' ;;
    *) printf '%s' "$v" ;;
  esac
}

# 旧方式の runtime-config.js（tracked default、または override.yml が
# 差し込んだ実ファイルのいずれか）から CARTO_BASEMAP_API_KEY の値を1つだけ
# 抜き出す。ファイルの実行や require は行わず、テキストとして読むだけ。
extract_legacy_key() {
  f="$1"
  [ -f "$f" ] || return 0
  sed -n "s/.*CARTO_BASEMAP_API_KEY[[:space:]]*:[[:space:]]*['\"]\\([^'\"]*\\)['\"].*/\\1/p" "$f" 2>/dev/null | head -n1
}

if [ ! -f "$TEMPLATE" ]; then
  echo "runtime-config: template $TEMPLATE not found, skipping generation" >&2
  exit 0
fi

env_key="$(sanitize_key "${CARTO_BASEMAP_API_KEY:-}")"

if [ -n "$env_key" ]; then
  key="$env_key"
  source_desc=".env"
else
  legacy_raw="$(extract_legacy_key "$LEGACY_SOURCE")"
  legacy_key="$(sanitize_key "${legacy_raw:-}")"
  if [ -n "$legacy_key" ]; then
    key="$legacy_key"
    source_desc="legacy override ($LEGACY_SOURCE)"
  else
    key=""
    source_desc="none"
  fi
fi

mkdir -p "$OUT_DIR"
if CARTO_BASEMAP_API_KEY="$key" envsubst '${CARTO_BASEMAP_API_KEY}' < "$TEMPLATE" > "$OUT_FILE.tmp" 2>/dev/null \
    && mv "$OUT_FILE.tmp" "$OUT_FILE" 2>/dev/null; then
  if [ -n "$key" ]; then
    echo "runtime-config: generated $OUT_FILE (CARTO_BASEMAP_API_KEY set, source: $source_desc)"
  else
    echo "runtime-config: generated $OUT_FILE (CARTO_BASEMAP_API_KEY empty — OSM fallback)"
  fi
else
  echo "runtime-config: failed to write $OUT_FILE (unexpected — $OUT_DIR should be writable)" >&2
fi

exit 0
