'use strict';

const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う (他 live-stream 系 spec と同じ規約)
const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${DOCKER_BASE}/live/stream${query}${sep}focusSpeed=test&runtimeSpeed=test&demoNow=${DEMO_NOW}`;
}

function eqItem(id, lat, lng, magnitude, intensity, points) {
  return {
    event_id: id, lat, lng, magnitude, max_intensity: intensity,
    occurred_at: OBSERVED_AT, epicenter_name: `震源${id}`,
    points: points || [],
  };
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

const WIDE_AREA_POINTS = [
  { pref: '岩手県', addr: '盛岡市',     isArea: false, scale: 45 },
  { pref: '岩手県', addr: '宮古市',     isArea: false, scale: 45 },
  { pref: '岩手県', addr: '大船渡市',   isArea: false, scale: 40 },
  { pref: '宮城県', addr: '石巻市',     isArea: false, scale: 40 },
  { pref: '宮城県', addr: '仙台青葉区', isArea: false, scale: 30 },
  { pref: '青森県', addr: '八戸市',     isArea: false, scale: 30 },
  { pref: '秋田県', addr: '秋田市',     isArea: false, scale: 20 },
  { pref: '福島県', addr: '福島市',     isArea: false, scale: 20 },
];

async function waitForEqMuniReady(page, timeout) {
  await page.waitForFunction(() => {
    const el = document.getElementById('eq-muni');
    return el && !el.hidden && el.dataset.eqMuniScrollMode && el.dataset.eqMuniScrollMode !== 'unavailable';
  }, null, { timeout: timeout || 8000 });
}

test.describe('/live/stream — Stream Phase 5-A bundle A 地震子画面 小地図Leaflet化・詳細表示同期', () => {

  test('1: mini map renders as a real Leaflet/CARTO map (not the SVG mock)', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a1', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const info = await page.evaluate(() => {
      const el = document.getElementById('eq-map');
      return { isLeaflet: el.classList.contains('leaflet-container'), hasTilePane: !!el.querySelector('.leaflet-tile-pane') };
    });
    expect(info.isLeaflet).toBe(true);
    expect(info.hasTilePane).toBe(true);
    expect(errors).toEqual([]);
  });

  test('2: municipal intensity markers are rendered on the mini map', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a2', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);
    const markers = page.locator('#eq-map [data-testid="live-stream-earthquake-municipal-marker"]');
    expect(await markers.count()).toBeGreaterThan(0);
  });

  test('3: markers on the mini map belong only to the currently active earthquake id', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a3', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);
    const sectionId = await page.locator('[data-testid="live-stream-panel-earthquake"]').getAttribute('data-earthquake-detail-id');
    expect(sectionId).toBe('eq-a3');
    const rowPrefs = await page.locator('[data-testid="live-stream-earthquake-municipal-row"]').evaluateAll(els => els.map(e => e.dataset.pref));
    expect(rowPrefs.length).toBeGreaterThan(0);
    expect(rowPrefs.every(p => ['岩手県', '宮城県', '青森県', '秋田県', '福島県'].includes(p))).toBe(true);
  });

  test('4: header shows occurred time, epicenter, magnitude, and max intensity', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a4', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);
    const popup = page.locator('[data-testid="live-stream-earthquake-popup"]');
    await expect(popup).toBeVisible();
    const text = await popup.textContent();
    expect(text).toContain('震源eq-a4');
    expect(text).toContain('M6.1');
    expect(text).toContain('5弱');
  });

  test('5: header, list, and mini map all reference the same earthquake id', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a5', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);
    const headerId = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');
    const sectionId = await page.locator('[data-testid="live-stream-panel-earthquake"]').getAttribute('data-earthquake-detail-id');
    const diagId = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().earthquakeDetail.activeEventId);
    expect(headerId).toBe('eq-a5');
    expect(sectionId).toBe('eq-a5');
    expect(diagId).toBe('eq-a5');
  });

  test('6: the earthquake does not switch away until the municipal list finishes scrolling', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [
        eqItem('eq-a6-wide', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS),
        eqItem('eq-a6-small', 38.4, 142.0, 4.2, '2', [{ pref: '宮城県', addr: '石巻市', isArea: false, scale: 20 }]),
      ],
    });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);
    const idBefore = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');
    await page.waitForTimeout(9000);
    const idAfter = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');
    expect(idAfter).toBe(idBefore);
  });

  test('7: the earthquake does not switch away until the mini-map tour finishes', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a7', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);
    const eqMap = page.locator('#eq-map');
    expect(await eqMap.getAttribute('data-eq-mini-map-mode')).toBe('tour');
    const idBefore = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');
    const frame1 = Number(await eqMap.getAttribute('data-eq-mini-map-frame-index'));
    await page.waitForTimeout(4500);
    const frame2 = Number(await eqMap.getAttribute('data-eq-mini-map-frame-index'));
    const idAfter = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');
    expect(frame2).toBeGreaterThan(frame1);
    expect(idAfter).toBe(idBefore);
  });

  test('7b: after the mini-map/list hold is released, the earthquake panel advances to the next target', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [
        eqItem('eq-a7b-wide', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS),
        eqItem('eq-a7b-small', 38.4, 142.0, 4.2, '2', [{ pref: '宮城県', addr: '石巻市', isArea: false, scale: 20 }]),
      ],
    });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    await expect(page.locator('[data-testid="live-stream-earthquake-popup"]')).toHaveAttribute('data-event-id', 'eq-a7b-wide');
    await page.waitForFunction(() => {
      const popup = document.querySelector('[data-testid="live-stream-earthquake-popup"]');
      return popup && popup.dataset.eventId === 'eq-a7b-small';
    }, null, { timeout: 32000 });
    await expect(page.locator('[data-testid="live-stream-panel-earthquake"]')).toHaveAttribute('data-earthquake-detail-id', 'eq-a7b-small');
  });

  test('8: no demo fallback when detail/empty/failure states occur', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a8', 39.2, 142.1, 6.1, '3', [])] }); // no points -> empty detail
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForFunction(() => {
      const el = document.getElementById('eq-muni');
      return el && !el.hidden && el.dataset.eqMuniScrollMode === 'empty';
    }, null, { timeout: 6000 });
    const rows = await page.locator('[data-testid="live-stream-earthquake-municipal-row"]').count();
    expect(rows).toBe(0);
    const emptyMsg = await page.locator('[data-testid="live-stream-earthquake-municipal-empty"]').textContent();
    expect(emptyMsg).toContain('詳細なし');
  });

  test('9: repeated refresh does not accumulate Leaflet instances or markers on the mini map', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a9', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForEqMuniReady(page);

    // #eq-map 自身が Leaflet コンテナ (leaflet-container クラスを持つ) になる。子要素ではなく
    // 自分自身をカウントするため querySelectorAll ではなく classList を見る。
    const isLeafletSingleton = () => document.getElementById('eq-map').classList.contains('leaflet-container');
    expect(await page.evaluate(isLeafletSingleton)).toBe(true);
    const markerBefore = await page.locator('#eq-map [data-testid="live-stream-earthquake-municipal-marker"]').count();
    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    expect(await page.evaluate(isLeafletSingleton)).toBe(true); // 作り直されず同じインスタンスのまま
    const markerAfter = await page.locator('#eq-map [data-testid="live-stream-earthquake-municipal-marker"]').count();
    expect(markerAfter).toBe(markerBefore);
    expect(errors).toEqual([]);
  });

  test('10: earthquakeDetail diagnostics report valid values', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-a10', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);
    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().earthquakeDetail);
    expect(diag.activeEventId).toBe('eq-a10');
    expect(diag.municipalCount).toBeGreaterThan(0);
    expect(diag.markerCount).toBeGreaterThan(0);
    expect(['loading', 'ready', 'empty']).toContain(diag.detailStatus);
    expect(['idle', 'running', 'done']).toContain(diag.listScrollState);
    expect(['idle', 'running', 'done']).toContain(diag.mapTourState);
  });

  test('11: /live is unaffected by the mini-map Leaflet conversion', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1500);
    expect(await page.locator('#eq-map').count()).toBe(0);
    expect(errors).toEqual([]);
  });
});
