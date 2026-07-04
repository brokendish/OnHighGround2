'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${DOCKER_BASE}/live/stream${query}${sep}demoNow=${DEMO_NOW}`;
}

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

async function mockAllLiveApis500(page) {
  for (const pattern of [
    '**/api/live/earthquakes/history**', '**/api/live/summary**',
    '**/api/live/trains/summary**', '**/api/live/tide/stations**',
  ]) {
    await page.route(pattern, route => route.fulfill({ status: 500, body: 'internal error' }));
  }
}

async function gotoAndCaptureErrors(page, url) {
  const pageErrors = [];
  const consoleErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message || String(e)));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return { pageErrors, consoleErrors };
}

async function getSnapshot(page) {
  return page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
}

test.describe('/live/stream — Stream Phase 5-C demo mode diagnostics 状態整理', () => {

  test('1: demo=1 sets body[data-stream-data-mode="demo"]', async ({ page }) => {
    await gotoAndCaptureErrors(page, streamUrl('?demo=1&chrome=off'));
    await page.waitForTimeout(500);
    expect(await page.evaluate(() => document.body.dataset.streamDataMode)).toBe('demo');
  });

  test('2: demo mode runtimeState does not stay "loading"', async ({ page }) => {
    await gotoAndCaptureErrors(page, streamUrl('?demo=1&chrome=off'));
    await page.waitForTimeout(500);
    const snap = await getSnapshot(page);
    expect(snap.runtimeState).not.toBe('loading');
    expect(snap.runtimeState).toBe('demo');
  });

  test('3: demo mode diagnostics.dataMode === "demo" and isDemo === true', async ({ page }) => {
    await gotoAndCaptureErrors(page, streamUrl('?demo=1&chrome=off'));
    await page.waitForTimeout(500);
    const snap = await getSnapshot(page);
    expect(snap.dataMode).toBe('demo');
    expect(snap.isDemo).toBe(true);
    expect(snap.isCalm).toBe(false);
  });

  test('4: demo mode does not start /api/live/* periodic fetch', async ({ page }) => {
    const liveApiRequests = [];
    page.on('request', r => { if (r.url().includes('/api/live/')) liveApiRequests.push(r.url()); });
    await gotoAndCaptureErrors(page, streamUrl('?demo=1&chrome=off'));
    await page.waitForTimeout(2000);
    expect(liveApiRequests).toEqual([]);
    const snap = await getSnapshot(page);
    expect(snap.refreshCount).toBe(0);
  });

  test('5: demo mode does not produce "TypeError: Failed to fetch" console errors during a short session', async ({ page }) => {
    const { pageErrors, consoleErrors } = await gotoAndCaptureErrors(page, streamUrl('?demo=1&chrome=off'));
    await page.waitForTimeout(3000);
    expect(consoleErrors.filter(t => t.includes('TypeError: Failed to fetch'))).toEqual([]);
    expect(pageErrors).toEqual([]);
  });

  test('6: demo mode keeps map/panel/ticker/focus working as before', async ({ page }) => {
    await gotoAndCaptureErrors(page, streamUrl('?demo=1&chrome=off&focusSpeed=test'));
    await expect(page.getByTestId('live-stream-pulse-earthquake')).toBeVisible();
    await expect(page.getByTestId('live-stream-center-map')).toHaveClass(/leaflet-container/);
    await page.waitForFunction(() => document.body.dataset.streamFocusMode === 'focus', { timeout: 5000 });
    expect(await page.evaluate(() => !!document.body.dataset.streamFocusEventId)).toBe(true);
  });

  test('7: demo mode EventStore keeps demo events (eventCount > 0)', async ({ page }) => {
    await gotoAndCaptureErrors(page, streamUrl('?demo=1&chrome=off'));
    await page.waitForTimeout(500);
    const snap = await getSnapshot(page);
    expect(snap.eventCount).toBeGreaterThan(0);
  });

  test('8: real API 500 results in runtimeState=error/degraded, distinct from demo', async ({ page }) => {
    await mockAllLiveApis500(page);
    await gotoAndCaptureErrors(page, streamUrl('?chrome=off&runtimeSpeed=test'));
    await page.waitForTimeout(600);
    const snap = await getSnapshot(page);
    expect(['degraded', 'error']).toContain(snap.runtimeState);
    expect(snap.dataMode).toBe('real');
    expect(snap.isDemo).toBe(false);
    expect(snap.recentFetchFailures.length).toBeGreaterThan(0);
    expect(snap.recentFetchFailures[0]).toHaveProperty('category');
    expect(snap.recentFetchFailures[0]).toHaveProperty('errorMessage');
  });

  test('9: API failure does not fall back to demo (dataMode stays "real")', async ({ page }) => {
    await mockAllLiveApis500(page);
    await gotoAndCaptureErrors(page, streamUrl('?chrome=off&runtimeSpeed=test'));
    await page.waitForTimeout(600);
    const snap = await getSnapshot(page);
    expect(snap.dataMode).toBe('real');
    expect(snap.isDemo).toBe(false);
    const bodyText = await page.locator('body').textContent();
    expect(bodyText).not.toContain('平常運転');
  });

  test('10: calm mode has dataMode="calm", distinct from demo', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, streamUrl('?state=calm&chrome=off'));
    await page.waitForTimeout(500);
    const snap = await getSnapshot(page);
    expect(snap.dataMode).toBe('calm');
    expect(snap.isCalm).toBe(true);
    expect(snap.isDemo).toBe(false);
    expect(await page.evaluate(() => document.body.dataset.streamDataMode)).toBe('calm');
  });

  test('11: Phase 5-B scoped runtime diagnostics (byCategory, refreshInFlight) still present', async ({ page }) => {
    await mockAllLiveApis(page, {});
    await gotoAndCaptureErrors(page, streamUrl('?chrome=off&runtimeSpeed=test'));
    await page.waitForTimeout(500);
    const snap = await getSnapshot(page);
    expect(snap.byCategory).toHaveProperty('earthquake');
    expect(snap.byCategory).toHaveProperty('rain');
    expect(snap.byCategory).toHaveProperty('railway');
    expect(snap.byCategory).toHaveProperty('tide');
    expect(typeof snap.refreshInFlight).toBe('boolean');
  });

  test('12: /live regression is unaffected by the demo diagnostics changes', async ({ page }) => {
    const { pageErrors } = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1000);
    expect(pageErrors).toEqual([]);
  });
});
