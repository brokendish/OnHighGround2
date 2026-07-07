'use strict';

const { test, expect } = require('@playwright/test');

const BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${BASE}/live/stream${query}${sep}focusSpeed=test&runtimeSpeed=test&demoNow=${DEMO_NOW}`;
}

function railItem(overrides) {
  return Object.assign({
    railway_id: 'rail-test',
    railway_name: '京王線',
    operator_name: '検証事業者',
    status: 'suspended',
    status_label: '運転見合わせ',
    severity: 4,
    description: '検証用の運転見合わせです。',
    updated_at: OBSERVED_AT,
    source: '検証',
    lat: 35.69,
    lng: 139.69,
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

async function waitForRailFit(page, count) {
  await page.waitForFunction(expected => {
    const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
    return !!(d && d.railwayMiniMap && Array.isArray(d.railwayMiniMap.fittedLineIds)
      && d.railwayMiniMap.fittedLineIds.length === expected
      && d.railwayMiniMap.bounds);
  }, count, { timeout: 15000 });
  await page.waitForTimeout(700);
  return page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
}

function containsPoint(bounds, lat, lng) {
  return bounds.south <= lat && lat <= bounds.north && bounds.west <= lng && lng <= bounds.east;
}

function containsBounds(outer, inner) {
  return outer.south <= inner.south && outer.north >= inner.north
    && outer.west <= inner.west && outer.east >= inner.east;
}

test.describe('/live/stream railway bounds verification', () => {
  test('1: multiple affected lines spread east-west/north-south are fit together', async ({ page }) => {
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-fit-keio', railway_name: '京王線', lat: 35.69, lng: 139.69 }),
      railItem({ railway_id: 'rail-fit-tobu', railway_name: '東武東上線', lat: 35.69, lng: 139.69 }),
      railItem({ railway_id: 'rail-fit-yurakucho', railway_name: '有楽町線', lat: 35.69, lng: 139.69 }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const diag = await waitForRailFit(page, 3);

    expect(diag.fittedLineIds.sort()).toEqual(['rail-fit-keio', 'rail-fit-tobu', 'rail-fit-yurakucho']);
    expect(diag.zoom).toBeLessThan(11);
    expect(errors).toEqual([]);
  });

  test('2: single affected line uses the whole GeoJSON line bounds, not only a representative point', async ({ page }) => {
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-single-tobu', railway_name: '東武東上線', lat: 35.69, lng: 139.69 }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const diag = await waitForRailFit(page, 1);
    const lineBounds = await page.evaluate(() => LiveStreamRailwayLayer.getBoundsForNames(['東武東上線']));

    expect(diag.zoomedEventId).toBe('rail-single-tobu');
    expect(containsBounds(diag.bounds, lineBounds)).toBe(true);
    expect(errors).toEqual([]);
  });

  test('3: OSM names with operator prefix match bare affected names such as 有楽町線', async ({ page }) => {
    await mockLiveApis(page, [
      railItem({
        railway_id: 'rail-prefix-yurakucho',
        railway_name: '有楽町線',
        operator_name: '東京メトロ',
        lat: 35.69,
        lng: 139.69,
      }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const diag = await waitForRailFit(page, 1);
    const lineBounds = await page.evaluate(() => LiveStreamRailwayLayer.getBoundsForNames(['有楽町線']));

    expect(lineBounds).toBeTruthy();
    expect(lineBounds.matchedNames).toContain('有楽町線');
    expect(containsBounds(diag.bounds, lineBounds)).toBe(true);
    expect(errors).toEqual([]);
  });

  test('4: only lines missing from GeoJSON use representative-point fallback in mixed mode', async ({ page }) => {
    const fallback = { lat: 35.30, lng: 140.20 };
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-mixed-known', railway_name: '京王線', lat: 35.69, lng: 139.69 }),
      railItem({
        railway_id: 'rail-mixed-unknown',
        railway_name: '検証架空線',
        operator_name: '架空鉄道',
        lat: fallback.lat,
        lng: fallback.lng,
      }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const diag = await waitForRailFit(page, 2);
    const keioBounds = await page.evaluate(() => LiveStreamRailwayLayer.getBoundsForNames(['京王線']));

    expect(containsBounds(diag.bounds, keioBounds)).toBe(true);
    expect(containsPoint(diag.bounds, fallback.lat, fallback.lng)).toBe(true);
    expect(diag.fittedLineIds.sort()).toEqual(['rail-mixed-known', 'rail-mixed-unknown']);
    expect(errors).toEqual([]);
  });

  test('5: representative fallback applies to every unknown line, avoiding the old single-west-side bias', async ({ page }) => {
    const west = { lat: 35.45, lng: 139.20 };
    const east = { lat: 35.82, lng: 140.15 };
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-unknown-west', railway_name: '検証西線', lat: west.lat, lng: west.lng }),
      railItem({ railway_id: 'rail-unknown-east', railway_name: '検証東線', lat: east.lat, lng: east.lng }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const diag = await waitForRailFit(page, 2);

    expect(containsPoint(diag.bounds, west.lat, west.lng)).toBe(true);
    expect(containsPoint(diag.bounds, east.lat, east.lng)).toBe(true);
    expect(diag.fittedLineIds.sort()).toEqual(['rail-unknown-east', 'rail-unknown-west']);
    expect(errors).toEqual([]);
  });

  test('6: the mini-map bounds do not rotate every 8 seconds even while detail text rotates', async ({ page }) => {
    await mockLiveApis(page, [
      railItem({ railway_id: 'rail-stable-keio', railway_name: '京王線' }),
      railItem({ railway_id: 'rail-stable-tobu', railway_name: '東武東上線' }),
      railItem({ railway_id: 'rail-stable-yurakucho', railway_name: '有楽町線' }),
    ]);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&chrome=off'));
    const first = await waitForRailFit(page, 3);
    await page.waitForTimeout(9200);
    const second = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);

    expect(second.fittedLineIds.sort()).toEqual(first.fittedLineIds.sort());
    expect(Math.abs(second.zoom - first.zoom)).toBeLessThan(0.01);
    expect(Math.abs(second.center.lat - first.center.lat)).toBeLessThan(0.001);
    expect(Math.abs(second.center.lng - first.center.lng)).toBeLessThan(0.001);
    expect(errors).toEqual([]);
  });

  test('7: /live and /live/stream both remain displayable', async ({ page }) => {
    const streamErrors = await gotoAndCapturePageErrors(page, streamUrl('?state=calm&chrome=off'));
    await page.waitForFunction(() => document.getElementById('rail-map').classList.contains('leaflet-container'), null, { timeout: 8000 });
    expect(streamErrors).toEqual([]);

    const liveErrors = await gotoAndCapturePageErrors(page, `${BASE}/live`);
    await page.waitForTimeout(1200);
    expect(liveErrors).toEqual([]);
  });
});
