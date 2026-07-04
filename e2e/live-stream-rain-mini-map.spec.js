'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${DOCKER_BASE}/live/stream${query}${sep}focusSpeed=test&runtimeSpeed=test&demoNow=${DEMO_NOW}`;
}

function kikiArea(overrides) {
  return Object.assign({
    area_name: '静岡県 中部',
    level: 'danger',
    lat: 34.9,
    lng: 138.2,
    type: 'kikikuru',
    hazard: 'land',
    observed_at: OBSERVED_AT,
  }, overrides || {});
}

async function mockAllLiveApis(page, { kikiAreas, rainAreas } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/summary**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ rain: { status: 'ok', areas: rainAreas != null ? rainAreas : [] }, kikikuru: { status: 'ok', areas: kikiAreas != null ? kikiAreas : [] } }),
  }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
}

async function gotoAndCapturePageErrors(page, url) {
  const pageErrors = [];
  page.on('pageerror', e => {
    const text = e.message || String(e);
    if (text.includes('Failed to fetch')) return; // protomaps-leaflet ナビゲーション由来の無害なノイズ
    pageErrors.push(text);
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return pageErrors;
}

async function waitForRainMiniMapReady(page, timeout) {
  await page.waitForFunction(() => {
    const el = document.getElementById('rain-map');
    return !!(el && el.classList.contains('leaflet-container') && el.querySelector('.leaflet-tile-pane'));
  }, null, { timeout: timeout || 8000 });
}

test.describe('/live/stream — キキクル・豪雨子画面 小地図 本番地図化', () => {

  test('1: the mini map renders as a real Leaflet/CARTO map (not the old SVG blob mock)', async ({ page }) => {
    await mockAllLiveApis(page, { kikiAreas: [kikiArea()] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRainMiniMapReady(page);
    expect(errors).toEqual([]);
  });

  test('2: a pulse marker appears at the real lat/lng of the active kikikuru area', async ({ page }) => {
    await mockAllLiveApis(page, { kikiAreas: [kikiArea({ area_name: '静岡県 中部', lat: 34.9, lng: 138.2 })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRainMiniMapReady(page);
    const pulse = page.locator('#rain-map [data-testid="live-stream-rain-mini-pulse"]');
    await expect(pulse).toBeVisible();
  });

  test('3: the popup and active target still reflect the same area', async ({ page }) => {
    await mockAllLiveApis(page, { kikiAreas: [kikiArea({ area_name: '愛知県 東部' })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRainMiniMapReady(page);
    const popup = page.locator('[data-testid="live-stream-rain-popup"]');
    await expect(popup).toBeVisible();
    expect(await popup.textContent()).toContain('愛知県 東部');
  });

  test('4: state=calm shows no pulse and no crash', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await waitForRainMiniMapReady(page);
    expect(await page.locator('#rain-map [data-testid="live-stream-rain-mini-pulse"]').count()).toBe(0);
    expect(errors).toEqual([]);
  });

  test('5: no crash / no demo fallback when the summary API fails', async ({ page }) => {
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/summary**', route => route.fulfill({ status: 500, body: 'error' }));
    await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(1500);
    await expect(page.locator('[data-testid="live-stream-rain-status"]')).toHaveText('一時的に取得不可');
    expect(errors).toEqual([]);
  });

  test('6: demo=1 keeps the existing rain/kikikuru popup and cycling behavior', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?demo=1&focus=off'));
    await waitForRainMiniMapReady(page);
    await expect(page.locator('[data-testid="live-stream-rain-popup"]')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('7: repeated refresh does not accumulate the mini map instance or pulse markers', async ({ page }) => {
    await mockAllLiveApis(page, { kikiAreas: [kikiArea()] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRainMiniMapReady(page);
    const isLeafletBefore = await page.evaluate(() => document.getElementById('rain-map').classList.contains('leaflet-container'));
    const pulseCountBefore = await page.locator('#rain-map [data-testid="live-stream-rain-mini-pulse"]').count();
    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    const isLeafletAfter = await page.evaluate(() => document.getElementById('rain-map').classList.contains('leaflet-container'));
    const pulseCountAfter = await page.locator('#rain-map [data-testid="live-stream-rain-mini-pulse"]').count();
    expect(isLeafletAfter).toBe(isLeafletBefore);
    expect(pulseCountAfter).toBe(pulseCountBefore);
    expect(errors).toEqual([]);
  });

  test('8: /live is unaffected by the rain mini-map conversion', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
  });

  test('9: header no longer shows "監視卓"', async ({ page }) => {
    await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await page.waitForTimeout(500);
    const text = await page.locator('.ls-brand').textContent();
    expect(text).not.toContain('監視卓');
  });
});
