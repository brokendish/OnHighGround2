'use strict';

const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う (他 live-stream 系 spec と同じ規約)
const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

// focusSpeed=test でタイマーを数百msに短縮し、E2Eを高速化する (通常運用のデフォルトは変えない)。
function streamUrl(query) {
  return `${DOCKER_BASE}/live/stream${query}${query.includes('?') ? '&' : '?'}focusSpeed=test`;
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

async function mockAllLiveApis500(page) {
  for (const pattern of [
    '**/api/live/earthquakes/history**',
    '**/api/live/summary**',
    '**/api/live/trains/summary**',
    '**/api/live/tide/stations**',
  ]) {
    await page.route(pattern, route => route.fulfill({ status: 500, body: 'internal error' }));
  }
}

async function gotoAndCapturePageErrors(page, url) {
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message || String(e)));
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return pageErrors;
}

function eqItem(id, lat, lng, magnitude, intensity) {
  return { event_id: id, lat, lng, magnitude, max_intensity: intensity, occurred_at: OBSERVED_AT, epicenter_name: `震源${id}` };
}

async function waitForFocusMode(page, mode, timeout) {
  await page.waitForFunction(m => document.body.dataset.streamFocusMode === m, mode, { timeout: timeout || 5000 });
}

test.describe('/live/stream — Stream Phase 4-B 自動巡回ビュー演出・フォーカス表示', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('1: HUD is shown while focused', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));

    const hud = page.getByTestId('stream-focus-hud');
    await expect(hud).toBeHidden(); // overview 直後は非表示
    await waitForFocusMode(page, 'focus');
    await page.waitForTimeout(150);
    await expect(hud).toBeVisible();
    await expect(hud.locator('#focus-hud-title')).toContainText('注目');
    expect(errors).toEqual([]);
  });

  test('2: HUD data-focus-event-id matches body[data-stream-focus-event-id]', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    await page.waitForTimeout(150);

    const bodyEventId = await page.evaluate(() => document.body.dataset.streamFocusEventId);
    const bodyMode = await page.evaluate(() => document.body.dataset.streamFocusMode);
    await expect(page.getByTestId('stream-focus-hud')).toHaveAttribute('data-focus-event-id', bodyEventId);
    await expect(page.getByTestId('stream-focus-hud')).toHaveAttribute('data-focus-mode', bodyMode);
    expect(bodyEventId).toBe('eq-focus-1');
    expect(errors).toEqual([]);
  });

  test('3: focus event id matches the active map marker', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    await page.waitForTimeout(150);

    await expect(page.locator('[data-testid="live-stream-map-event-earthquake"][data-active="true"]')).toHaveAttribute('data-event-id', 'eq-focus-1');
    expect(errors).toEqual([]);
  });

  test('4: focus event id matches the active panel item', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    await page.waitForTimeout(150);

    const activePanel = page.locator('[data-focused="true"]');
    await expect(activePanel).toHaveAttribute('data-event-id', 'eq-focus-1');
    await expect(page.getByTestId('live-stream-earthquake-popup')).toHaveAttribute('data-active', 'true');
    expect(errors).toEqual([]);
  });

  test('5: ticker focus event id matches focus event id', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    await page.waitForTimeout(150);

    await expect(page.getByTestId('live-stream-ticker-body')).toHaveAttribute('data-focus-event-id', 'eq-focus-1');
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('注目');
    expect(errors).toEqual([]);
  });

  test('6: no stale active markup remains while in overview', async ({ page }) => {
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(1000);

    expect(await page.evaluate(() => document.body.dataset.streamFocusMode)).toBe('overview');
    await expect(page.getByTestId('stream-focus-hud')).toBeHidden();
    await expect(page.locator('[data-active="true"]')).toHaveCount(0);
    await expect(page.getByTestId('live-stream-ticker-body')).toHaveAttribute('data-focus-event-id', '');
    expect(errors).toEqual([]);
  });

  test('7: active markup does not persist after returning to overview', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    // focus -> returning -> overview の一巡を待つ
    await waitForFocusMode(page, 'overview', 8000);
    await page.waitForTimeout(150);

    await expect(page.getByTestId('stream-focus-hud')).toBeHidden();
    await expect(page.locator('[data-active="true"]')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('8: state=calm never shows an alert-styled HUD, no marker/pulse', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-should-not-focus', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?state=calm&chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(1500);

    await expect(page.getByTestId('stream-focus-hud')).toBeHidden();
    expect(await page.getByTestId('stream-focus-hud').getAttribute('data-focus-mode')).toBe('overview');
    await expect(page.getByTestId(/^live-stream-pulse-/)).toHaveCount(0);
    await expect(page.getByTestId(/^live-stream-map-event-/)).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('9: total API failure does not focus, no demo fallback, no stale HUD', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(1500);

    expect(await page.evaluate(() => document.body.dataset.streamFocusMode)).toBe('overview');
    await expect(page.getByTestId('stream-focus-hud')).toBeHidden();
    await expect(page.getByTestId(/^live-stream-pulse-/)).toHaveCount(0);
    await expect(page.getByTestId('live-stream-ticker-body')).toContainText('取得を確認中');
    expect(errors).toEqual([]);
  });

  test('10: with focusSpeed=test, HUD/marker/panel/ticker follow the cycling target', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [eqItem('eq-focus-a', 24.8, 141.8, 6.4, '5弱')],
      kikiAreas: [{ area_name: '静岡県中部', level: 'danger', lat: 34.9, lng: 138.2, type: 'kikikuru', hazard: 'land', observed_at: OBSERVED_AT }],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');
    const firstId = await page.evaluate(() => document.body.dataset.streamFocusEventId);

    await page.waitForFunction(prev => document.body.dataset.streamFocusEventId !== prev
      || document.body.dataset.streamFocusMode !== 'focus', firstId, { timeout: 5000 });

    let secondId = null;
    for (let i = 0; i < 8; i++) {
      await page.waitForTimeout(200);
      const mode = await page.evaluate(() => document.body.dataset.streamFocusMode);
      const id = await page.evaluate(() => document.body.dataset.streamFocusEventId);
      if (mode === 'focus' && id && id !== firstId) { secondId = id; break; }
    }
    expect(secondId).toBeTruthy();
    await page.waitForTimeout(150);

    // HUD / marker / panel / ticker が全て secondId で一致していること
    expect(await page.getByTestId('stream-focus-hud').getAttribute('data-focus-event-id')).toBe(secondId);
    await expect(page.locator(`[data-active="true"][data-event-id="${secondId}"]`).first()).toBeVisible();
    await expect(page.getByTestId('live-stream-ticker-body')).toHaveAttribute('data-focus-event-id', secondId);
    expect(errors).toEqual([]);
  });

  // 回帰テスト: demo シーンはカテゴリごとに複数 target を持つ (地震2件・キキクル2件・鉄道4件) が、
  // 小窓地図/ポップアップは 8秒巡回で選ばれた1件のみを表示する (Stream Phase 3-A 互換)。
  // focus 対象が「現在巡回中でない」demo target を指したとき、以前は active marker/panel item が
  // 一つも存在しない状態になっていた (静岡県中部が表示中に愛知県東部へ focus した場合等)。
  test('10b: every demo focus target (not just the currently cycled one) has an active marker/panel', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_NOW}`));

    const seenIds = new Set();
    const missingActive = [];
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(150);
      const mode = await page.evaluate(() => document.body.dataset.streamFocusMode);
      const id = await page.evaluate(() => document.body.dataset.streamFocusEventId);
      if (mode !== 'focus' || !id || seenIds.has(id)) continue;
      seenIds.add(id);
      const activeCount = await page.locator(`[data-active="true"][data-event-id="${id}"]`).count();
      if (activeCount === 0) missingActive.push(id);
    }

    expect(seenIds.size).toBeGreaterThan(1);
    expect(missingActive).toEqual([]);
    expect(errors).toEqual([]);
  });

  test('11: map stays non-interactive throughout focus cycling', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await waitForFocusMode(page, 'focus');

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.locator('.leaflet-control-zoom')).toHaveCount(0);
  });

  test('12: Phase 3-D badge/count/status sync still works', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-focus-1', 24.8, 141.8, 6.4, '5弱')] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl(`?chrome=off&demoNow=${DEMO_NOW}`));
    await page.waitForTimeout(400);

    await expect(page.getByTestId('live-stream-category-badge-earthquake')).toHaveAttribute('data-count', '1');
    await expect(page.locator('#ct-eq')).toHaveText('1');
    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-lv', 'high');
    expect(errors).toEqual([]);
  });

  test('13: /live regression unaffected by focus view wiring', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);

    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
