'use strict';
const { test, expect } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8080';
const DEMO_1942 = '2026-06-30T19:42:00%2B09:00';

test.use({ viewport: { width: 1920, height: 1080 } });

// Docker 向け ** グロブ
const TIDE_LIST_ROUTE   = '**/api/live/tide/stations';
const TIDE_DETAIL_ROUTE = '**/api/live/tide/stations/**';

// 実行時の今日の JST 日付文字列 (records フィルタと合わせる)
function jstDateStr() {
  const d = new Date();
  const jst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  return jst.getUTCFullYear() + '-'
    + String(jst.getUTCMonth() + 1).padStart(2, '0') + '-'
    + String(jst.getUTCDate()).padStart(2, '0');
}

function makeDetail(id, name, lat, lon, todayStr) {
  return {
    station_id: id, name, lat, lon, prefecture: '東京都',
    current_tide_cm: 155,
    next_high_tide: { time: `${todayStr}T05:38:00+09:00`, tide_cm: 184, remaining_minutes: 240 },
    next_low_tide:  { time: `${todayStr}T11:42:00+09:00`, tide_cm: 28,  remaining_minutes: 600 },
    records: [
      { datetime: `${todayStr}T00:00:00+09:00`, tide_cm: 120, station: id },
      { datetime: `${todayStr}T06:00:00+09:00`, tide_cm: 184, station: id },
      { datetime: `${todayStr}T12:00:00+09:00`, tide_cm: 50,  station: id },
      { datetime: `${todayStr}T18:00:00+09:00`, tide_cm: 170, station: id },
      { datetime: `${todayStr}T23:00:00+09:00`, tide_cm: 100, station: id },
    ],
    extremes: {
      high_tides: [{ time: `${todayStr}T05:38:00+09:00`, tide_cm: 184 }],
      low_tides:  [{ time: `${todayStr}T11:42:00+09:00`, tide_cm: 28  }],
    },
  };
}

// --- 0 地点: 対象なし表示 ---
test('tide 0 stations: ct-tide=0, no crash', async ({ page }) => {
  await page.route(TIDE_LIST_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ count: 0, stations: [] }) })
  );
  const errs = [], perrs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  // 取得成功・0件 → ct-tide=0 (取得失敗ではないので '-' にならない)
  await expect(page.locator('#ct-tide')).toHaveText('0');
  await expect(page.getByTestId('live-stream-panel-tide')).toBeVisible();
  await expect(page.getByTestId('live-stream-tide-status')).toBeVisible();
  expect(errs,  'console errors').toEqual([]);
  expect(perrs, 'page errors').toEqual([]);
});

// --- 2 地点実データ: station/testid/curve が表示される ---
test('tide 2 real stations: shows station names, testids, no crash', async ({ page }) => {
  const today = jstDateStr();

  await page.route(TIDE_LIST_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ count: 2, stations: [
        { id: 'MOCK_TOKYO',    name: '東京', lat: 35.65, lon: 139.77, prefecture: '東京都', has_data: true },
        { id: 'MOCK_YOKOHAMA', name: '横浜', lat: 35.44, lon: 139.64, prefecture: '神奈川県', has_data: true },
      ]}) })
  );
  await page.route(TIDE_DETAIL_ROUTE, route => {
    const url = route.request().url();
    const id  = decodeURIComponent(url.split('/').pop());
    const name = id === 'MOCK_TOKYO' ? '東京' : '横浜';
    const lat  = id === 'MOCK_TOKYO' ? 35.65  : 35.44;
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeDetail(id, name, lat, 139.77, today)) });
  });

  const errs = [], perrs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  // 実データ由来の testid が存在する
  await expect(page.getByTestId('live-stream-tide-station').first()).toBeVisible();
  await expect(page.getByTestId('live-stream-tide-station-name').first()).toBeVisible();
  await expect(page.getByTestId('live-stream-tide-high').first()).toBeVisible();
  await expect(page.getByTestId('live-stream-tide-low').first()).toBeVisible();
  await expect(page.getByTestId('live-stream-tide-source').first()).toBeVisible();
  await expect(page.getByTestId('live-stream-tide-current').first()).toBeVisible();
  // 実データ: curve が描画される
  await expect(page.getByTestId('live-stream-tide-curve').first()).toBeAttached();
  // MVP: 高潮警報ロジック未実装なので ct-tide=0
  await expect(page.locator('#ct-tide')).toHaveText('0');
  expect(errs,  'console errors').toEqual([]);
  expect(perrs, 'page errors').toEqual([]);
});

// --- 潮位リスト API 500: ct-tide='-', 画面壊れない ---
test('tide stations API 500: ct-tide=-, no page error', async ({ page }) => {
  await page.route(TIDE_LIST_ROUTE, route =>
    route.fulfill({ status: 500, body: 'Internal Server Error' })
  );
  const errs = [], perrs = [];
  page.on('console', m => {
    if (m.type() === 'error' && !m.text().includes('Failed to load resource')) errs.push(m.text());
  });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  await expect(page.locator('#ct-tide')).toHaveText('-');
  await expect(page.getByTestId('live-stream-panel-tide')).toBeVisible();
  expect(perrs, 'page errors').toEqual([]);
  expect(errs,  'JS console errors').toEqual([]);
});

// --- 詳細 API 500: 0 地点として graceful degradation ---
test('tide detail API 500: graceful fallback, no crash', async ({ page }) => {
  await page.route(TIDE_LIST_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ count: 1, stations: [
        { id: 'MOCK_ST', name: '東京', lat: 35.65, lon: 139.77, prefecture: '東京都', has_data: true },
      ]}) })
  );
  await page.route(TIDE_DETAIL_ROUTE, route =>
    route.fulfill({ status: 500, body: 'Internal Server Error' })
  );
  const errs = [], perrs = [];
  page.on('console', m => {
    if (m.type() === 'error' && !m.text().includes('Failed to load resource')) errs.push(m.text());
  });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  // 詳細がすべて失敗 → 地点0扱い → ct-tide=0 (未取得ではなく空)
  await expect(page.locator('#ct-tide')).toHaveText('0');
  await expect(page.getByTestId('live-stream-panel-tide')).toBeVisible();
  expect(perrs, 'page errors').toEqual([]);
  expect(errs,  'JS console errors').toEqual([]);
});

// --- 不正 JSON: 画面壊れない ---
test('invalid JSON from tide API causes no page error', async ({ page }) => {
  await page.route(TIDE_LIST_ROUTE, route =>
    route.fulfill({ status: 200, body: 'not json {{{' })
  );
  const errs = [], perrs = [];
  page.on('pageerror', e => perrs.push(e.message));
  page.on('console', m => {
    if (m.type() === 'error' && !m.text().includes('Failed to load resource')) errs.push(m.text());
  });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  expect(perrs, 'page errors').toEqual([]);
  expect(errs,  'console errors').toEqual([]);
});

// --- records なし: データなし表示でも画面壊れない ---
test('tide station with no records: shows データなし SVG, no crash', async ({ page }) => {
  const today = jstDateStr();

  await page.route(TIDE_LIST_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ count: 1, stations: [
        { id: 'MOCK_EMPTY', name: '静岡', lat: 34.97, lon: 138.38, prefecture: '静岡県', has_data: true },
      ]}) })
  );
  await page.route(TIDE_DETAIL_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({
        station_id: 'MOCK_EMPTY', name: '静岡', lat: 34.97, lon: 138.38, prefecture: '静岡県',
        current_tide_cm: null,
        next_high_tide: null, next_low_tide: null,
        records: [],
        extremes: { high_tides: [], low_tides: [] },
      }) })
  );
  const errs = [], perrs = [];
  page.on('pageerror', e => perrs.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  // 地点名が表示される
  await expect(page.getByTestId('live-stream-tide-station-name').first()).toBeVisible();
  // records なし → 'データなし' SVG が表示される
  await expect(page.getByTestId('live-stream-panel-tide')).toBeVisible();
  expect(perrs, 'page errors').toEqual([]);
  expect(errs,  'console errors').toEqual([]);
});
