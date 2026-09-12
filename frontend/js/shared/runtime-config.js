'use strict';
/**
 * runtime-config.js — フロントエンド ランタイム設定の「配信ターゲット（tracked default）」
 *
 * このファイルは利用者が直接編集する設定ファイルではありません。役割は
 * 「デフォルト値の保持」と、旧方式（下記レガシー経路）でのローカル設定の
 * 配信先（bind-mount のマウント先）に限定します。リポジトリにはプレースホルダー
 * （空値）のみを置き、実際の API キーをこのファイルへ書き込んでコミットしないで
 * ください。
 *
 * 通常の設定方法（推奨・単一の入口）:
 *   1. cp .env.example .env
 *   2. .env の CARTO_BASEMAP_API_KEY に自分の値を設定する（Git 管理外）
 *   3. docker compose up -d frontend
 *      （起動時に scripts/frontend/generate_runtime_config.sh が
 *       window.OHG2_RUNTIME_CONFIG を生成して配信する。詳細は docs/configuration.md §8）
 *
 * レガシー経路（docker-compose.override.yml を既に使っている環境向け）:
 *   1. cp config/runtime-config.example.js config/runtime-config.local.js
 *   2. config/runtime-config.local.js に自分の値を設定する（Git 管理外）
 *   3. cp docker-compose.override.example.yml docker-compose.override.yml
 *      （Git 管理外。`docker compose` が自動でマージし、config/runtime-config.local.js を
 *       このファイルの位置へ read-only mount する）
 *   4. docker compose up -d frontend
 *   → `.env` の CARTO_BASEMAP_API_KEY が空の場合のみ、このファイルの内容が
 *     後方互換フォールバックとして使われる。
 *
 * ここで渡す値は CARTO タイルをブラウザが直接取得するために使われるため、実行時に
 * ブラウザから参照可能な公開設定値です（server-side secret ではありません）。
 * backend / operator / stream の secret は .env / .env.operator / .env.stream に
 * 置き、この経路へ混在させないでください。
 *
 * キー一覧:
 *   CARTO_BASEMAP_API_KEY
 *     /live・/live/stream の背景地図に使う CARTO Basemaps の API キー。
 *     取得: https://carto.com/basemaps/apikey/
 *     未設定・空・プレースホルダーの場合、背景地図はキー不要の
 *     OpenStreetMap ラスタタイル（/ トップ画面と同一）へ自動フォールバックする。
 */
(function (global) {
  var existing = (global.OHG2_RUNTIME_CONFIG && typeof global.OHG2_RUNTIME_CONFIG === 'object')
    ? global.OHG2_RUNTIME_CONFIG
    : {};
  var defaults = {
    CARTO_BASEMAP_API_KEY: '',
  };
  var merged = {};
  Object.keys(defaults).forEach(function (k) { merged[k] = defaults[k]; });
  Object.keys(existing).forEach(function (k) { merged[k] = existing[k]; });
  global.OHG2_RUNTIME_CONFIG = merged;
})(window);
