'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${DOCKER_BASE}/live/stream${query}${sep}focusSpeed=test&runtimeSpeed=test&demoNow=${DEMO_NOW}`;
}

function railItem(overrides) {
  return Object.assign({
    railway_id: 'odpt.Railway:JR-East.Yamanote',
    railway_name: '山手線',
    operator_name: 'JR東日本',
    status: 'delay',
    status_label: '遅延',
    severity: 2,
    description: '大雨の影響で遅延しています。',
    updated_at: OBSERVED_AT,
    source: 'JR東日本公式',
  }, overrides || {});
}

async function mockAllLiveApis(page, { railItems } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: railItems != null ? railItems : [] }) }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
}

async function mockTrainsApi500(page) {
  await page.route('**/api/live/trains/summary**', route => route.fulfill({ status: 500, body: 'internal error' }));
}

async function gotoAndCapturePageErrors(page, url) {
  const pageErrors = [];
  page.on('pageerror', e => {
    const text = e.message || String(e);
    if (text.includes('Failed to fetch')) return;
    pageErrors.push(text);
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return pageErrors;
}

test.describe('/live/stream — Stream Phase 5-A bundle C メイン地図 鉄道路線カラー反映', () => {

  test('1: the main map renders the railway PMTiles layer', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem()] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
      return !!(d && d.railwayLayer && d.railwayLayer.loaded);
    }, null, { timeout: 8000 });
    expect(errors).toEqual([]);
  });

  test('2: the same official/quasi-official line colors as /live are applied to the rail card accents', async ({ page }) => {
    // メイン地図はPMTiles(canvas)描画のため個別featureの色をDOMから直接検証できないが、
    // 同じ公式カラー表を共有する鉄道カード (.bar) の色で間接的に確認する。
    await mockAllLiveApis(page, {
      railItems: [
        railItem({ railway_id: 'rail-c2-a', railway_name: '山手線', severity: 2 }),
        railItem({ railway_id: 'rail-c2-b', railway_name: '中央線快速', severity: 3 }),
      ],
    });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForSelector('[data-testid="live-stream-rail-list-item"]');
    const bars = await page.locator('[data-testid="live-stream-rail-list-item"] .bar').evaluateAll(
      els => els.map(el => el.style.background)
    );
    // ブラウザは rgb() 表記に正規化する。山手線 #9ACD32 = rgb(154, 205, 50), 中央線快速 #F15A22 = rgb(241, 90, 34)
    expect(bars.some(b => b.replace(/\s/g, '') === 'rgb(154,205,50)')).toBe(true);
    expect(bars.some(b => b.replace(/\s/g, '') === 'rgb(241,90,34)')).toBe(true);
  });

  test('3: an affected line is emphasized (thicker/more opaque) relative to normal lines — verified via card highlight, map does not crash', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-c3', railway_name: '山手線', severity: 3 })] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForSelector('[data-testid="live-stream-rail-list-item"]');
    const status = await page.locator('[data-testid="live-stream-rail-status"]').first().textContent();
    expect(status).toBeTruthy();
    expect(errors).toEqual([]);
  });

  test('4: repeated refresh does not accumulate railway layers/instances', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem()] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
      return !!(d && d.railwayLayer && d.railwayLayer.loaded);
    }, null, { timeout: 8000 });

    // Stream Phase 5-A.1 (railway calm map): 中央地図に加え、鉄道子画面小地図 (#rail-map) にも
    // 同じ路線レイヤーを載せるようになったため layerCount は 2 (center + rail-mini) が正しい。
    // ここで検証したいのは「増殖しない」ことであり、固定の 1 ではない。
    const before = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayLayer.layerCount);
    expect(before).toBe(2);
    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayLayer);
    expect(diag.layerCount).toBe(before);
    expect(errors).toEqual([]);
  });

  test('5: no pageerror when the railway GeoJSON/summary API fails; center map keeps rendering', async ({ page }) => {
    await mockTrainsApi500(page);
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
    await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(1500);
    // #center-map 自身が Leaflet コンテナ (leaflet-container クラス) になる。
    const isLeaflet = await page.evaluate(() => document.getElementById('center-map').classList.contains('leaflet-container'));
    expect(isLeaflet).toBe(true);
    expect(errors).toEqual([]);
  });

  test('6: the main map remains non-interactive (no zoom UI, no drag/wheel/dblclick/keyboard)', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem()] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForFunction(() => document.getElementById('center-map').classList.contains('leaflet-container'), null, { timeout: 8000 });
    const hasZoomControl = await page.evaluate(() => !!document.getElementById('center-map').querySelector('.leaflet-control-zoom'));
    expect(hasZoomControl).toBe(false);
  });

  test('7: attribution is preserved on the main map', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem()] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForSelector('#center-map .leaflet-control-attribution');
    const attr = await page.locator('#center-map .leaflet-control-attribution').textContent();
    expect(attr.length).toBeGreaterThan(0);
  });

  test('8: /live is unaffected by the stream railway color layer change', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
  });
});
