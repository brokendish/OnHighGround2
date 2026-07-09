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
    lat: 35.86,
    lng: 139.98,
  }, overrides || {});
}

const LONG_DESC = 'つくばエクスプレス線は、車両点検の影響で、守谷〜つくば駅間の運転を一時見合わせております。振替輸送は関東鉄道常総線・関東鉄道竜ヶ崎線でご利用いただけます。運転再開の見込みは現在のところ立っておらず、詳細が分かり次第公式サイトでお知らせいたします。ご迷惑をおかけしております。';

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
    if (text.includes('Failed to fetch')) return;
    pageErrors.push(text);
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return pageErrors;
}

async function waitForRailFocus(page, id, timeout) {
  await page.waitForFunction(want => document.body.dataset.streamFocusEventId === want, id, { timeout: timeout || 8000 });
}

test.describe('/live/stream — Stream Phase 5-B 鉄道子画面 太線強調・詳細全文・ズーム', () => {

  test('1: a line whose backend name falls back to a raw ODPT id fragment is still resolved to its Japanese name and highlighted', async ({ page }) => {
    // 'odpt.Railway:MIR.TsukubaExpress' は backend の _RAILWAY_NAMES に無いため、
    // backend は railway_name として ID 末尾の英字 'TsukubaExpress' をそのまま返す。
    await mockAllLiveApis(page, {
      railItems: [railItem({
        railway_id: 'odpt.Railway:MIR.TsukubaExpress',
        railway_name: 'TsukubaExpress',
        operator_name: '首都圏新都市鉄道',
        description: LONG_DESC,
      })],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
      return !!(d && d.railwayMiniMap && d.railwayMiniMap.loaded);
    }, null, { timeout: 8000 });

    // カード表示名は英字のフォールバックではなく日本語名になっている
    const nameText = await page.locator('[data-testid="live-stream-rail-line-name"]').first().textContent();
    expect(nameText).toContain('つくばエクスプレス');
    expect(nameText).not.toContain('TsukubaExpress');

    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    expect(diag.affectedCount).toBe(1);
    expect(diag.highlightedCount).toBe(1);
    expect(errors).toEqual([]);
  });

  test('2: an affected line zooms the mini map in (via local 8s rotation, not just when globally focused), and clearing the line zooms back out', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-zoom-1' })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
      return !!(d && d.railwayMiniMap && d.railwayMiniMap.loaded);
    }, null, { timeout: 8000 });

    // Stream Phase 6-D: 鉄道子画面は地震/豪雨と同じく「グローバル自動巡回が来ていなくても、
    // 自身の8秒巡回(ローカルfallback)で対象を表示・ズームする」。1件しかない場合は
    // 巡回インデックスが常に0を指すため、グローバルfocusを待たずズームインされる。
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap;
      return d && d.zoomedEventId === 'rail-zoom-1';
    }, null, { timeout: 8000 });
    await page.waitForTimeout(1200); // focusOn アニメーションの収束を待つ
    const zoomedIn = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    expect(zoomedIn.zoomedEventId).toBe('rail-zoom-1');
    expect(zoomedIn.zoom).toBeGreaterThan(10.5);

    // 対象路線が無くなれば (影響路線ゼロへ切り替われば)、既定の首都圏表示へ戻る。
    await page.unroute('**/api/live/trains/summary**');
    await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap;
      return d && d.zoomedEventId === null;
    }, null, { timeout: 8000 });
    await page.waitForTimeout(1200); // fitTo アニメーションの収束を待つ
    const zoomedOut = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    expect(zoomedOut.zoomedEventId).toBeNull();
    expect(zoomedOut.zoom).toBeLessThan(10.5); // focusOn(..., 12) より広角(=既定の首都圏表示)に戻っている
  });

  test('3: full description text is shown in the scrollable list below the card list, not truncated', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-full-1', description: LONG_DESC })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailFocus(page, 'rail-full-1');
    await expect(page.locator('[data-testid="live-stream-railway-detail-panel"]')).toBeVisible();
    const bodyText = await page.locator('[data-testid="live-stream-railway-detail-body"]').first().textContent();
    expect(bodyText).toContain('守谷〜つくば駅間');
    expect(bodyText).toContain('ご迷惑をおかけしております。'); // 末尾まで欠けていない
    expect(bodyText).toContain('出典'); // 出典表記も全文側に含まれる
  });

  test('4: the floating popup on the mini map only shows a short summary (no full body text)', async ({ page }) => {
    await mockAllLiveApis(page, { railItems: [railItem({ railway_id: 'rail-short-popup', description: LONG_DESC })] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForRailFocus(page, 'rail-short-popup');
    const popupText = await page.locator('[data-testid="live-stream-railway-detail"]').textContent();
    expect(popupText).not.toContain('守谷〜つくば駅間');
  });

  test('6: a line with no representative coordinates at all is still highlighted and shown via the mini map\'s own local rotation (no generic fallback point, no central-map focus)', async ({ page }) => {
    // 事業者代表点 (_operator_representative_latlng) が取得できない場合を再現する
    // (lat/lng を持たない API レスポンス)。
    // Phase 7-A.5 (全国ODPT対応): 「代表点が無ければ東京駅等へ安易に寄せない」という要件のため、
    // 座標の無い路線はもう中央地図のイベント化・グローバル自動巡回の focus 対象にはならない
    // (東京駅への汎用フォールバックは廃止)。ただし鉄道小画面は rail.affected を直接参照する
    // 別経路 (自身の8秒巡回) のため、太線強調・詳細カード・小地図のズーム対象には引き続きなれる。
    await mockAllLiveApis(page, {
      railItems: [railItem({ railway_id: 'rail-nocoord-1', railway_name: '京王線', lat: undefined, lng: undefined })],
    });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    // グローバル中央地図の focus (document.body.dataset.streamFocusEventId) はもう発火しない
    // ため待たない。小地図自身の local rotation (1件しかないので即座に index 0 を指す) を待つ。
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap;
      return d && d.zoomedEventId === 'rail-nocoord-1';
    }, null, { timeout: 8000 });

    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    expect(diag.highlightedCount).toBe(1);
    expect(diag.zoomedEventId).toBe('rail-nocoord-1');

    await expect(page.locator('[data-testid="live-stream-railway-detail-panel"]')).toBeVisible();
    const bodyText = await page.locator('[data-testid="live-stream-railway-detail-body"]').first().textContent();
    expect(bodyText).toContain('人身事故');

    // 中央地図・自動巡回の focus 対象にはならないことを確認する (東京駅固定フォールバック回帰防止)。
    const focusEventId = await page.evaluate(() => document.body.dataset.streamFocusEventId || null);
    expect(focusEventId).not.toBe('rail-nocoord-1');
  });

  test('7: /live is unaffected by the railway phase 5-B changes', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
  });

  test('8 (Stream Phase 6-D): every line in a multi-line list eventually gets the detail popup (text card rotation is unaffected by the map bounds change)', async ({ page }) => {
    await mockAllLiveApis(page, {
      railItems: [
        railItem({ railway_id: 'rail-multi-1', railway_name: '中央線快速' }),
        railItem({ railway_id: 'rail-multi-2', railway_name: '山手線' }),
        railItem({ railway_id: 'rail-multi-3', railway_name: '銀座線' }),
        railItem({ railway_id: 'rail-multi-4', railway_name: '丸ノ内線' }),
      ],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&focusSpeed=test&runtimeSpeed=test'));

    const seenDetailIds = new Set();
    const expected = ['rail-multi-1', 'rail-multi-2', 'rail-multi-3', 'rail-multi-4'];
    for (let i = 0; i < 90 && seenDetailIds.size < 4; i++) {
      await page.waitForTimeout(500);
      const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
      if (diag.railwayDetail && diag.railwayDetail.activeRailwayEventId) seenDetailIds.add(diag.railwayDetail.activeRailwayEventId);
    }
    for (const id of expected) {
      expect(seenDetailIds.has(id)).toBe(true);
    }
    expect(errors).toEqual([]);
  });

  test('9 (Stream Phase 6-H): multiple simultaneously affected lines are all fit into the mini-map bounds at once, not zoomed to a single shared representative point', async ({ page }) => {
    // 京王線 (西部) と 東武東上線 (北西部/川越方面) は実際には大きく離れた別路線だが、
    // 事業者代表点は意図的に同一座標にモックしてある (以前のバグ: 代表点方式だと必ずこの
    // 1点にしか寄れず、他方の路線は画面外になっていた)。
    await mockAllLiveApis(page, {
      railItems: [
        railItem({ railway_id: 'rail-bounds-keio', railway_name: '京王線', operator_name: '京王電鉄', lat: 35.69, lng: 139.692 }),
        railItem({ railway_id: 'rail-bounds-tobu', railway_name: '東武東上線', operator_name: '東武鉄道', lat: 35.69, lng: 139.692 }),
      ],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForFunction(() => {
      const d = window.__LiveStreamDiagnostics && window.__LiveStreamDiagnostics.getSnapshot();
      return !!(d && d.railwayMiniMap && d.railwayMiniMap.fittedLineIds && d.railwayMiniMap.fittedLineIds.length === 2);
    }, null, { timeout: 15000 });

    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap);
    // 両路線が同時に fit 対象に含まれている (どちらか1件だけを巡回して見せているのではない)。
    expect(diag.fittedLineIds.sort()).toEqual(['rail-bounds-keio', 'rail-bounds-tobu']);
    // 代表点1点への固定ズーム (旧仕様は zoom=12 固定) より広角になっている = 両路線の実際の
    // 広がりを反映した bounds になっている証拠。
    expect(diag.zoom).toBeLessThan(11);
    expect(errors).toEqual([]);
  });
});
