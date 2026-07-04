'use strict';
const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う
const BASE = 'http://127.0.0.1:8080';
const DEMO_1942 = '2026-06-30T19:42:00%2B09:00';

test.use({ viewport: { width: 1920, height: 1080 } });

function makeItem(id, t, m, s, lat, lng) {
  return {
    event_id: id, occurred_at: t, epicenter_name: `震源${id}`,
    magnitude: m, max_intensity: s,
    lat: lat || 38.0, lng: lng || 141.0,
    depth_km: 30, tsunami_info: null,
    isImportant: true, importantReasons: [], municipalityIntensityAvailable: true,
  };
}

// Docker 向けには ** グロブで full URL を補足する
const EQ_ROUTE = '**/api/live/earthquakes/history**';

// --- 0件表示確認 ---
test('earthquake 0 items shows target-none and count 0', async ({ page }) => {
  await page.route(EQ_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ days:1, source:'p2p', fallback:false,
        municipalityIntensityAvailable:true, updated_at: new Date().toISOString(),
        count:0, items:[] }) })
  );
  const errs = [], perrs = [];
  page.on('console', m => { if (m.type()==='error') errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(2000);

  await expect(page.getByText('現在 対象なし').first()).toBeVisible();
  await expect(page.locator('#ct-eq')).toHaveText('0');
  await expect(page.getByTestId('live-stream-pulse-earthquake')).toHaveCount(0);
  expect(errs, 'console errors').toEqual([]);
  expect(perrs, 'page errors').toEqual([]);
});

// --- 12時間フィルタ確認 ---
test('12h filter excludes events older than demoNow-12h', async ({ page }) => {
  // demoNow=19:42 → cutoff=07:42  A:19:21→OK  B:08:00→OK  C:06:00→除外
  await page.route(EQ_ROUTE, route =>
    route.fulfill({ status:200, contentType:'application/json',
      body: JSON.stringify({ days:1, source:'p2p', fallback:false,
        municipalityIntensityAvailable:true, updated_at: new Date().toISOString(), count:3,
        items:[
          makeItem('A', '2026-06-30T19:21:00+09:00', 6.1, '5弱'),
          makeItem('B', '2026-06-30T08:00:00+09:00', 4.2, '2'),
          makeItem('C', '2026-06-30T06:00:00+09:00', 3.5, '1'),
        ]}) })
  );
  const errs = [];
  page.on('console', m => { if (m.type()==='error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(2000);

  await expect(page.locator('#ct-eq')).toHaveText('2');
  await expect(page.getByTestId('live-stream-earthquake-list').getByText('震源A')).toBeVisible();
  await expect(page.getByTestId('live-stream-earthquake-list').getByText('震源C')).toHaveCount(0);
  // 中央マップは本番データモード (Stream Phase 3-B) では live-stream-map-event-* を使う
  // (live-stream-pulse-* は demo=1 専用)
  await expect(page.getByTestId('live-stream-map-event-earthquake').first()).toBeVisible();
  expect(errs, 'console errors').toEqual([]);
});

// --- activeTarget 優先順位確認 ---
test('activeTarget selects highest intensity first', async ({ page }) => {
  await page.route(EQ_ROUTE, route =>
    route.fulfill({ status:200, contentType:'application/json',
      body: JSON.stringify({ days:1, source:'p2p', fallback:false,
        municipalityIntensityAvailable:true, updated_at: new Date().toISOString(), count:2,
        items:[
          makeItem('LOW',  '2026-06-30T19:30:00+09:00', 6.5, '3',   35.7, 139.7),
          makeItem('HIGH', '2026-06-30T18:00:00+09:00', 5.0, '5弱', 39.0, 141.0),
        ]}) })
  );
  const errs = [];
  page.on('console', m => { if (m.type()==='error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(2000);

  // 震度5弱のHIGHが優先される（震度3のLOWよりM6.5でも後）
  await expect(page.getByTestId('live-stream-earthquake-active')).toHaveText('震源HIGH');
  expect(errs, 'console errors').toEqual([]);
});

// --- 取得失敗 (HTTP 500) ---
test('API 500 shows no page error and uses fallback scene', async ({ page }) => {
  await page.route(EQ_ROUTE, route =>
    route.fulfill({ status: 500, body: 'Internal Server Error' })
  );
  const errs = [], perrs = [];
  // "Failed to load resource" はブラウザ組み込み動作のため除外し、JS コードの console.error のみ確認
  page.on('console', m => { if (m.type()==='error' && !m.text().includes('Failed to load resource')) errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(2000);

  // 取得失敗後は error 状態 → ヘッダー '-'
  await expect(page.locator('#ct-eq')).toHaveText('-');
  // 画面は壊れない
  await expect(page.getByTestId('live-stream-panel-earthquake')).toBeVisible();
  expect(perrs, 'page errors').toEqual([]);
  expect(errs, 'JS console errors').toEqual([]);
});

// --- 取得失敗 (不正JSON) ---
test('invalid JSON from API causes no page error', async ({ page }) => {
  await page.route(EQ_ROUTE, route =>
    route.fulfill({ status: 200, body: 'not json {{{' })
  );
  const perrs = [], errs = [];
  page.on('pageerror', e => perrs.push(e.message));
  page.on('console', m => { if (m.type()==='error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(2000);
  expect(perrs, 'page errors').toEqual([]);
  expect(errs, 'console errors').toEqual([]);
});
