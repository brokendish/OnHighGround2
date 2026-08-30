'use strict';
/**
 * basemap-mock.js — 背景地図タイルのネットワークモック（E2E 共通ヘルパー）
 *
 * /live・/live/stream の背景地図は、CARTO_BASEMAP_API_KEY が設定されていれば
 * CARTO dark_all、未設定なら OpenStreetMap ラスタタイルへフォールバックする
 * （frontend/js/shared/basemap.js）。E2E では意図しない外部通信を避けるため、
 * どちらのプロバイダーのタイル要求も透明 PNG で受ける。
 *
 * 使い方:
 *   const { mockBasemapTiles } = require('./helpers/basemap-mock');
 *   await mockBasemapTiles(page);
 */

const TRANSPARENT_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
  'base64',
);

async function mockBasemapTiles(page) {
  const png = route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG });
  await page.route('**/basemaps.cartocdn.com/**', png);
  await page.route('**/tile.openstreetmap.org/**', png);
}

/**
 * ページ読み込み前に window.OHG2_RUNTIME_CONFIG を注入する。
 * @param {import('@playwright/test').Page} page
 * @param {string} key  CARTO_BASEMAP_API_KEY に設定する値（プレースホルダー検証用に任意文字列可）
 */
async function injectCartoApiKey(page, key) {
  await page.addInitScript(k => {
    window.OHG2_RUNTIME_CONFIG = Object.assign(
      {}, window.OHG2_RUNTIME_CONFIG || {}, { CARTO_BASEMAP_API_KEY: k },
    );
  }, key);
}

module.exports = { mockBasemapTiles, injectCartoApiKey, TRANSPARENT_PNG };
