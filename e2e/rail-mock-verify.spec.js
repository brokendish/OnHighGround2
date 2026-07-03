'use strict';
const { test, expect } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8080';
const DEMO_1942 = '2026-06-30T19:42:00%2B09:00';

test.use({ viewport: { width: 1920, height: 1080 } });

// Docker 向け ** グロブ
const TRAIN_ROUTE = '**/api/live/trains/summary**';

function makeTrainSummary(items) {
  return {
    status: 'ok',
    stale: false,
    scope: { mode: 'all' },
    updated_at: new Date().toISOString(),
    items: items || [],
  };
}

function makeTrainItem(id, name, operatorName, status, severity, description) {
  return {
    railway_id:    `odpt.Railway:${id}`,
    operator_id:   `odpt.Operator:${id.split('.')[0]}`,
    operator_name: operatorName,
    railway_name:  name,
    status:        status,
    status_label:  { delay: '遅延', partial_suspension: '一部運休', suspended: '運転見合わせ' }[status] || status,
    severity:      severity,
    description:   description || `${name}で${status}が発生しています。`,
    updated_at:    new Date().toISOString(),
    source:        'ODPT',
    lat:           35.69,
    lng:           139.69,
  };
}

// --- 0 件: ct-rail=0, empty 表示 ---
test('rail 0 affected: ct-rail=0, shows empty state', async ({ page }) => {
  await page.route(TRAIN_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeTrainSummary([])) })
  );
  const errs = [], perrs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  await expect(page.locator('#ct-rail')).toHaveText('0');
  await expect(page.getByTestId('live-stream-rail-empty')).toBeVisible();
  await expect(page.getByTestId('live-stream-panel-rail')).toBeVisible();
  expect(errs,  'console errors').toEqual([]);
  expect(perrs, 'page errors').toEqual([]);
});

// --- 遅延 1 件: リスト・testid・件数 ---
test('rail delay 1 line: shows in list, ct-rail=1, testids present', async ({ page }) => {
  const items = [
    makeTrainItem('TokyoMetro.Ginza', '銀座線', '東京メトロ', 'delay', 2, '上野駅での点検のため遅れています。'),
  ];
  await page.route(TRAIN_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeTrainSummary(items)) })
  );
  const errs = [], perrs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  await expect(page.locator('#ct-rail')).toHaveText('1');
  await expect(page.getByTestId('live-stream-rail-list-item').first()).toBeVisible();
  await expect(page.getByTestId('live-stream-rail-line-name').first()).toBeVisible();
  await expect(page.getByTestId('live-stream-rail-status').first()).toBeVisible();
  await expect(page.getByTestId('live-stream-rail-list').getByText('銀座線')).toBeVisible();
  expect(errs,  'console errors').toEqual([]);
  expect(perrs, 'page errors').toEqual([]);
});

// --- severity 高い方が先頭 ---
test('rail suspended > delay: suspended line listed first', async ({ page }) => {
  const items = [
    makeTrainItem('TokyoMetro.Ginza',   '銀座線',   '東京メトロ', 'delay',     2, '遅延中'),
    makeTrainItem('TokyoMetro.Marunouchi', '丸ノ内線', '東京メトロ', 'suspended', 4, '運転見合わせ中'),
  ];
  await page.route(TRAIN_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeTrainSummary(items)) })
  );
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  // 丸ノ内線(suspended, severity=4) が銀座線(delay, severity=2) より先頭になる
  const firstItem = page.getByTestId('live-stream-rail-line-name').first();
  await expect(firstItem).toHaveText('丸ノ内線');
  expect(errs, 'console errors').toEqual([]);
});

// --- API 500: ct-rail='-', 画面壊れない ---
test('rail API 500: ct-rail=-, no page error', async ({ page }) => {
  await page.route(TRAIN_ROUTE, route =>
    route.fulfill({ status: 500, body: 'Internal Server Error' })
  );
  const errs = [], perrs = [];
  page.on('console', m => {
    if (m.type() === 'error' && !m.text().includes('Failed to load resource')) errs.push(m.text());
  });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  await expect(page.locator('#ct-rail')).toHaveText('-');
  await expect(page.getByTestId('live-stream-panel-rail')).toBeVisible();
  await expect(page.getByTestId('live-stream-rail-unavailable')).toBeVisible();
  expect(perrs, 'page errors').toEqual([]);
  expect(errs,  'JS console errors').toEqual([]);
});

// --- status:unavailable: ct-rail='-', 画面壊れない ---
test('rail status unavailable: ct-rail=-, shows unavailable state', async ({ page }) => {
  await page.route(TRAIN_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ status: 'unavailable', stale: false, scope: {}, items: [] }) })
  );
  const errs = [], perrs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => perrs.push(e.message));
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  await expect(page.locator('#ct-rail')).toHaveText('-');
  await expect(page.getByTestId('live-stream-rail-unavailable')).toBeVisible();
  expect(perrs, 'page errors').toEqual([]);
  expect(errs,  'console errors').toEqual([]);
});

// --- 不正 JSON: 画面壊れない ---
test('invalid JSON from train API causes no page error', async ({ page }) => {
  await page.route(TRAIN_ROUTE, route =>
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

// --- normal 状態は除外される ---
test('normal status items are excluded from the affected list', async ({ page }) => {
  const items = [
    makeTrainItem('TokyoMetro.Ginza', '銀座線', '東京メトロ', 'normal', 0, '平常です'),
    makeTrainItem('TokyoMetro.Tozai', '東西線', '東京メトロ', 'delay',  2, '遅延中'),
  ];
  await page.route(TRAIN_ROUTE, route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(makeTrainSummary(items)) })
  );
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(`${BASE}/live/stream?state=alert&chrome=off&demoNow=${DEMO_1942}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  // 銀座線(normal) は除外、東西線(delay) のみ表示
  await expect(page.locator('#ct-rail')).toHaveText('1');
  await expect(page.getByTestId('live-stream-rail-list').getByText('東西線')).toBeVisible();
  const items2 = page.getByTestId('live-stream-rail-list-item');
  await expect(items2).toHaveCount(1);
  expect(errs, 'console errors').toEqual([]);
});
