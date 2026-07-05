'use strict';

const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う (他 live-stream 系 spec と同じ規約)
const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';

// 本番想定URL: OBS Browser Source が実際に指定するURLそのもの
// (demo=1 / focusSpeed=test / runtimeSpeed=test を一切含まない)。
const PROD_URL = `${DOCKER_BASE}/live/stream?chrome=off`;

async function mockAllLiveApis(page, { eqItems, rainAreas, kikiAreas, railItems, tideStations } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ items: eqItems != null ? eqItems : [] }),
  }));
  await page.route('**/api/live/summary**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ rain: { status: 'ok', areas: rainAreas != null ? rainAreas : [] }, kikikuru: { status: 'ok', areas: kikiAreas != null ? kikiAreas : [] } }),
  }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ items: railItems != null ? railItems : [] }),
  }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ stations: tideStations != null ? tideStations : [] }),
  }));
}

async function gotoAndCaptureErrors(page, url) {
  const pageErrors = [];
  const consoleErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message || String(e)));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return { pageErrors, consoleErrors };
}

test.describe('/live/stream — Stream Phase 6-A OBS実配信リハーサル・公開前最終確認', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('1: production URL (?chrome=off) is reachable and renders without errors', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const { pageErrors, consoleErrors } = await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(600);
    expect(pageErrors).toEqual([]);
    expect(consoleErrors.filter(t => t.includes('TypeError: Failed to fetch'))).toEqual([]);
  });

  test('2: production URL never contains demo/test state in the body', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(600);
    const snap = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
    expect(snap.isDemo).toBe(false);
    expect(snap.dataMode).toBe('real');
    const bodyAttrs = await page.evaluate(() => Object.assign({}, document.body.dataset));
    expect(bodyAttrs.streamDataMode).toBe('real');
  });

  test('3: production URL dataMode stays "real" (never demo/calm) via diagnostics', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(600);
    const snap = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
    expect(['healthy', 'degraded', 'error', 'loading']).toContain(snap.runtimeState);
    expect(snap.dataMode).toBe('real');
  });

  test('4: major UI fits within 1920x1080 (no horizontal/vertical overflow)', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(600);
    const stage = page.locator('.ls-stage, #stage').first();
    await expect(stage).toBeVisible();
    const box = await stage.boundingBox();
    expect(box).not.toBeNull();
    expect(box.width).toBeLessThanOrEqual(1920 + 2);
    expect(box.height).toBeLessThanOrEqual(1080 + 2);
  });

  test('5: center map and mini maps are all rendered (Leaflet containers present)', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(800);
    const count = await page.locator('.leaflet-container').count();
    expect(count).toBeGreaterThanOrEqual(4);
  });

  test('6: ticker exists and has content', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(600);
    const ticker = page.locator('.ls-ticker');
    await expect(ticker).toBeVisible();
    const nodeCount = await page.locator('.ls-ticker .move > *').count();
    expect(nodeCount).toBeGreaterThan(0);
  });

  test('7: dev controls are hidden on the production URL', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(300);
    const devEl = page.locator('#dev');
    if (await devEl.count() > 0) {
      await expect(devEl).toBeHidden();
    }
  });

  test('8: runtime diagnostics are retrievable and internally consistent', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(600);
    const snap = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
    expect(snap).not.toBeNull();
    expect(typeof snap.leafletContainerCount).toBe('number');
    expect(snap.leafletContainerCount).toBeGreaterThanOrEqual(4);
    expect(typeof snap.uptimeMs).toBe('number');
    expect(snap.byCategory).toHaveProperty('earthquake');
  });

  test('9: state=calm rehearsal URL is distinct from production (dataMode=calm, not demo)', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, `${DOCKER_BASE}/live/stream?state=calm&chrome=off`);
    await page.waitForTimeout(500);
    const snap = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
    expect(snap.dataMode).toBe('calm');
    expect(snap.isDemo).toBe(false);
  });

  test('10: demo=1 rehearsal URL is distinct from production (dataMode=demo)', async ({ page }) => {
    const { pageErrors } = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/live/stream?demo=1&chrome=off`);
    await page.waitForTimeout(500);
    const snap = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
    expect(snap.dataMode).toBe('demo');
    expect(snap.isDemo).toBe(true);
    expect(pageErrors).toEqual([]);
  });

  test('11: API failure on the production URL does not claim "normal" and does not fall back to demo', async ({ page }) => {
    for (const pattern of [
      '**/api/live/earthquakes/history**', '**/api/live/summary**',
      '**/api/live/trains/summary**', '**/api/live/tide/stations**',
    ]) {
      await page.route(pattern, route => route.fulfill({ status: 500, body: 'internal error' }));
    }
    const { pageErrors } = await gotoAndCaptureErrors(page, PROD_URL);
    await page.waitForTimeout(600);
    const snap = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
    expect(['degraded', 'error']).toContain(snap.runtimeState);
    expect(snap.dataMode).toBe('real');
    expect(snap.isDemo).toBe(false);
    const bodyText = await page.locator('body').textContent();
    expect(bodyText).not.toContain('平常運転');
    expect(pageErrors).toEqual([]);
  });

  test('12: /live is unaffected by the OBS rehearsal changes', async ({ page }) => {
    const { pageErrors } = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1000);
    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });

  test('13: / (navigation root) is unaffected', async ({ page }) => {
    const { pageErrors } = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/`);
    await page.waitForTimeout(500);
    expect(pageErrors).toEqual([]);
  });
});
