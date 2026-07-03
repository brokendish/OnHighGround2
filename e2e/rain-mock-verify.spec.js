'use strict';
const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う
const BASE = 'http://127.0.0.1:8080';
const DEMO_1942 = '2026-06-30T19:42:00%2B09:00';

test.use({ viewport: { width: 1920, height: 1080 } });

// Docker 向けには ** グロブで full URL を補足する
const SUMMARY_ROUTE = '**/api/live/summary**';

function makeSummary(kikiAreas, rainAreas) {
  return {
    updated_at: new Date().toISOString(),
    status: 'ok',
    rain: {
      status: 'ok', evaluated: true,
      summary: { strong_rain_detected: rainAreas.length > 0, warning_area_count: rainAreas.length, danger_area_count: 0 },
      areas: rainAreas,
    },
    kikikuru: {
      status: 'ok', evaluated: true,
      summary: { danger_detected: kikiAreas.length > 0, warning_area_count: kikiAreas.length, danger_area_count: 0 },
      areas: kikiAreas,
    },
    earthquake: { status: 'ok', evaluated: true, summary: {}, areas: [] },
    tsunami:    { status: 'ok', evaluated: true, summary: {}, areas: [] },
    storm_surge:{ status: 'ok', evaluated: true, summary: {}, areas: [] },
    dangerous_areas: [],
    integrated_dangerous_regions: [],
    observation: { rain_area_count: rainAreas.length, kikikuru_area_count: kikiAreas.length, storm_surge_area_count: 0, dangerous_area_count: 0, max_areas: 5 },
  };
}

function makeKikiArea(id, level, hazard, lat, lng, label) {
  return {
    id, label: label || `${id}付近`, prefecture: id, area_name: label || `${id}付近`,
    level, type: 'kikikuru', hazard: hazard || 'land',
    source: 'jma_kikikuru', lat, lng,
    observed_at: '2026-06-30T19:20:00+09:00', description: 'テスト',
  };
}

function makeRainArea(id, level, lat, lng, label) {
  return {
    id, label: label || `${id}付近`, prefecture: id, area_name: label || `${id}付近`,
    level, type: 'rain',
    source: 'jma_nowcast_scan', lat, lng,
    observed_at: '2026-06-30T19:20:00+09:00', description: 'テスト',
  };
}

// --- 0件表示確認 ---
test('rain 0 areas: shows target-none, count 0, no rain pulse', async ({ page }) => {
  await page.route(SUMMARY_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeSummary([], [])) })
  );
  const errs = [], perrs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  // rain status: 0件 → 対象なし
  await expect(page.locator('#ct-rain')).toHaveText('0');
  await expect(page.getByTestId('live-stream-pulse-rain')).toHaveCount(0);
  await expect(page.getByTestId('live-stream-rain-status')).toBeVisible();
  expect(errs,  'console errors').toEqual([]);
  expect(perrs, 'page errors').toEqual([]);
});

// --- キキクル危険 1件 ---
test('kikikuru danger area: shows in targets and pulse, ct-rain=1', async ({ page }) => {
  const kikiAreas = [
    makeKikiArea('shizuoka', 'danger', 'land', 34.98, 138.38, '静岡県中部付近'),
  ];
  await page.route(SUMMARY_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeSummary(kikiAreas, [])) })
  );
  const errs = [], perrs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  // 中央地図にパルス表示
  await expect(page.getByTestId('live-stream-pulse-rain')).toBeVisible();
  // 件数
  await expect(page.locator('#ct-rain')).toHaveText('1');
  // ポップアップ
  await expect(page.getByTestId('live-stream-rain-popup')).toBeVisible();
  await expect(page.getByTestId('live-stream-rain-active')).toHaveText('静岡県中部付近');
  // 左パネルリスト
  await expect(page.getByTestId('live-stream-rain-list-item').first()).toBeVisible();
  expect(errs,  'console errors').toEqual([]);
  expect(perrs, 'page errors').toEqual([]);
});

// --- 危険 > 警戒 優先順位 ---
test('danger area takes priority over warning in activeTarget', async ({ page }) => {
  const kikiAreas = [
    makeKikiArea('area_warning', 'warning', 'land', 35.0, 139.0, '警戒エリア'),
    makeKikiArea('area_danger',  'danger',  'land', 34.5, 138.5, '危険エリア'),
  ];
  await page.route(SUMMARY_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeSummary(kikiAreas, [])) })
  );
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  // 危険エリアが先頭に来る
  await expect(page.getByTestId('live-stream-rain-active')).toHaveText('危険エリア');
  expect(errs, 'console errors').toEqual([]);
});

// --- API 500 エラー ---
test('API summary 500 shows no page error, rain header shows -', async ({ page }) => {
  await page.route(SUMMARY_ROUTE, route =>
    route.fulfill({ status: 500, body: 'Internal Server Error' })
  );
  const errs = [], perrs = [];
  page.on('console', m => {
    if (m.type() === 'error' && !m.text().includes('Failed to load resource')) errs.push(m.text());
  });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  await expect(page.locator('#ct-rain')).toHaveText('-');
  await expect(page.getByTestId('live-stream-panel-rain')).toBeVisible();
  expect(perrs, 'page errors').toEqual([]);
  expect(errs,  'JS console errors').toEqual([]);
});

// --- 不正JSON ---
test('invalid JSON from summary API causes no page error', async ({ page }) => {
  await page.route(SUMMARY_ROUTE, route =>
    route.fulfill({ status: 200, body: 'not json {{{' })
  );
  const errs = [], perrs = [];
  page.on('pageerror', e => perrs.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  expect(perrs, 'page errors').toEqual([]);
  expect(errs,  'console errors').toEqual([]);
});

// --- watch は alerts に表示されるが targets には出ない ---
test('watch level appears in alerts list but not in targets/popup', async ({ page }) => {
  const kikiAreas = [
    makeKikiArea('watch_area', 'watch', 'land', 36.0, 138.0, '注意エリア'),
  ];
  await page.route(SUMMARY_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeSummary(kikiAreas, [])) })
  );
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  // watch は targets に含まれないので popup/pulse なし
  await expect(page.getByTestId('live-stream-rain-popup')).toHaveCount(0);
  await expect(page.getByTestId('live-stream-pulse-rain')).toHaveCount(0);
  // ct-rain = 0 (warning/danger ベースの statusCount)
  await expect(page.locator('#ct-rain')).toHaveText('0');
  // 左パネルリストには watch も表示される
  await expect(page.getByTestId('live-stream-rain-list-item').first()).toBeVisible();
  expect(errs, 'console errors').toEqual([]);
});
