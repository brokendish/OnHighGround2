'use strict';
/**
 * live-basemap-carto-key.spec.js — /live 背景地図 CARTO API キー対応
 *
 * CARTO Basemaps は API キー必須（2026-08〜）。
 *   - キー設定時   : CARTO dark_all を key 付きで要求する
 *   - キー未設定時 : CARTO へ要求せず、OpenStreetMap タイルへフォールバックする
 *   - プレースホルダー: 未設定扱い（CARTO へ送らない）
 *
 * backend 不要。API はすべて空応答でモックする。
 */

const { test, expect } = require('@playwright/test');
const { mockBasemapTiles, injectCartoApiKey } = require('./helpers/basemap-mock');

async function stubApis(page) {
  await mockBasemapTiles(page);
  await page.route('**/data/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page.route('**/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page.route('**/jma.go.jp/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.alloc(0) }));
}

test.describe('/live 背景地図 — CARTO API キー', () => {
  test('キー設定時: CARTO dark_all を key 付きで要求する', async ({ page }) => {
    await stubApis(page);
    await injectCartoApiKey(page, 'test-carto-key-123');

    const cartoRequest = page.waitForRequest(/basemaps\.cartocdn\.com\/.*dark_all/);
    await page.goto('/live.html');
    await expect(page.locator('#live-map.leaflet-container')).toBeVisible({ timeout: 5000 });

    const req = await cartoRequest;
    const url = new URL(req.url());
    expect(url.searchParams.get('key')).toBe('test-carto-key-123');

    const info = await page.evaluate(() => {
      const b = window.OHG2Basemap.createBaseLayer(window.L, {});
      return { provider: b.provider, url: b.layer._url, hasKey: window.OHG2Basemap.hasCartoApiKey() };
    });
    expect(info.provider).toBe('carto');
    expect(info.hasKey).toBe(true);
    expect(info.url).toContain('key=test-carto-key-123');
  });

  test('キー未設定時: CARTO へ要求せず OpenStreetMap へフォールバックする', async ({ page }) => {
    await stubApis(page);

    const cartoRequests = [];
    page.on('request', r => { if (r.url().includes('basemaps.cartocdn.com')) cartoRequests.push(r.url()); });

    await page.goto('/live.html');
    await expect(page.locator('#live-map.leaflet-container')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#live-map .leaflet-tile-pane img.leaflet-tile').first()).toBeVisible({ timeout: 5000 });

    const info = await page.evaluate(() => {
      const b = window.OHG2Basemap.createBaseLayer(window.L, {});
      return {
        provider: b.provider,
        url: b.layer._url,
        key: window.OHG2Basemap.readCartoApiKey(),
        attribution: document.querySelector('.leaflet-control-attribution').innerHTML,
      };
    });
    expect(info.provider).toBe('osm');
    expect(info.key).toBe('');
    expect(info.url).toContain('tile.openstreetmap.org');
    expect(info.url).not.toContain('key=');
    // フォールバックでも OSM / ODbL 出典は維持される
    expect(info.attribution).toMatch(/OSM|OpenStreetMap/);
    expect(info.attribution).toContain('ODbL');

    expect(cartoRequests).toHaveLength(0);
  });

  test('プレースホルダー値は未設定扱い（CARTO へ送らない）', async ({ page }) => {
    await stubApis(page);
    await injectCartoApiKey(page, 'YOUR_KEY');

    const cartoRequests = [];
    page.on('request', r => { if (r.url().includes('basemaps.cartocdn.com')) cartoRequests.push(r.url()); });

    await page.goto('/live.html');
    await expect(page.locator('#live-map.leaflet-container')).toBeVisible({ timeout: 5000 });

    const key = await page.evaluate(() => window.OHG2Basemap.readCartoApiKey());
    expect(key).toBe('');
    expect(cartoRequests).toHaveLength(0);
  });

  test('空白のみのキーは未設定扱い', async ({ page }) => {
    await stubApis(page);
    await injectCartoApiKey(page, '   ');
    await page.goto('/live.html');
    await expect(page.locator('#live-map.leaflet-container')).toBeVisible({ timeout: 5000 });
    const key = await page.evaluate(() => window.OHG2Basemap.readCartoApiKey());
    expect(key).toBe('');
  });
});
