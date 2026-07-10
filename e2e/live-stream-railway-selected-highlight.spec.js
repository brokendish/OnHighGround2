'use strict';
// Phase 7-A.6: 鉄道情報リストで選択した障害路線を、路線図(鉄道子画面 #rail-map)上で
// 前面表示・太線・縁取り・控えめ点滅により識別できるようにする機能の検証。
//
// Phase 7-A.6追補: YouTube配信の視聴者はリストをクリックできないため、既存の自動巡回/focus
// (詳細ポップアップ・小地図ズームと同じ対象 = focusedRailLine) がデフォルトで選択ハイライトも
// 駆動する (自動追従)。ブラウザで手動クリックした場合は一時的な override として優先され、
// 自動巡回が次の対象へ進んだ時点で override を解除して自動追従へ戻る。

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

// リストは render() のたびに作り直されるため、is-selected の出現を1件だけ待つ
// (auto-follow がデフォルトで有効なため、クリック無しでもいずれか1件が選択されるはず)。
async function waitForAnyRailSelection(page, timeout) {
  await page.waitForFunction(() => document.querySelectorAll('.rail-card.is-selected').length === 1, null, { timeout: timeout || 8000 });
}

const TWO_LINES = [
  railItem({ railway_id: 'odpt.Railway:TokyoMetro.Chiyoda', railway_name: '千代田線' }),
  railItem({ railway_id: 'odpt.Railway:TokyoMetro.Fukutoshin', railway_name: '副都心線', description: '9時38分頃、西船橋駅で発生した安全確認の影響で、遅れが出ています。' }),
];

const THREE_LINES = [
  railItem({ railway_id: 'rail-rot-1', railway_name: '千代田線' }),
  railItem({ railway_id: 'rail-rot-2', railway_name: '副都心線' }),
  railItem({ railway_id: 'rail-rot-3', railway_name: '銀座線' }),
];

test.describe('/live/stream — Phase 7-A.6 鉄道障害路線 選択ハイライト', () => {

  test('1: without any click, the currently auto-focused line is selected and highlighted by default (for viewers who cannot click)', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    await waitForAnyRailSelection(page);
    await expect(page.locator('.live-railway-selected-outline')).not.toHaveCount(0);
    await expect(page.locator('.live-railway-selected-core')).not.toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test('2: the auto-selected highlight rotates through every affected line over time, matching the existing detail-card rotation', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: THREE_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test&focusSpeed=test'));
    await waitForRailMiniMapReady(page);

    const seenSelected = new Set();
    const expected = ['rail-rot-1', 'rail-rot-2', 'rail-rot-3'];
    for (let i = 0; i < 60 && seenSelected.size < 3; i++) {
      await page.waitForTimeout(500);
      const id = await page.evaluate(() => {
        const el = document.querySelector('.rail-card.is-selected');
        return el ? el.dataset.eventId : null;
      });
      if (id) seenSelected.add(id);
    }
    for (const id of expected) expect(seenSelected.has(id)).toBe(true);
    expect(errors).toEqual([]);
  });

  test('3: manually clicking a non-selected line overrides auto-follow and highlights that line instead', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);
    await waitForAnyRailSelection(page);

    const cards = page.locator('.rail-card[data-event-id]');
    const notSelected = page.locator('.rail-card[data-event-id]:not(.is-selected)');
    await expect(notSelected).toHaveCount(1);
    const targetId = await notSelected.getAttribute('data-event-id');

    await notSelected.click();
    await expect(page.locator(`.rail-card[data-event-id="${targetId}"]`)).toHaveClass(/is-selected/);
    await expect(cards).toHaveCount(2);
    await expect(page.locator('.rail-card.is-selected')).toHaveCount(1);

    // 地図側も1本だけがハイライトされている (二重残りしない)
    const coreCount = await page.evaluate(() => document.querySelectorAll('.live-railway-selected-core').length);
    expect(coreCount).toBeGreaterThan(0);

    expect(errors).toEqual([]);
  });

  test('4: clicking the currently-selected line deselects it and removes the highlight', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);
    await waitForAnyRailSelection(page);

    const selected = page.locator('.rail-card.is-selected');
    await selected.click();

    await expect(page.locator('.rail-card.is-selected')).toHaveCount(0);
    await expect(page.locator('.live-railway-selected-core')).toHaveCount(0);
    await expect(page.locator('.live-railway-selected-outline')).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test('5: a manual override is eventually released once the auto-rotation advances to a new target (does not permanently stick)', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: THREE_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test&focusSpeed=test'));
    await waitForRailMiniMapReady(page);
    await waitForAnyRailSelection(page);

    // 現在選択中でない路線を手動選択 (override 開始)
    const notSelected = page.locator('.rail-card[data-event-id]:not(.is-selected)').first();
    const manualId = await notSelected.getAttribute('data-event-id');
    await notSelected.click();
    await expect(page.locator(`.rail-card[data-event-id="${manualId}"]`)).toHaveClass(/is-selected/);

    // 自動巡回が進めば override が解除され、選択がやがて別の路線へ動くはず (固定されたままにならない)。
    let changed = false;
    for (let i = 0; i < 60 && !changed; i++) {
      await page.waitForTimeout(500);
      const id = await page.evaluate(() => {
        const el = document.querySelector('.rail-card.is-selected');
        return el ? el.dataset.eventId : null;
      });
      if (id && id !== manualId) changed = true;
    }
    expect(changed).toBe(true);
    expect(errors).toEqual([]);
  });

  test('6: the highlighted core keeps the official line color and is styled thicker than the outline', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);
    await waitForAnyRailSelection(page);

    // 公式カラーを決定的に検証するため、千代田線カードを明示的に手動選択する
    // (auto-follow が既に選択済みの場合、クリックするとトグルで解除されてしまうため、
    // 未選択のときだけクリックする)。
    const chiyoda = page.locator('[data-testid="live-stream-rail-list-item"]', { hasText: '千代田線' });
    const alreadySelected = (await chiyoda.getAttribute('class') || '').includes('is-selected');
    if (!alreadySelected) await chiyoda.click();
    await expect(chiyoda).toHaveClass(/is-selected/);
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

  test('7: a line with no matching GeoJSON feature is auto-selected (list) without crashing or highlighting', async ({ page }) => {
    await mockAllLiveApis(page, {
      railItems: [railItem({
        railway_id: 'odpt.Railway:Unknown.NoGeometryLine',
        railway_name: '存在しない架空線',
      })],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);

    // 唯一の障害路線なので auto-follow が自動的に選択する (クリック不要)。
    await waitForAnyRailSelection(page);
    await expect(page.locator('.live-railway-selected-core')).toHaveCount(0);

    // 画面が壊れず、他の要素は通常通り機能する。
    await expect(page.locator('[data-testid="live-stream-rail-list-item"]')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('8: prefers-reduced-motion disables the blink animation but keeps the highlight visible', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await mockAllLiveApis(page, { railItems: TWO_LINES });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForRailMiniMapReady(page);
    await waitForAnyRailSelection(page);
    await expect(page.locator('.live-railway-selected-core')).not.toHaveCount(0);

    const animationName = await page.evaluate(() => {
      const core = document.querySelector('.live-railway-selected-core');
      return getComputedStyle(core).animationName;
    });
    expect(animationName).toBe('none');

    expect(errors).toEqual([]);
  });

  test('9: does not regress /live or the rest of the /live/stream panels', async ({ page }) => {
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
