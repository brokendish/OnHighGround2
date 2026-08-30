'use strict';
/**
 * basemap.js — /live・/live/stream 共通の背景地図（base tile layer）生成ヘルパー
 *
 * CARTO Basemaps は API キーが必須化された（2026-08）。キーが設定されていれば
 * CARTO dark_all を key 付きで使用し、未設定・空・プレースホルダーの場合は
 * キー不要の OpenStreetMap ラスタタイル（/ トップ画面と同一プロバイダー）へ
 * フォールバックする。
 *
 * キー未設定時に CARTO へ無効リクエスト（?key= が空・undefined・null 等）を
 * 送らないため、キーが有効なときだけ CARTO の L.tileLayer を生成する。
 *
 * 設定値は window.OHG2_RUNTIME_CONFIG.CARTO_BASEMAP_API_KEY から読む
 * （runtime-config.js を本スクリプトより前に読み込むこと）。
 */
(function (global) {
  var PLACEHOLDER_KEYS = [
    'your_key', 'your_carto_api_key', 'your-carto-api-key', 'yourkey',
    'changeme', 'change_me', 'replace_me', 'replaceme', 'placeholder',
    'xxx', 'xxxx', 'todo', 'example', 'none',
  ];

  var CARTO_TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
  var OSM_TILE_URL   = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';

  /** 有効な CARTO API キー文字列を返す。無効（未設定・空・空白のみ・
   *  プレースホルダー）の場合は空文字を返す。 */
  function readCartoApiKey() {
    var cfg = global.OHG2_RUNTIME_CONFIG;
    var raw = (cfg && typeof cfg === 'object') ? cfg.CARTO_BASEMAP_API_KEY : undefined;
    if (raw === undefined || raw === null) return '';
    var v = String(raw).trim();
    if (v === '') return '';
    if (PLACEHOLDER_KEYS.indexOf(v.toLowerCase()) !== -1) return '';
    return v;
  }

  /** CARTO の背景地図が使える（有効キーがある）かどうか。 */
  function hasCartoApiKey() {
    return readCartoApiKey() !== '';
  }

  /**
   * base tile layer を生成して返す（map への addTo は呼び出し側で行う）。
   *
   * @param {object} L  Leaflet ライブラリ
   * @param {object} [opts]
   * @param {number} [opts.maxZoom=19]
   * @param {number} [opts.opacity]           指定時のみ layer options に渡す
   * @param {number} [opts.zIndex]            指定時のみ layer options に渡す
   * @param {string} [opts.cartoAttribution]  CARTO 使用時の attribution 文字列
   * @param {string} [opts.osmAttribution]    フォールバック時の attribution 文字列
   * @returns {{ layer: object, provider: 'carto'|'osm' }}
   */
  function createBaseLayer(L, opts) {
    var o = opts || {};
    var key = readCartoApiKey();
    var provider = key ? 'carto' : 'osm';

    var tileOptions = { maxZoom: o.maxZoom || 19 };
    if (typeof o.opacity === 'number') tileOptions.opacity = o.opacity;
    if (typeof o.zIndex === 'number') tileOptions.zIndex = o.zIndex;

    var url;
    if (provider === 'carto') {
      url = CARTO_TILE_URL + '?key=' + encodeURIComponent(key);
      tileOptions.subdomains = 'abcd';
      if (o.cartoAttribution) tileOptions.attribution = o.cartoAttribution;
    } else {
      url = OSM_TILE_URL;
      if (o.osmAttribution) tileOptions.attribution = o.osmAttribution;
    }

    return { layer: L.tileLayer(url, tileOptions), provider: provider };
  }

  global.OHG2Basemap = {
    readCartoApiKey: readCartoApiKey,
    hasCartoApiKey: hasCartoApiKey,
    createBaseLayer: createBaseLayer,
    CARTO_TILE_URL: CARTO_TILE_URL,
    OSM_TILE_URL: OSM_TILE_URL,
  };
})(window);
