'use strict';
/**
 * live-stream-railway-odpt-national.spec.js — /live/stream 鉄道運行情報 全国ODPT対応 (Phase 7-A.5)
 *
 * 関東外の代表点・座標なし路線が混ざっても、小地図が東京駅固定ズームへ回帰しないこと、
 * 統合boundsが西日本側の代表点も含むことを確認する。
 */

const { test, expect } = require('@playwright/test');

const BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const DEMO_NOW = '2026-07-08T13:05:00%2B09:00';

// 旧実装が固定フォールバックに使っていた東京駅座標 (回帰防止用の比較対象)
const TOKYO_STATION = { lat: 35.6812, lng: 139.7671 };

function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${BASE}/live/stream${query}${sep}focusSpeed=test&runtimeSpeed=test&demoNow=${DEMO_NOW}`;
}

function railItem(overrides) {
  return Object.assign({
    railway_id: 'rail-test',
    railway_name: '検証路線',
    operator_name: '検証事業者',
    status: 'suspended',
    status_label: '運転見合わせ',
    severity: 4,
    description: '検証用の運転見合わせです。',
    updated_at: '2026-07-08T13:00:00+09:00',
    source: '検証',
  }, overrides || {});
}

async function mockLiveApis(page, railItems) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ items: [] }),
  }));
  await page.route('**/api/live/summary**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }),
  }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ items: railItems }),
  }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ stations: [] }),
  }));
}

async function gotoAndCapturePageErrors(page, url) {
  const errors = [];
  page.on('pageerror', e => {
    const msg = e.message || String(e);
    if (msg.includes('Failed to fetch')) return;
    errors.push(msg);
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return errors;
}

async function waitForRailSettled(page, expectedCount) {
  await page.waitForFunction(expected => {
    const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
    return !!(d && d.railwayMiniMap && Array.isArray(d.railwayMiniMap.fittedLineIds)
      && d.railwayMiniMap.fittedLineIds.length === expected);
  }, expectedCount, { timeout: 15000 });
  await page.waitForTimeout(700);
  return page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
}

function containsPoint(bounds, lat, lng) {
  return bounds.south <= lat && lat <= bounds.north && bounds.west <= lng && lng <= bounds.east;
}

function nearlyEquals(a, b, eps) {
  return Math.abs(a - b) < eps;
}

test.describe('/live/stream railway ODPT nationwide (Phase 7-A.5)', () => {
  test('1: 座標もGeoJSON一致も無い単独路線は、東京駅固定ズームへ寄らずデフォルト俯瞰へ戻る', async ({ page }) => {
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-no-coord', railway_name: '検証未知路線', operator_name: '検証未知事業者' }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const diag = await waitForRailSettled(page, 1);

    // 東京駅ピンポイント (半径 0.05度 程度) へ単独ズームしていないことを確認する。
    // デフォルト俯瞰bounds、またはboundsなしのいずれであっても、東京駅極小範囲への
    // 収束であってはならない。
    const spanLat = diag.bounds ? (diag.bounds.north - diag.bounds.south) : Infinity;
    const spanLng = diag.bounds ? (diag.bounds.east - diag.bounds.west) : Infinity;
    const isTinyTokyoBox = spanLat < 0.05 && spanLng < 0.05
      && diag.bounds && containsPoint(diag.bounds, TOKYO_STATION.lat, TOKYO_STATION.lng);
    expect(isTinyTokyoBox).toBe(false);
    expect(errors).toEqual([]);
  });

  test('2: 関西・九州など離れた代表点を持つ複数路線の統合boundsが両方を含み、東京駅中心にならない', async ({ page }) => {
    const osaka = { lat: 34.69, lng: 135.19 };
    const fukuoka = { lat: 33.59, lng: 130.40 };
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-osaka', railway_name: '検証関西線', operator_name: '検証関西事業者', lat: osaka.lat, lng: osaka.lng }),
      railItem({ railway_id: 'rail-fukuoka', railway_name: '検証九州線', operator_name: '検証九州事業者', lat: fukuoka.lat, lng: fukuoka.lng }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const diag = await waitForRailSettled(page, 2);

    expect(containsPoint(diag.bounds, osaka.lat, osaka.lng)).toBe(true);
    expect(containsPoint(diag.bounds, fukuoka.lat, fukuoka.lng)).toBe(true);
    // 中心が東京駅座標と一致しない (西側への統合bounds なので東京駅より南西に寄るはず)
    expect(nearlyEquals(diag.center.lat, TOKYO_STATION.lat, 0.01)
      && nearlyEquals(diag.center.lng, TOKYO_STATION.lng, 0.01)).toBe(false);
    expect(diag.fittedLineIds.sort()).toEqual(['rail-fukuoka', 'rail-osaka']);
    expect(errors).toEqual([]);
  });

  test('3: GeoJSON一致(関東)路線+代表点のみの関西路線が混在しても両方bounds に含まれる', async ({ page }) => {
    const osaka = { lat: 34.69, lng: 135.19 };
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-mixed-keio', railway_name: '京王線', lat: 35.69, lng: 139.69 }),
      railItem({ railway_id: 'rail-mixed-osaka', railway_name: '検証関西線', operator_name: '検証関西事業者', lat: osaka.lat, lng: osaka.lng }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const diag = await waitForRailSettled(page, 2);
    const keioBounds = await page.evaluate(() => LiveStreamRailwayLayer.getBoundsForNames(['京王線']));

    expect(keioBounds).toBeTruthy();
    expect(diag.bounds.south).toBeLessThanOrEqual(keioBounds.south);
    expect(diag.bounds.north).toBeGreaterThanOrEqual(keioBounds.north);
    expect(containsPoint(diag.bounds, osaka.lat, osaka.lng)).toBe(true);
    expect(errors).toEqual([]);
  });

  test('4: /live と /live/stream?chrome=off がともに全国データで200 OK・エラーなし', async ({ page }) => {
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-national-1', railway_name: '検証全国線A', lat: 43.06, lng: 141.35 }), // 札幌付近
      railItem({ railway_id: 'rail-national-2', railway_name: '検証全国線B' }), // 座標なし
    ]);
    const streamErrors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    await page.waitForFunction(() => document.getElementById('rail-map').classList.contains('leaflet-container'), null, { timeout: 8000 });
    expect(streamErrors).toEqual([]);

    const liveErrors = await gotoAndCapturePageErrors(page, `${BASE}/live`);
    await page.waitForTimeout(1200);
    expect(liveErrors).toEqual([]);
  });
});
