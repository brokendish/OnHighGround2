'use strict';

const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う (他 live-stream 系 spec と同じ規約)
const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

function streamUrl(query) {
  return `${DOCKER_BASE}/live/stream${query}`;
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

async function getSnapshot(page) {
  return page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
}

test.describe('/live/stream — Stream Phase 5-A 配信用安定運用・長時間稼働対策', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('1: runtime diagnostics snapshot is available', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(400);

    const snap = await getSnapshot(page);
    expect(snap).not.toBeNull();
    expect(typeof snap.runtimeState).toBe('string');
    expect(typeof snap.refreshCount).toBe('number');
    expect(snap.byCategory).toHaveProperty('earthquake');
    expect(snap.byCategory).toHaveProperty('tide');
    expect(errors).toEqual([]);
  });

  test('2: repeated refresh does not accumulate map markers', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}&runtimeSpeed=test`));
    await page.waitForTimeout(300);

    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    const count = await page.getByTestId('live-stream-map-event-earthquake').count();
    expect(count).toBe(1);
    expect(errors).toEqual([]);
  });

  test('3: repeated refresh does not accumulate ticker DOM nodes', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}&runtimeSpeed=test`));
    await page.waitForTimeout(300);

    const before = await getSnapshot(page);
    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    const after = await getSnapshot(page);
    expect(after.dom.tickerTextNodes).toBe(before.dom.tickerTextNodes);
    expect(errors).toEqual([]);
  });

  test('4: repeated refresh does not accumulate panel DOM (rail cards)', async ({ page }) => {
    await mockAllLiveApis(page, {
      railItems: [
        { railway_id: 'chuo', railway_name: '中央線快速', operator_name: 'JR東日本', status: 'suspended', status_label: '見合わせ', description: '人身事故', severity: 3, updated_at: OBSERVED_AT },
      ],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}&runtimeSpeed=test`));
    await page.waitForTimeout(300);

    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    const count = await page.getByTestId('live-stream-rail-list-item').count();
    expect(count).toBe(1);
    expect(errors).toEqual([]);
  });

  test('5: an in-flight refresh blocks a concurrent duplicate refresh', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}&runtimeSpeed=test`));
    await page.waitForTimeout(300);

    const before = await getSnapshot(page);
    // 同一tick内で2回連続呼び出す (in-flightガードがなければ両方走ってしまう)
    await page.evaluate(() => {
      window.__LiveStreamDiagnostics.forceRefresh();
      window.__LiveStreamDiagnostics.forceRefresh();
    });
    await page.waitForTimeout(400);
    const after = await getSnapshot(page);
    // 1回のforceRefresh呼び出し分 (4カテゴリ) しか実行されていないこと
    expect(after.byCategory.earthquake.count).toBe(before.byCategory.earthquake.count + 1);
    expect(errors).toEqual([]);
  });

  test('6: API 500 continuing does not cause pageerror', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}&runtimeSpeed=test`));
    await page.waitForTimeout(400);
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    expect(errors).toEqual([]);
  });

  test('7: continuing failures push runtimeState to degraded/error', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}&runtimeSpeed=test`));
    await page.waitForTimeout(400);

    const snap = await getSnapshot(page);
    expect(['degraded', 'error']).toContain(snap.runtimeState);
    expect(['degraded', 'error']).toContain(await page.evaluate(() => document.body.dataset.streamRuntimeState));
    expect(errors).toEqual([]);
  });

  test('8: recovery brings runtimeState back to healthy', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}&runtimeSpeed=test`));
    await page.waitForTimeout(400);
    expect((await getSnapshot(page)).runtimeState).not.toBe('healthy');

    await page.unroute('**/api/live/earthquakes/history**');
    await page.unroute('**/api/live/summary**');
    await page.unroute('**/api/live/trains/summary**');
    await page.unroute('**/api/live/tide/stations**');
    await mockAllLiveApis(page, {});
    await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
    await page.waitForTimeout(400);

    const snap = await getSnapshot(page);
    expect(snap.runtimeState).toBe('healthy');
    expect(snap.consecutiveFailures).toBe(0);
    expect(await page.evaluate(() => document.body.dataset.streamRuntimeState)).toBe('healthy');
    expect(errors).toEqual([]);
  });

  test('9: active class does not persist once a focused event disappears', async ({ page }) => {
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ items: [eqItem('eq-vanish', 24.8, 141.8, 6.4, '5弱')] }),
    }));
    await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
    await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));

    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForFunction(() => document.body.dataset.streamFocusMode === 'focus', { timeout: 5000 });
    expect(await page.evaluate(() => document.body.dataset.streamFocusEventId)).toBe('eq-vanish');

    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
      contentType: 'application/json', body: JSON.stringify({ items: [] }),
    }));
    await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
    await page.waitForTimeout(600);

    await expect(page.locator('[data-active="true"]')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('10: calm / demo / real mode existing behaviour is unaffected', async ({ page }) => {
    // calm
    let errors = await gotoAndCapturePageErrors(page, streamUrl(`?state=calm&chrome=off&demoNow=${DEMO_NOW}`));
    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-lv', 'calm');
    expect(errors).toEqual([]);

    // demo
    errors = await gotoAndCapturePageErrors(page, streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_NOW}`));
    await expect(page.getByTestId('live-stream-pulse-earthquake')).toBeVisible();
    expect(errors).toEqual([]);

    // real (empty data)
    await mockAllLiveApis(page, {});
    errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await expect(page.getByTestId('live-stream-center-map')).toHaveClass(/leaflet-container/);
    expect(errors).toEqual([]);
  });

  test('11: Phase 3-D badge/count/status sync still works', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(400);

    await expect(page.getByTestId('live-stream-category-badge-earthquake')).toHaveAttribute('data-count', '1');
    await expect(page.locator('#ct-eq')).toHaveText('1');
    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-lv', 'high');
    expect(errors).toEqual([]);
  });

  test('12: /live regression unaffected by runtime wiring', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);

    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
