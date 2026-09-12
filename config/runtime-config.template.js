'use strict';
/**
 * runtime-config.template.js — .env の CARTO_BASEMAP_API_KEY から
 * ブラウザ向けランタイム公開設定を生成するための envsubst テンプレート（tracked）。
 *
 * 直接ブラウザへ配信されるファイルではない。frontend コンテナ起動時に
 * scripts/frontend/generate_runtime_config.sh が envsubst でこのファイルを
 * 読み込み、下記オブジェクト内のプレースホルダーを実際の値へ置換した結果を
 * /run/ohg2/runtime-config.js（nginx が /js/shared/runtime-config.js として
 * 配信する alias 先）へ書き込む。
 *
 * 注意: envsubst はファイル全体に対して単純なテキスト置換を行うため、
 * このコメント欄にプレースホルダーと同じ記法（波括弧内に変数名）を
 * そのまま書かないこと（意図せず置換されてしまう）。
 *
 * このファイル自体には実値を書かない（プレースホルダーのみ）。
 */
window.OHG2_RUNTIME_CONFIG = {
  CARTO_BASEMAP_API_KEY: '${CARTO_BASEMAP_API_KEY}',
};
