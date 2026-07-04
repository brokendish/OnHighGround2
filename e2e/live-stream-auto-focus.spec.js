'use strict';

const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う (他 live-stream 系 spec と同じ規約)
const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

// focusSpeed=test でタイマーを数百msに短縮し、E2Eを高速化する (通常運用のデフォルトは変えない)。
function streamUrl(query) {
  return `${DOCKER_BASE}/live/stream${query}${query.includes('?') ? '&' : '?'}focusSpeed=test`;
}

async function mockAllLiveApis(page, { eqItems, rainAreas, kikiAreas, railItems, tideStations } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ items: eqItems != null ? eqItems : [] }),
  }));
  await page.route('**/api/live/summary**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      rain:     { status: 'ok', areas: rainAreas != null ? rainAreas : [] },
      kikikuru: { status: 'ok', areas: kikiAreas != null ? kikiAreas : [] },
    }),
  }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ items: railItems != null ? railItems : [] }),
  }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ stations: tideStations != null ? tideStations : [] }),
  }));
}

async function mockAllLiveApis500(page) {
  for (const pattern of [
    '**/api/live/earthquakes/history**',
    '**/api/live/summary**',
    '**/api/live/trains/summary**',
    '**/api/live/tide/stations**',
  ]) {
    await page.route(pattern, route => route.fulfill({ status: 500, body: 'internal error' }));
  }
}

async function gotoAndCapturePageErrors(page, url) {
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message || String(e)));
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return pageErrors;
}

function eqItem(id, lat, lng, magnitude, intensity) {
  return { event_id: id, lat, lng, magnitude, max_intensity: intensity, occurred_at: OBSERVED_AT, epicenter_name: `震源${id}` };
}

async function waitForFocusMode(page, mode, timeout) {
  await page.waitForFunction(m => document.body.dataset.streamFocusMode === m, mode, { timeout: timeout || 5000 });
}

test.describe('/live/stream — Stream Phase 4-A 自動巡回・注目地域フォーカス', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('1: a high-priority event is selected as the focus target', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');

    const eventId = await page.evaluate(() => document.body.dataset.streamFocusEventId);
    expect(eventId).toBe('eq-focus-1');
    expect(errors).toEqual([]);
  });

  test('2: body reflects focus mode and focus event id', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    // ページロード直後は overview
    expect(await page.evaluate(() => document.body.dataset.streamFocusMode)).toBe('overview');
    await waitForFocusMode(page, 'focus');
    expect(await page.evaluate(() => document.body.dataset.streamFocusEventId)).toBe('eq-focus-1');
    expect(errors).toEqual([]);
  });

  test('3: focus event id is identical on map marker and panel item', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    await page.waitForTimeout(150);

    await expect(page.locator('[data-testid="live-stream-map-event-earthquake"][data-active="true"]')).toHaveAttribute('data-event-id', 'eq-focus-1');
    await expect(page.locator('[data-testid="live-stream-earthquake-popup"][data-active="true"]')).toHaveAttribute('data-event-id', 'eq-focus-1');
    expect(errors).toEqual([]);
  });

  test('4: focus event content is reflected in the ticker', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    await page.waitForTimeout(150);

    const tickerText = await page.getByTestId('live-stream-ticker-body').textContent();
    expect(tickerText).toContain('注目');
    expect(tickerText).toContain('震源eq-focus-1');
    expect(errors).toEqual([]);
  });

  test('5: cycles to the next focus event after a while when multiple events exist', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [eqItem('eq-focus-a', 24.8, 141.8, 6.4, '5弱')],
      kikiAreas: [{ area_name: '静岡県中部', level: 'danger', lat: 34.9, lng: 138.2, type: 'kikikuru', hazard: 'land', observed_at: OBSERVED_AT }],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    const first = await page.evaluate(() => document.body.dataset.streamFocusEventId);

    // 次の候補、または overview への遷移を待つ (returning を経由することもある)
    await page.waitForFunction(prev => document.body.dataset.streamFocusEventId !== prev
      || document.body.dataset.streamFocusMode !== 'focus', first, { timeout: 5000 });

    const seen = new Set([first]);
    for (let i = 0; i < 6; i++) {
      await page.waitForTimeout(200);
      const mode = await page.evaluate(() => document.body.dataset.streamFocusMode);
      const id = await page.evaluate(() => document.body.dataset.streamFocusEventId);
      if (mode === 'focus' && id) seen.add(id);
      if (seen.size >= 2) break;
    }
    expect(seen.size).toBeGreaterThanOrEqual(2);
    expect(errors).toEqual([]);
  });

  test('6: state=calm never focuses, stays in overview', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-should-not-focus', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?state=calm&chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(1500);

    expect(await page.evaluate(() => document.body.dataset.streamFocusMode)).toBe('overview');
    expect(await page.evaluate(() => document.body.dataset.streamFocusEventId)).toBe('');
    expect(errors).toEqual([]);
  });

  test('7: demo=1 cycles through the same focus pipeline', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');

    const eventId = await page.evaluate(() => document.body.dataset.streamFocusEventId);
    expect(eventId).toBeTruthy();
    await page.waitForTimeout(150);
    await expect(page.locator(`[data-testid^="live-stream-pulse-"][data-event-id="${eventId}"][data-active="true"]`)).toHaveCount(1);
    expect(errors).toEqual([]);
  });

  test('8: empty data never focuses, stays in overview', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(1500);

    expect(await page.evaluate(() => document.body.dataset.streamFocusMode)).toBe('overview');
    expect(errors).toEqual([]);
  });

  test('9: total API failure does not focus and does not fall back to demo', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(1500);

    expect(await page.evaluate(() => document.body.dataset.streamFocusMode)).toBe('overview');
    await expect(page.getByTestId(/^live-stream-pulse-/)).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('10: active class is cleared once the focused event disappears', async ({ page }) => {
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ items: [eqItem('eq-vanish', 24.8, 141.8, 6.4, '5弱')] }),
    }));
    await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
    await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));

    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    expect(await page.evaluate(() => document.body.dataset.streamFocusEventId)).toBe('eq-vanish');

    // イベントが消える
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
      contentType: 'application/json', body: JSON.stringify({ items: [] }),
    }));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);

    await expect(page.locator('[data-active="true"]')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('11: map remains non-interactive during focus cycling', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.locator('.leaflet-control-zoom')).toHaveCount(0);
  });

  test('12: /live regression unaffected by focus controller wiring', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);

    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
