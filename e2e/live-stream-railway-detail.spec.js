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

// #rail-detail-viewport は無スクロールで約280文字収まる (実測ベース) ため、スクロール挙動を
// 意味のある形でテストするにはそれを超える長さが必要。
const LONG_DESC = '中央線快速は三鷹〜東京間で人身事故の影響により、運転を見合わせています。振替輸送は西武線・京王線でご利用いただけます。運転再開の見込みは現在のところ立っておらず、詳細が分かり次第お知らせします。ご迷惑をおかけして大変申し訳ございません。なお、振替輸送区間内であっても、一部の駅では混雑により入場規制を行う場合がございます。あらかじめご了承ください。運行状況は今後も随時更新いたしますので、最新情報をご確認のうえご利用ください。お急ぎのところ大変恐れ入りますが、復旧まで今しばらくお待ちいただきますよう、何卒よろしくお願い申し上げます。';

async function mockAllLiveApis(page, { eqItems, rainAreas, kikiAreas, railItems, tideStations } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ items: eqItems != null ? eqItems : [] }),
  }));
  await page.route('**/api/live/summary**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ rain: { status: 'ok', areas: rainAreas != null ? rainAreas : [] }, kikikuru: { status: 'ok', areas: kikiAreas != null ? kikiAreas : [] } }),
  }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ items: railItems != null ? railItems : [] }),
  }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ stations: tideStations != null ? tideStations : [] }),
  }));
}

async function mockAllLiveApis500(page) {
  for (const pattern of [
    '**/api/live/earthquakes/history**', '**/api/live/summary**',
    '**/api/live/trains/summary**', '**/api/live/tide/stations**',
  ]) {
    await page.route(pattern, route => route.fulfill({ status: 500, body: 'internal error' }));
  }
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

async function waitForRailFocus(page, id, timeout) {
  await page.waitForFunction(want => document.body.dataset.streamFocusEventId === want, id, { timeout: timeout || 6000 });
}

test.describe('/live/stream — Stream Phase 5-A bundle B 鉄道子画面 詳細化', () => {

  test('1: the focused affected line shows a detail card', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-b1', description: LONG_DESC })] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailFocus(page, 'rail-b1');
    await expect(page.locator('[data-testid="live-stream-railway-detail"]')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('2: line name, operator, status, and updated time are shown (non-committal when unavailable)', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-b2', operator_name: '', updated_at: '', description: LONG_DESC })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailFocus(page, 'rail-b2');
    expect(await page.locator('[data-testid="live-stream-railway-detail-name"]').textContent()).toContain('中央線快速');
    expect(await page.locator('[data-testid="live-stream-railway-detail-status"]').textContent()).toContain('運転見合わせ');
    expect(await page.locator('[data-testid="live-stream-railway-detail-operator"]').textContent()).toBe('事業者不明');
    expect(await page.locator('[data-testid="live-stream-railway-detail-updated"]').textContent()).toBe('更新時刻不明');
  });

  test('3: a long description body auto-scrolls', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-b3', description: LONG_DESC })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailFocus(page, 'rail-b3');
    await expect(page.locator('#rail-detail')).toHaveAttribute('data-railway-detail-scroll-mode', 'scrolling');
    const bodyText = await page.locator('[data-testid="live-stream-railway-detail-body"]').first().textContent();
    expect(bodyText).toContain('人身事故');
  });

  test('4: a short description does not scroll', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-b4', description: '一部列車に遅れ' })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailFocus(page, 'rail-b4');
    await expect(page.locator('#rail-detail')).toHaveAttribute('data-railway-detail-scroll-mode', 'static');
  });

  test('5: the focused line does not switch away while the description is still scrolling (hold)', async ({ page }) => {
    await mockAllLiveApis(page, {
      railItems: [
        railItem({ railway_id: 'rail-b5-long', railway_name: '中央線快速', description: LONG_DESC, severity: 4 }),
        railItem({ railway_id: 'rail-b5-short', railway_name: '山手線', description: '遅延', severity: 2 }),
      ],
    });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailFocus(page, 'rail-b5-long');
    expect(await page.evaluate(() => document.body.dataset.streamPanelHold)).toBe('railway-detail');
    await page.waitForTimeout(2500); // > focus dwell(900ms) を超えても切り替わらないことを確認
    expect(await page.evaluate(() => document.body.dataset.streamFocusEventId)).toBe('rail-b5-long');
  });

  test('6: no demo fallback / no crash when the train API fails', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(1500);
    await expect(page.locator('#rail-overlay')).toBeHidden();
    await expect(page.locator('#rail-detail')).toBeHidden();
    expect(errors).toEqual([]);
  });

  test('7: railwayDetail diagnostics report valid values, and hold does not block unrelated categories', async ({ page }) => {
    test.setTimeout(45000); // hold時間が上限(30000ms)に貼り付く長文でテストするため、既定の30s枠を広げる
    // scrolling 判定の閾値 (#rail-detail-viewport 実測ベースの260文字) を超える長さが必要。
    // この閾値を超える長さは hold時間 (文字数*150ms) が既に上限 (30000ms) に貼り付く領域のため、
    // 「無関係カテゴリの focus は hold 中でも進む」ことをその時間内で検証する。
    const mediumDesc = LONG_DESC;
    await mockAllLiveApis(page, {
      railItems: [railItem({ railway_id: 'rail-b7', description: mediumDesc })],
      eqItems: [{ event_id: 'eq-b7', lat: 35.0, lng: 139.0, magnitude: 5.5, max_intensity: '4', occurred_at: OBSERVED_AT, epicenter_name: 'x', points: [] }],
    });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailFocus(page, 'rail-b7');
    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayDetail);
    expect(diag.activeRailwayEventId).toBe('rail-b7');
    expect(diag.hasScrollableDetail).toBe(true);
    expect(diag.holdActive).toBe(true);

    // 鉄道の hold 中でも、focus は他カテゴリ (地震) へ巡回できる (無関係カテゴリを止めない)。
    await page.waitForFunction(() => document.body.dataset.streamFocusEventId === 'eq-b7', null, { timeout: 35000 });
    expect(await page.evaluate(() => document.body.dataset.streamFocusEventId)).toBe('eq-b7');
  });

  test('8: state=calm regression — no crash, no rail detail', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-b8', description: LONG_DESC })] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=calm'));
    await page.waitForTimeout(1000);
    await expect(page.locator('#rail-overlay')).toBeHidden();
    await expect(page.locator('#rail-detail')).toBeHidden();
    expect(errors).toEqual([]);
  });

  test('9: /live is unaffected by the railway detail feature', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1500);
    expect(await page.locator('#rail-overlay').count()).toBe(0);
    expect(errors).toEqual([]);
  });
});
