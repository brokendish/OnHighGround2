'use strict';
/**
 * runtime-config.example.js — ブラウザから参照可能なランタイム公開設定のテンプレート
 *
 * 使い方:
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
