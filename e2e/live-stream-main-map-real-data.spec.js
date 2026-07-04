'use strict';

const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う (他 live-stream 系 spec と同じ規約)
const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';

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

function gotoAndCapturePageErrors(page, url) {
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message || String(e)));
  return page.goto(url, { waitUntil: 'domcontentloaded' }).then(() => pageErrors);
}

async function gotoAndCaptureAllErrors(page, url) {
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', e => pageErrors.push(e.message || String(e)));
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return { consoleErrors, pageErrors };
}

test.describe('/live/stream — Stream Phase 3-B 中央メイン地図 本番データ連動', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('earthquake events render from mocked production API', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [
        { event_id: 'eq-1', lat: 24.8, lng: 141.8, magnitude: 6.4, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: '宮古島北西沖' },
      ],
    });
    const errors = await gotoAndCaptureAllErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.getByTestId('live-stream-map-event-earthquake')).toBeVisible();
    expect(errors.pageErrors).toEqual([]);
  });

  test('rain/kikikuru representative events render from mocked production API', async ({ page }) => {
    await mockAllLiveApis(page, {
      kikiAreas: [
        { area_name: '静岡県中部', level: 'danger', lat: 34.9, lng: 138.2, type: 'kikikuru', hazard: 'land', observed_at: OBSERVED_AT },
      ],
    });
    const errors = await gotoAndCaptureAllErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.getByTestId('live-stream-map-event-kikikuru')).toBeVisible();
    expect(errors.pageErrors).toEqual([]);
  });

  test('railway affected-line event renders from mocked production API', async ({ page }) => {
    await mockAllLiveApis(page, {
      railItems: [
        {
          railway_id: 'odpt.Railway:JR-East.ChuoRapid', railway_name: '中央線快速',
          operator_name: 'JR東日本', status: 'suspended', status_label: '見合わせ',
          description: '人身事故', severity: 3, updated_at: OBSERVED_AT,
        },
      ],
    });
    const errors = await gotoAndCaptureAllErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.getByTestId('live-stream-map-event-railway')).toBeVisible();
    expect(errors.pageErrors).toEqual([]);
  });

  test('items without valid coordinates are excluded from the map', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [
        { event_id: 'eq-nocoord', lat: null, lng: null, magnitude: 5.0, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: '座標なし震源' },
        { event_id: 'eq-badcoord', lat: 999, lng: 999, magnitude: 5.0, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: '異常座標震源' },
      ],
    });
    const errors = await gotoAndCaptureAllErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId('live-stream-map-event-earthquake')).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });

  test('empty data from all APIs: no markers, no crash', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCaptureAllErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap).toHaveClass(/leaflet-container/);
    await expect(page.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });

  test('API 500 on all endpoints: no JS error, map still renders, no demo fallback', async ({ page }) => {
    await mockAllLiveApis500(page);
    // 500応答は Chromium がネットワークエラーとして console.error を出すため、ここでは pageerror のみ検証する
    // (既存 rain-mock-verify.spec.js 等と同じ規約)
    const pageErrors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(1000);

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap).toHaveClass(/leaflet-container/);
    await expect(page.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    // 取得失敗時に demo パルスへフォールバックしていないこと
    await expect(page.getByTestId('live-stream-pulse-earthquake')).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });

  test('demo=1 shows demo pulses, not production events', async ({ page }) => {
    // demo=1 時は実APIを呼ばない前提だが、万一呼ばれても検知できるようダミーで応答させる
    await mockAllLiveApis(page, {
      eqItems: [{ event_id: 'eq-x', lat: 24.8, lng: 141.8, magnitude: 6.4, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: 'ダミー' }],
    });
    const errors = await gotoAndCaptureAllErrors(page, streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_NOW}`));

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.getByTestId('live-stream-pulse-earthquake')).toBeVisible();
    await expect(centerMap.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });

  test('normal access never falls back to demo markers even when production data is empty', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCaptureAllErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId('live-stream-pulse-earthquake')).toHaveCount(0);
    await expect(page.getByTestId('live-stream-pulse-rain')).toHaveCount(0);
    await expect(page.getByTestId('live-stream-pulse-rail')).toHaveCount(0);
    await expect(page.getByTestId('live-stream-pulse-tide')).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });

  test('map stays non-interactive in production data mode', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [{ event_id: 'eq-1', lat: 24.8, lng: 141.8, magnitude: 6.4, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: '宮古島北西沖' }],
    });
    await gotoAndCaptureAllErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.locator('.leaflet-control-zoom')).toHaveCount(0);
  });

  test('/live regression: normal Leaflet map unaffected by production event layer', async ({ page }) => {
    const errors = await gotoAndCaptureAllErrors(page, `${DOCKER_BASE}/live`);

    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });
});
