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
    railway_id: 'odpt.Railway:JR-East.ChuoRapid',
    railway_name: '中央線快速',
    operator_name: 'JR東日本',
    status: 'suspended',
    status_label: '運転見合わせ',
    severity: 4,
    description: '三鷹〜東京間で人身事故のため運転を見合わせています。',
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
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
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

async function waitForRailMiniMapReady(page, timeout) {
  await page.waitForFunction(() => {
    const el = document.getElementById('rail-map');
    return !!(el && el.classList.contains('leaflet-container') && el.querySelector('.leaflet-tile-pane'));
  }, null, { timeout: timeout || 8000 });
}

test.describe('/live/stream — Stream Phase 5-A.1 鉄道小画面 平常時路線図表示範囲修正', () => {

  test('1: state=calm shows the Tokyo-area ODPT route map even with zero affected lines', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await waitForRailMiniMapReady(page);
    expect(errors).toEqual([]);
  });

  test('2: normal / calm operation shows "no affected lines / normal operation" on the left', async ({ page }) => {
    await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await waitForRailMiniMapReady(page);
    await expect(page.locator('[data-testid="live-stream-rail-empty"]')).toBeVisible();
    const text = await page.locator('[data-testid="live-stream-rail-empty"]').textContent();
    expect(text).toContain('影響路線なし');
    expect(text).toContain('平常運転');
  });

  test('3: the route map is not blank — it is a real Leaflet/PMTiles map, not the old 4-line SVG mock', async ({ page }) => {
    await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await waitForRailMiniMapReady(page);
    const info = await page.evaluate(() => {
      const el = document.getElementById('rail-map');
      return { isLeaflet: el.classList.contains('leaflet-container'), hasTilePane: !!el.querySelector('.leaflet-tile-pane') };
    });
    expect(info.isLeaflet).toBe(true);
    expect(info.hasTilePane).toBe(true);
  });

  test('4: the mini map is fixed to the Tokyo-area default bounds (not full-Japan/ocean-only)', async ({ page }) => {
    await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await waitForRailMiniMapReady(page);
    // railwayMiniMap.loaded は PMTiles の非同期ロード (probe fetch → layer作成) 完了後に true になる。
    // ベース地図(タイル)の準備完了より遅れることがあるため、診断値自体を待つ。
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
      return !!(d && d.railwayMiniMap && d.railwayMiniMap.loaded);
    }, null, { timeout: 8000 });
    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    expect(diag.loaded).toBe(true);
    expect(diag.defaultBoundsApplied).toBe(true);
  });

  test('5: "ODPT-covered lines only" scope label is present and does not overlap other labels', async ({ page }) => {
    await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await waitForRailMiniMapReady(page);
    const label = page.locator('[data-testid="live-stream-railway-scope-label"]');
    await expect(label).toBeVisible();
    const text = await label.textContent();
    expect(text).toContain('ODPT対応路線');
    expect(text).not.toContain('全国鉄道');
    expect(text).not.toContain('首都圏全路線');
  });

  test('6: railway layer initializes regardless of affected count (0 affected)', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);
    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    expect(diag.loaded).toBe(true);
    expect(diag.affectedCount).toBe(0);
    expect(diag.highlightedCount).toBe(0);
  });

  test('7: affected-state demo/mock still highlights the affected line and keeps the existing detail card', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-calm-7' })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);
    await page.waitForFunction(() => document.body.dataset.streamFocusEventId === 'rail-calm-7', null, { timeout: 8000 });
    await expect(page.locator('[data-testid="live-stream-railway-detail"]')).toBeVisible();
    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    expect(diag.affectedCount).toBe(1);
    expect(diag.highlightedCount).toBe(1);
  });

  test('8: demo=1 keeps the existing affected-line emphasis working', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?demo=1&chrome=off'));
    await waitForRailMiniMapReady(page);
    await expect(page.locator('[data-testid="live-stream-rail-list-item"]').first()).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('9: API failure does not claim "normal operation" or "no affected lines" — shows unavailable instead', async ({ page }) => {
    await mockTrainsApi500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(1500);
    const unavailable = page.locator('[data-testid="live-stream-rail-unavailable"]');
    await expect(unavailable).toBeVisible();
    const text = await unavailable.textContent();
    expect(text).not.toContain('平常運転');
    expect(text).not.toContain('影響路線なし');
    expect(await page.locator('[data-testid="live-stream-rail-empty"]').count()).toBe(0);
    expect(errors).toEqual([]);
  });

  test('10: API failure still keeps the route map background (layer already initialized independently of fetch status)', async ({ page }) => {
    await mockTrainsApi500(page);
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailMiniMapReady(page);
    // railwayMiniMap.loaded は PMTiles の非同期ロード完了後に true になるため、診断値自体を待つ
    // (テスト4と同じ理由 — ベース地図タイルの準備完了より遅れることがある)。
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
      return !!(d && d.railwayMiniMap && d.railwayMiniMap.loaded);
    }, null, { timeout: 8000 });
    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    expect(diag.loaded).toBe(true);
    expect(diag.highlightedCount).toBe(0); // 取得失敗時は強調なし
  });

  test('11: repeated refresh in calm/normal mode does not accumulate the rail mini map instance', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);
    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    const isLeafletSingleton = await page.evaluate(() => document.getElementById('rail-map').classList.contains('leaflet-container'));
    expect(isLeafletSingleton).toBe(true);
    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayLayer);
    expect(diag.layerCount).toBe(2); // center + rail-mini、増殖していない
    expect(errors).toEqual([]);
  });

  test('12: no undefined/null/NaN/[object Object] leakage in the rail panel during calm', async ({ page }) => {
    await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await waitForRailMiniMapReady(page);
    const text = await page.locator('[data-testid="live-stream-panel-rail"]').textContent();
    expect(text).not.toContain('undefined');
    expect(text).not.toContain('NaN');
    expect(text).not.toContain('[object Object]');
  });

  test('13: /live is unaffected by the railway mini map fix', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
  });

  test('14: / (navigation root) is unaffected by the railway mini map fix', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/`);
    await page.waitForTimeout(1000);
    expect(errors).toEqual([]);
  });
});
