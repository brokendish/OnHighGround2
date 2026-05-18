'use strict';

/**
 * shelter-marker-image.spec.js
 *
 * 避難所マーカー画像化対応の検証。
 * API はモックし、Leaflet 上の実 DOM で SVG / zoom size / selection /
 * clustering / proximity highlight / layer toggle を確認する。
 */

const { test, expect } = require('@playwright/test');

const TEST_SITES = [
  { name: '有明小学校', lat: 35.6418, lon: 139.7908, category: 'evacuation_shelter', designation: '指定避難所', address: '東京都江東区有明', hazard_types: ['tsunami'], region: 'tokyo' },
  { name: '有明北緑道公園', lat: 35.6422, lon: 139.7912, category: 'emergency_evacuation_site', designation: '指定緊急避難場所', address: '東京都江東区有明', hazard_types: ['tsunami', 'flood'], region: 'tokyo' },
  { name: '東雲小学校', lat: 35.6430, lon: 139.7920, category: 'evacuation_shelter', designation: '指定避難所', address: '東京都江東区東雲', hazard_types: [], region: 'tokyo' },
  { name: '辰巳公園', lat: 35.6438, lon: 139.7928, category: 'emergency_evacuation_site', designation: '指定緊急避難場所', address: '東京都江東区辰巳', hazard_types: ['earthquake'], region: 'tokyo' },
  { name: '豊洲西小学校', lat: 35.6446, lon: 139.7936, category: 'evacuation_shelter', designation: '指定避難所', address: '東京都江東区豊洲', hazard_types: ['flood'], region: 'tokyo' },
  { name: '晴海ふ頭公園', lat: 35.6454, lon: 139.7944, category: 'emergency_evacuation_site', designation: '指定緊急避難場所', address: '東京都中央区晴海', hazard_types: ['tsunami'], region: 'tokyo' },
  { name: '有明テニスの森', lat: 35.6462, lon: 139.7952, category: 'evacuation_shelter', designation: '指定避難所', address: '東京都江東区有明', hazard_types: [], region: 'tokyo' },
];

async function setupMocks(page) {
  await page.route('**/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('**/api/admin/config**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }));
  await page.route('**/api/admin/config/stream**', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'event: heartbeat\ndata: {}\n\n',
  }));
  await page.route('**/api/tsunami/warnings/current**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ source: 'mock', status: 'none', observed_at: null, updated_at: new Date().toISOString(), ttl_seconds: 60, areas: [], message: '' }),
  }));
  await page.route('**/api/weather/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('**/api/hazards/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ type: 'FeatureCollection', features: [] }),
  }));
  await page.route('**/api/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ count: TEST_SITES.length, total_count: TEST_SITES.length, data: TEST_SITES }),
  }));
  await page.route('**/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ count: TEST_SITES.length, total_count: TEST_SITES.length, data: TEST_SITES }),
  }));
}

async function gotoReady(page, viewport) {
  if (viewport) await page.setViewportSize(viewport);
  await setupMocks(page);
  await page.goto('/');
  await page.waitForFunction(() => window.map && window.L && typeof L.markerClusterGroup === 'function');
  await page.waitForFunction(() => typeof refreshEmergencyShelters === 'function');
}

async function renderShelters(page, zoom = 16, withLocation = true) {
  await page.evaluate(async ({ zoom, withLocation }) => {
    isShelterBrowseLayerVisible = false;
    currentLocation = withLocation
      ? { lat: 35.6415, lon: 139.7905, accuracyMeters: 8, elevation: null }
      : null;
    map.setView([35.6415, 139.7905], zoom, { animate: false });
    await refreshEmergencyShelters();
  }, { zoom, withLocation });
  await page.waitForTimeout(250);
}

test.describe('避難所マーカー画像化検証', () => {
  test('SVGアイコン・ズーム依存サイズ・選択状態・近傍強調・レイヤーON/OFFが機能する', async ({ page }) => {
    const consoleErrors = [];
    page.on('pageerror', error => consoleErrors.push(error.message));
    page.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await gotoReady(page);
    await renderShelters(page, 16, true);

    const icons = page.locator('.shelter-icon');
    await expect(icons).toHaveCount(TEST_SITES.length);
    await expect(page.locator('.shelter-icon--es')).toHaveCount(4);
    await expect(page.locator('.shelter-icon--eee')).toHaveCount(3);
    await expect(page.locator('.shelter-icon svg')).toHaveCount(TEST_SITES.length);
    await expect(page.locator('.shelter-icon--near')).toHaveCount(5);
    await expect(page.locator('.shelter-icon--far')).toHaveCount(2);

    const sizeAt16 = await icons.first().evaluate(el => ({
      width: parseFloat(el.style.width),
      height: parseFloat(el.style.height),
    }));
    expect(sizeAt16).toEqual({ width: 28, height: 28 });

    await page.evaluate(async () => {
      map.setZoom(12, { animate: false });
      await refreshEmergencyShelters();
    });
    await page.waitForTimeout(250);
    const clusterCount = await page.locator('.shelter-cluster-icon').count();
    expect(clusterCount).toBeGreaterThan(0);

    await page.evaluate(async () => {
      map.setZoom(17, { animate: false });
      await refreshEmergencyShelters();
    });
    await page.waitForTimeout(250);
    await expect(page.locator('.shelter-cluster-icon')).toHaveCount(0);
    await expect(icons).toHaveCount(TEST_SITES.length);
    const sizeAt17 = await icons.first().evaluate(el => ({
      width: parseFloat(el.style.width),
      height: parseFloat(el.style.height),
    }));
    expect(sizeAt17).toEqual({ width: 34, height: 34 });

    await icons.nth(0).click();
    await expect(page.locator('.shelter-icon--selected')).toHaveCount(1);
    await expect(page.locator('.leaflet-popup-content')).toContainText('指定避難所');
    await expect(page.locator('.leaflet-popup-content')).toContainText('ルートを表示');

    await page.evaluate(() => {
      map.closePopup();
      emergencyShelterMarkers[1].fire('click');
    });
    await expect(page.locator('.shelter-icon--selected')).toHaveCount(1);
    await expect(page.locator('.leaflet-popup-content').filter({ hasText: '指定緊急避難場所' }).first()).toBeVisible();

    await page.evaluate(() => {
      const shelters = document.getElementById('showEmergencyShelters');
      const sites = document.getElementById('showEmergencyEvacuationSites');
      shelters.checked = false;
      sites.checked = false;
      shelters.dispatchEvent(new Event('change', { bubbles: true }));
      sites.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await expect(page.locator('.shelter-icon')).toHaveCount(0);
    await expect(page.locator('.shelter-cluster-icon')).toHaveCount(0);

    await page.evaluate(() => {
      const shelters = document.getElementById('showEmergencyShelters');
      const sites = document.getElementById('showEmergencyEvacuationSites');
      shelters.checked = true;
      sites.checked = true;
      shelters.dispatchEvent(new Event('change', { bubbles: true }));
      sites.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.waitForTimeout(400);
    await expect(page.locator('.shelter-icon')).toHaveCount(TEST_SITES.length);

    const fatalErrors = consoleErrors.filter(text => !/favicon|Failed to load resource/i.test(text));
    expect(fatalErrors).toEqual([]);

    await page.screenshot({ path: 'test-results/shelter-marker-image-desktop.png', fullPage: true });
  });

  test('現在地未取得時は通常表示になり、スマホ幅でも地図UIが表示される', async ({ page }) => {
    await gotoReady(page, { width: 390, height: 844 });
    await renderShelters(page, 16, false);

    await expect(page.locator('.shelter-icon')).toHaveCount(TEST_SITES.length);
    await expect(page.locator('.shelter-icon--near')).toHaveCount(0);
    await expect(page.locator('.shelter-icon--far')).toHaveCount(0);
    await expect(page.locator('#map')).toBeVisible();
    await expect(page.locator('#mbc-tab-btn-layer')).toBeVisible();

    const mapBox = await page.locator('#map').boundingBox();
    const tabBox = await page.locator('#mbc-tab-btn-layer').boundingBox();
    expect(mapBox.width).toBeGreaterThan(300);
    expect(tabBox.width).toBeGreaterThan(30);

    await page.screenshot({ path: 'test-results/shelter-marker-image-mobile.png', fullPage: true });
  });
});
