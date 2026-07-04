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

function kikiArea(id, level, lat, lng) {
  return { area_name: id, level, type: 'kikikuru', hazard: 'land', lat, lng, observed_at: OBSERVED_AT };
}

function railItem(id, name, status, statusLabel, severity) {
  return { railway_id: id, railway_name: name, operator_name: 'テスト鉄道', status, status_label: statusLabel, description: `${name}情報`, severity, updated_at: OBSERVED_AT };
}

test.describe('/live/stream — Stream Phase 3-D 全体ステータス・カテゴリバッジ・件数の同期', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('1: earthquake badge count matches the number of qualifying earthquake events', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [
        eqItem('eq-1', 24.8, 141.8, 6.4, '5弱'),
        eqItem('eq-2', 35.0, 139.0, 5.5, '4'),
      ],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const badge = page.getByTestId('live-stream-category-badge-earthquake');
    await expect(badge).toHaveAttribute('data-count', '2');
    await expect(page.locator('#ct-eq')).toHaveText('2');
    expect(errors).toEqual([]);
  });

  test('2: rain badge count is the sum of rain + kikikuru events', async ({ page }) => {
    await mockAllLiveApis(page, {
      kikiAreas: [kikiArea('静岡県中部', 'danger', 34.9, 138.2)],
      rainAreas: [{ area_name: '愛知県東部', level: 'warning', type: 'rain', lat: 34.9, lng: 137.3, observed_at: OBSERVED_AT }],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const badge = page.getByTestId('live-stream-category-badge-rain');
    await expect(badge).toHaveAttribute('data-count', '2');
    await expect(page.locator('#ct-rain')).toHaveText('2');
    expect(errors).toEqual([]);
  });

  test('3: railway badge count matches the number of affected-line events', async ({ page }) => {
    await mockAllLiveApis(page, {
      railItems: [
        railItem('rail-1', '中央線快速', 'suspended', '見合わせ', 4),
        railItem('rail-2', '山手線', 'delay', '遅延', 2),
      ],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const badge = page.getByTestId('live-stream-category-badge-railway');
    await expect(badge).toHaveAttribute('data-count', '2');
    await expect(page.locator('#ct-rail')).toHaveText('2');
    expect(errors).toEqual([]);
  });

  test('4: tide badge stays 0 when no tide/water event reaches the store (alert judgement not wired yet)', async ({ page }) => {
    await mockAllLiveApis(page, {
      tideStations: [{ id: 'ST1', name: '東京', lat: 35.65, lon: 139.77, prefecture: '東京都', has_data: true }],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const badge = page.getByTestId('live-stream-category-badge-tide');
    await expect(badge).toHaveAttribute('data-count', '0');
    await expect(page.locator('#ct-tide')).toHaveText('0');
    expect(errors).toEqual([]);
  });

  test('5: map marker count matches the header category count for earthquake', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [eqItem('eq-1', 24.8, 141.8, 6.4, '5弱'), eqItem('eq-2', 35.0, 139.0, 5.5, '4')],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const markerCount = await page.getByTestId('live-stream-map-event-earthquake').count();
    const badgeCount = await page.getByTestId('live-stream-category-badge-earthquake').getAttribute('data-count');
    expect(String(markerCount)).toBe(badgeCount);
    expect(errors).toEqual([]);
  });

  test('6: panel data-count/data-status matches EventStore summary for earthquake', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [eqItem('eq-1', 24.8, 141.8, 6.4, '5弱')],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const panel = page.getByTestId('live-stream-panel-earthquake');
    await expect(panel).toHaveAttribute('data-count', '1');
    await expect(panel).toHaveAttribute('data-status', 'high');
    expect(errors).toEqual([]);
  });

  test('7: overallStatus becomes non-calm (data-lv=high) when a high-severity event exists', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [eqItem('eq-1', 24.8, 141.8, 6.4, '5弱')],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-lv', 'high');
    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-stream-overall-status', 'alert');
    expect(errors).toEqual([]);
  });

  test('8: no events with successful fetch -> calm/monitoring', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-lv', 'calm');
    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-stream-overall-status', 'calm');
    await expect(page.getByTestId('live-stream-category-badge-earthquake')).toHaveAttribute('data-count', '0');
    expect(errors).toEqual([]);
  });

  test('9: total API failure is not displayed as calm (distinct wording, not "-" miscounted as 0)', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(500);

    await expect(page.getByTestId('live-stream-alert-level')).not.toHaveAttribute('data-stream-overall-status', 'calm');
    await expect(page.locator('#level-text')).not.toHaveText('平常 · 監視中');
    await expect(page.locator('#ct-eq')).toHaveText('-');
    await expect(page.getByTestId('live-stream-category-badge-earthquake')).toHaveAttribute('data-status', 'error');
    expect(errors).toEqual([]);
  });

  test('10: demo=1 synchronizes badge/status/panel/ticker through the same pipeline', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_NOW}`));

    const eqBadge = page.getByTestId('live-stream-category-badge-earthquake');
    await expect(eqBadge).toHaveAttribute('data-count', '2');
    await expect(page.locator('#ct-eq')).toHaveText('2');
    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-lv', 'high');
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('岩手県沖');
    expect(errors).toEqual([]);
  });

  test('11: state=calm forces badge count 0, overallStatus calm, and no markers regardless of mocked data', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [eqItem('eq-should-not-count', 24.8, 141.8, 6.4, '5弱')],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?state=calm&chrome=off&demoNow=${DEMO_NOW}`));

    await expect(page.getByTestId('live-stream-category-badge-earthquake')).toHaveAttribute('data-count', '0');
    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-lv', 'calm');
    await expect(page.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('12: stale/invalid events are excluded from the badge count', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [
        eqItem('eq-valid', 24.8, 141.8, 6.4, '5弱'),
        eqItem('eq-nocoord', null, null, 6.0, '5弱'),
        { event_id: 'eq-old', lat: 24.8, lng: 141.8, magnitude: 6.0, max_intensity: '5弱', occurred_at: '2020-01-01T00:00:00+09:00', epicenter_name: '古い震源' },
      ],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    // eq-nocoord (座標なし) と eq-old (12h窓の外) は adapter 側で既に除外されるため、
    // 有効イベントは eq-valid の1件のみとなる。
    await expect(page.getByTestId('live-stream-category-badge-earthquake')).toHaveAttribute('data-count', '1');
    await expect(page.locator('#ct-eq')).toHaveText('1');
    expect(errors).toEqual([]);
  });

  test('13: /live regression unaffected by status/badge sync wiring', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);

    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
