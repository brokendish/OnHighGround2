'use strict';
/**
 * runtime-config.example.js — ブラウザから参照可能なランタイム公開設定の
 * 【レガシー / 上級者向け override】テンプレート
 *
 * 通常はこのファイルを使う必要はありません。CARTO_BASEMAP_API_KEY は
 * リポジトリroot直下の `.env`（`.env.example` をコピーして作成）に
 * 設定するだけで有効になります。詳細は docs/configuration.md §8。
 *
 *   cp .env.example .env
 *   vi .env    # CARTO_BASEMAP_API_KEY=... を設定
 *   docker compose up -d frontend
 *
 * このファイルは、`.env` とは別に docker-compose.override.yml 経由で
 * frontend コンテナへ直接ファイルを差し込みたい場合にのみ使う後方互換の
 * 経路です（`.env` の CARTO_BASEMAP_API_KEY が空の場合のフォールバックとして
 * 読まれます）。新規セットアップではこの手順を使わないでください。
 *
 * 使い方（レガシー）:
 *   cp config/runtime-config.example.js config/runtime-config.local.js
 *   # config/runtime-config.local.js に自分の値を設定する（Git 管理外）
 *   cp docker-compose.override.example.yml docker-compose.override.yml
 *   docker compose up -d frontend
 *
 * ここに置くのは「最終的にブラウザから参照可能でも許容される公開設定値」だけです。
 * backend / operator / stream の secret（`.env` / `.env.operator` / `.env.stream`）は
 * ここに入れないでください。
 *
 * このファイル（example）には実値を書かないこと。実値は config/runtime-config.local.js
 * にのみ書き、コミットしないでください。
 */
window.OHG2_RUNTIME_CONFIG = {
  // CARTO Basemaps の API キー（/live・/live/stream の背景地図用）。
  // 取得: https://carto.com/basemaps/apikey/
  // 未設定・空・プレースホルダーの場合は、キー不要の OpenStreetMap タイルへ
  // 自動フォールバックする（アプリの起動には影響しない）。
  CARTO_BASEMAP_API_KEY: '',
};
