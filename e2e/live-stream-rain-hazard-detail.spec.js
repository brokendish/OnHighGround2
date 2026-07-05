'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-05T13:00:00+09:00';

function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${DOCKER_BASE}/live/stream${query}${sep}focusSpeed=test&runtimeSpeed=test`;
}

async function mockAllLiveApis(page, { rainAreas, kikiAreas } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({
    rain: { status: 'ok', areas: rainAreas != null ? rainAreas : [] },
    kikikuru: { status: 'ok', areas: kikiAreas != null ? kikiAreas : [] },
  }) }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
}

async function gotoAndCaptureErrors(page, url) {
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message || String(e)));
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return pageErrors;
}

test.describe('/live/stream — Stream Phase 6-C キキクル・豪雨ポップアップ hazard内訳表示', () => {

  test('1: a single-hazard area still shows one hazard line (no regression)', async ({ page }) => {
    await mockAllLiveApis(page, {
      kikiAreas: [{ area_name: '愛知県 東部', prefecture: '愛知県', level: 'danger', type: 'kikikuru', hazard: 'land', lat: 35.0, lng: 137.4, observed_at: OBSERVED_AT }],
    });
    const errors = await gotoAndCaptureErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(500);
    const lines = await page.locator('#rain-overlay .l').allTextContents();
    expect(lines.length).toBe(1);
    expect(lines[0]).toContain('土砂災害');
    expect(lines[0]).toContain('危険');
    expect(errors).toEqual([]);
  });

  test('2: multiple hazards at the same location are all shown, not just the top one', async ({ page }) => {
    await mockAllLiveApis(page, {
      kikiAreas: [
        { area_name: '静岡県 中部', prefecture: '静岡県', level: 'danger', type: 'kikikuru', hazard: 'land', lat: 34.9, lng: 138.2, observed_at: OBSERVED_AT },
        { area_name: '静岡県 中部', prefecture: '静岡県', level: 'warning', type: 'kikikuru', hazard: 'inund', lat: 34.9, lng: 138.2, observed_at: OBSERVED_AT },
        { area_name: '静岡県 中部', prefecture: '静岡県', level: 'warning', type: 'kikikuru', hazard: 'flood_mesh', lat: 34.9, lng: 138.2, observed_at: OBSERVED_AT },
      ],
    });
    const errors = await gotoAndCaptureErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(500);
    const lines = await page.locator('#rain-overlay .l').allTextContents();
    expect(lines.length).toBe(3);
    expect(lines.some(t => t.includes('土砂災害') && t.includes('危険'))).toBe(true);
    expect(lines.some(t => t.includes('浸水災害') && t.includes('警戒'))).toBe(true);
    expect(lines.some(t => t.includes('洪水災害') && t.includes('警戒'))).toBe(true);
    expect(errors).toEqual([]);
  });

  test('3: the popup shows an update time line', async ({ page }) => {
    await mockAllLiveApis(page, {
      kikiAreas: [{ area_name: '愛媛県 東予', prefecture: '愛媛県', level: 'warning', type: 'kikikuru', hazard: 'land', lat: 33.9, lng: 133.1, observed_at: OBSERVED_AT }],
    });
    await gotoAndCaptureErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(500);
    const note = page.getByTestId('live-stream-rain-updated');
    await expect(note).toBeVisible();
    expect(await note.textContent()).toContain('更新');
  });

  test('4: a duplicate sample for the same hazard keeps only the highest level', async ({ page }) => {
    await mockAllLiveApis(page, {
      kikiAreas: [
        { area_name: '鹿児島県 薩摩', prefecture: '鹿児島県', level: 'warning', type: 'kikikuru', hazard: 'land', lat: 31.6, lng: 130.3, observed_at: OBSERVED_AT },
        { area_name: '鹿児島県 薩摩', prefecture: '鹿児島県', level: 'danger', type: 'kikikuru', hazard: 'land', lat: 31.6, lng: 130.3, observed_at: OBSERVED_AT },
      ],
    });
    await gotoAndCaptureErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(500);
    const lines = await page.locator('#rain-overlay .l').allTextContents();
    expect(lines.length).toBe(1);
    expect(lines[0]).toContain('危険');
  });

  test('5: rain (nowcast) and kikikuru hazards at the same area name are combined too', async ({ page }) => {
    await mockAllLiveApis(page, {
      rainAreas: [{ area_name: '高知県 中部', prefecture: '高知県', level: 'danger', type: 'rain', lat: 33.5, lng: 133.5, observed_at: OBSERVED_AT }],
      kikiAreas: [{ area_name: '高知県 中部', prefecture: '高知県', level: 'warning', type: 'kikikuru', hazard: 'inund', lat: 33.5, lng: 133.5, observed_at: OBSERVED_AT }],
    });
    await gotoAndCaptureErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(500);
    const lines = await page.locator('#rain-overlay .l').allTextContents();
    expect(lines.length).toBe(2);
    expect(lines.some(t => t.includes('豪雨災害') && t.includes('危険'))).toBe(true);
    expect(lines.some(t => t.includes('浸水災害') && t.includes('警戒'))).toBe(true);
  });

  test('6: /live is unaffected by the rain hazard detail change', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(800);
    expect(errors).toEqual([]);
  });
});
