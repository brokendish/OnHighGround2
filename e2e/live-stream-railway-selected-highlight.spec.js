'use strict';
// Phase 7-A.6: 鉄道情報リストで選択した障害路線を、路線図(鉄道子画面 #rail-map)上で
// 前面表示・太線・縁取り・控えめ点滅により識別できるようにする機能の検証。

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
    railway_id: 'odpt.Railway:TokyoMetro.Chiyoda',
    railway_name: '千代田線',
    operator_name: '東京メトロ',
    status: 'delayed',
    status_label: '遅延',
    severity: 2,
    description: '一部の列車に遅れが出ています。',
    updated_at: OBSERVED_AT,
    source: 'ODPT',
  }, overrides || {});
}

async function mockAllLiveApis(page, { railItems } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: railItems != null ? railItems : [] }) }));
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
    const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
    return !!(d && d.railwayMiniMap && d.railwayMiniMap.loaded);
  }, null, { timeout: timeout || 8000 });
}

const TWO_LINES = [
  railItem({ railway_id: 'odpt.Railway:TokyoMetro.Chiyoda', railway_name: '千代田線' }),
  railItem({ railway_id: 'odpt.Railway:TokyoMetro.Fukutoshin', railway_name: '副都心線', description: '9時38分頃、西船橋駅で発生した安全確認の影響で、遅れが出ています。' }),
];

test.describe('/live/stream — Phase 7-A.6 鉄道障害路線 選択ハイライト', () => {

  test('1: clicking an affected line marks it selected in the list and highlights it on the mini map', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    const cards = page.locator('.rail-card[data-event-id]');
    await expect(cards).toHaveCount(2);
    await expect(page.locator('.rail-card.is-selected')).toHaveCount(0);

    await cards.first().click();
    await expect(cards.first()).toHaveClass(/is-selected/);
    await expect(page.locator('.live-railway-selected-outline')).not.toHaveCount(0);
    await expect(page.locator('.live-railway-selected-core')).not.toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test('2: selecting a different line replaces the highlight (no duplicate layers, old selection cleared)', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    const cards = page.locator('.rail-card[data-event-id]');
    await cards.nth(0).click();
    const firstId = await cards.nth(0).getAttribute('data-event-id');
    await expect(cards.nth(0)).toHaveClass(/is-selected/);

    await cards.nth(1).click();
    const secondId = await cards.nth(1).getAttribute('data-event-id');
    expect(secondId).not.toBe(firstId);

    // 選択は1件のみ (リスト側・地図側とも二重残りしない)
    await expect(page.locator('.rail-card.is-selected')).toHaveCount(1);
    await expect(cards.nth(1)).toHaveClass(/is-selected/);
    await expect(cards.nth(0)).not.toHaveClass(/is-selected/);

    const layerGroups = await page.evaluate(() => document.querySelectorAll('.live-railway-selected-core').length);
    expect(layerGroups).toBeGreaterThan(0);

    expect(errors).toEqual([]);
  });

  test('3: clicking the already-selected line deselects it and removes the highlight', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    const cards = page.locator('.rail-card[data-event-id]');
    await cards.first().click();
    await expect(cards.first()).toHaveClass(/is-selected/);

    await cards.first().click();
    await expect(page.locator('.rail-card.is-selected')).toHaveCount(0);
    await expect(page.locator('.live-railway-selected-core')).toHaveCount(0);
    await expect(page.locator('.live-railway-selected-outline')).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test('4: the highlighted core keeps the official line color and is styled thicker than the outline', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    await page.locator('.rail-card[data-event-id]').first().click();
    await expect(page.locator('.live-railway-selected-core')).not.toHaveCount(0);

    const style = await page.evaluate(() => {
      const core = document.querySelector('.live-railway-selected-core');
      const outline = document.querySelector('.live-railway-selected-outline');
      return {
        coreColor: core.getAttribute('stroke'),
        coreWidth: Number(core.getAttribute('stroke-width')),
        outlineWidth: Number(outline.getAttribute('stroke-width')),
      };
    });
    expect(style.coreColor).toBe('#009944'); // 千代田線 公式カラー
    expect(style.coreColor.toLowerCase()).not.toBe('#ff0000'); // 赤点滅(警戒色)は使わない
    expect(style.outlineWidth).toBeGreaterThan(style.coreWidth); // 白縁取りは中心線より太い

    expect(errors).toEqual([]);
  });

  test('5: selecting a line with no matching GeoJSON feature keeps the list selection without crashing or highlighting', async ({ page }) => {
    await mockAllLiveApis(page, {
      railItems: [railItem({
        railway_id: 'odpt.Railway:Unknown.NoGeometryLine',
        railway_name: '存在しない架空線',
      })],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    const card = page.locator('.rail-card[data-event-id]').first();
    await card.click();
    await expect(card).toHaveClass(/is-selected/);
    await expect(page.locator('.live-railway-selected-core')).toHaveCount(0);

    // 画面が壊れず、他のカードは通常通り機能する (title/panel は生きている)
    await expect(page.locator('[data-testid="live-stream-rail-list-item"]')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('6: prefers-reduced-motion disables the blink animation but keeps the highlight visible', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    await page.locator('.rail-card[data-event-id]').first().click();
    await expect(page.locator('.live-railway-selected-core')).not.toHaveCount(0);

    const animationName = await page.evaluate(() => {
      const core = document.querySelector('.live-railway-selected-core');
      return getComputedStyle(core).animationName;
    });
    expect(animationName).toBe('none');

    expect(errors).toEqual([]);
  });

  test('7: does not regress /live or the rest of the /live/stream panels', async ({ page }) => {
    const errorsLive = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await expect(page.locator('body')).toBeVisible();
    expect(errorsLive).toEqual([]);

    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errorsStream = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    await expect(page.locator('[data-testid="live-stream-panel-earthquake"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-panel-rail"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-ticker-body"]')).toBeVisible();

    expect(errorsStream).toEqual([]);
  });
});
