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

async function gotoAndCaptureErrors(page, url, { strict } = {}) {
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', e => pageErrors.push(e.message || String(e)));
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return { consoleErrors: strict === false ? [] : consoleErrors, pageErrors };
}

test.describe('/live/stream — Stream Phase 3-C 地図・パネル・テロップの event 同期', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('1: earthquake event id is identical on map marker and panel popup', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [
        { event_id: 'eq-sync-001', lat: 24.8, lng: 141.8, magnitude: 6.4, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: '宮古島北西沖' },
      ],
    });
    const errors = await gotoAndCaptureErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId('live-stream-map-event-earthquake')).toHaveAttribute('data-event-id', 'eq-sync-001');
    await expect(page.getByTestId('live-stream-earthquake-popup')).toHaveAttribute('data-event-id', 'eq-sync-001');
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('宮古島北西沖');
    expect(errors.pageErrors).toEqual([]);
  });

  test('2: rain/kikikuru event is reflected on marker, panel, and ticker with matching id', async ({ page }) => {
    await mockAllLiveApis(page, {
      kikiAreas: [
        { area_name: '静岡県中部', level: 'danger', lat: 34.9, lng: 138.2, type: 'kikikuru', hazard: 'land', observed_at: OBSERVED_AT },
      ],
    });
    const errors = await gotoAndCaptureErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const mapId = await page.getByTestId('live-stream-map-event-kikikuru').getAttribute('data-event-id');
    const popupId = await page.getByTestId('live-stream-rain-popup').getAttribute('data-event-id');
    expect(mapId).toBeTruthy();
    expect(mapId).toBe(popupId);
    await expect(page.getByTestId('live-stream-rain-active')).toHaveText('静岡県中部');
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('静岡県中部');
    expect(errors.pageErrors).toEqual([]);
  });

  test('3: railway event id is identical on map marker and panel list item', async ({ page }) => {
    await mockAllLiveApis(page, {
      railItems: [
        {
          railway_id: 'rail-sync-001', railway_name: '中央線快速', operator_name: 'JR東日本',
          status: 'suspended', status_label: '見合わせ', description: '人身事故', severity: 3, updated_at: OBSERVED_AT,
        },
      ],
    });
    const errors = await gotoAndCaptureErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId('live-stream-map-event-railway')).toHaveAttribute('data-event-id', 'rail-sync-001');
    await expect(page.getByTestId('live-stream-rail-list-item')).toHaveAttribute('data-event-id', 'rail-sync-001');
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('中央線快速');
    expect(errors.pageErrors).toEqual([]);
  });

  test('4: stale content is not left behind when the store updates (eq event disappears when it stops qualifying)', async ({ page }) => {
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ items: [
        { event_id: 'eq-sync-002', lat: 24.8, lng: 141.8, magnitude: 6.4, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: '宮古島北西沖' },
      ]}),
    }));
    await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
    await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));

    const errors = await gotoAndCaptureErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await expect(page.getByTestId('live-stream-map-event-earthquake')).toHaveCount(1);

    // 次の fetch サイクルで 0 件へ更新 (route を差し替えて再取得をシミュレートする代わりに再訪問)
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
      contentType: 'application/json', body: JSON.stringify({ items: [] }),
    }));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);

    await expect(page.getByTestId('live-stream-map-event-earthquake')).toHaveCount(0);
    await expect(page.getByTestId('live-stream-earthquake-popup')).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });

  test('5: empty data across all APIs -> no marker, calm panels, monitoring ticker', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCaptureErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    await expect(page.getByTestId('live-stream-center').getByText('現在、表示対象なし')).toBeVisible();
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('監視中');
    expect(errors.pageErrors).toEqual([]);
  });

  test('6: API 500 across all endpoints -> no crash, no demo fallback, waiting-for-data ticker', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCaptureErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`), { strict: false });
    await page.waitForTimeout(500);

    await expect(page.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    await expect(page.getByTestId(/^live-stream-pulse-/)).toHaveCount(0);
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('取得を確認中');
    expect(errors.pageErrors).toEqual([]);
  });

  test('7: invalid JSON from earthquake API -> no crash, no demo fallback', async ({ page }) => {
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: 'not json {{{' }));
    await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
    await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));

    const errors = await gotoAndCaptureErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(500);

    await expect(page.getByTestId('live-stream-map-event-earthquake')).toHaveCount(0);
    await expect(page.getByTestId('live-stream-pulse-earthquake')).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });

  test('8: state=calm -> no marker, calm panels, monitoring ticker regardless of mocked data', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [{ event_id: 'eq-should-not-show', lat: 24.8, lng: 141.8, magnitude: 6.4, max_intensity: '5弱', occurred_at: OBSERVED_AT, epicenter_name: 'ダミー' }],
    });
    const errors = await gotoAndCaptureErrors(page, streamUrl(`?state=calm&chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    await expect(page.getByTestId(/^live-stream-pulse-/)).toHaveCount(0);
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('監視中');
    expect(errors.pageErrors).toEqual([]);
  });

  test('9: demo=1 reflects demo events through the same pipeline on map, panel and ticker', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(page, streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_NOW}`));

    const mapId = await page.getByTestId('live-stream-pulse-earthquake').getAttribute('data-event-id');
    const popupId = await page.getByTestId('live-stream-earthquake-popup').getAttribute('data-event-id');
    expect(mapId).toBeTruthy();
    expect(mapId).toBe(popupId);
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('岩手県沖');
    // demo は従来の pulse testid を使う (map-event-* ではない) — 既存E2E互換を維持
    await expect(page.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });

  test('10: map stays non-interactive while event-driven markers are shown', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [{ event_id: 'eq-sync-003', lat: 24.8, lng: 141.8, magnitude: 6.4, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: '宮古島北西沖' }],
    });
    await gotoAndCaptureErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.locator('.leaflet-control-zoom')).toHaveCount(0);
  });

  test('11: /live regression unaffected by event-store wiring', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/live`);

    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    expect(errors.pageErrors).toEqual([]);
  });
});
