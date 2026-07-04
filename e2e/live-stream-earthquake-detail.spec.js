'use strict';

const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う (他 live-stream 系 spec と同じ規約)
const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
// 実データ (points/occurred_at) が 12h フィルタ内に収まるよう、時計を OBSERVED_AT の近傍へ固定する
// (他 live-stream 系 spec と同じ規約。付けないと実際の壁時計との差で 12h ウィンドウ外に落ちて eqOn=false になる)。
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

// focusSpeed=test / runtimeSpeed=test でタイマー/timeoutを短縮し、E2Eを高速化する
// (通常運用のデフォルトの間隔・上限 [8s-60s hold, 4s/frame tour] 自体は変えない)。
function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${DOCKER_BASE}/live/stream${query}${sep}focusSpeed=test&runtimeSpeed=test&demoNow=${DEMO_NOW}`;
}

function eqItem(id, lat, lng, magnitude, intensity, points) {
  return {
    event_id: id, lat, lng, magnitude, max_intensity: intensity,
    occurred_at: OBSERVED_AT, epicenter_name: `震源${id}`,
    points: points || [],
  };
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
  page.on('pageerror', e => {
    const text = e.message || String(e);
    // protomaps-leaflet の PMTiles range-request が goto の二重ナビゲーションで
    // abort されることによる無害な fetch エラーはノイズとして除外する (既存specと同じ方針)。
    if (text.includes('Failed to fetch')) return;
    pageErrors.push(text);
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return pageErrors;
}

// 東北広域: 5県にまたがる14市区町村 (小地図 tour + リスト自動スクロールの両方を誘発する件数)。
// 末尾1件は座標辞書に存在しない地名 (missingCoordinateCount 検証用)。
const WIDE_AREA_POINTS = [
  { pref: '岩手県', addr: '盛岡市',     isArea: false, scale: 45 },
  { pref: '岩手県', addr: '宮古市',     isArea: false, scale: 45 },
  { pref: '岩手県', addr: '大船渡市',   isArea: false, scale: 40 },
  { pref: '岩手県', addr: '花巻市',     isArea: false, scale: 40 },
  { pref: '岩手県', addr: '北上市',     isArea: false, scale: 30 },
  { pref: '岩手県', addr: '久慈市',     isArea: false, scale: 30 },
  { pref: '宮城県', addr: '石巻市',     isArea: false, scale: 40 },
  { pref: '宮城県', addr: '仙台青葉区', isArea: false, scale: 30 },
  { pref: '青森県', addr: '八戸市',     isArea: false, scale: 30 },
  { pref: '青森県', addr: '十和田市',   isArea: false, scale: 20 },
  { pref: '秋田県', addr: '秋田市',     isArea: false, scale: 20 },
  { pref: '福島県', addr: '福島市',     isArea: false, scale: 20 },
  { pref: '福島県', addr: 'いわき市',   isArea: false, scale: 10 },
  { pref: '架空県', addr: '架空町',     isArea: false, scale: 30 },
];

// 局所的: 単一県内の少数市区町村 (自動スクロール/tour 不要な件数)
const SMALL_POINTS = [
  { pref: '宮城県', addr: '石巻市',     isArea: false, scale: 20 },
  { pref: '宮城県', addr: '仙台若林区', isArea: false, scale: 20 },
];

async function waitForEqMuniReady(page, timeout) {
  await page.waitForFunction(() => {
    const el = document.getElementById('eq-muni');
    return el && !el.hidden && el.dataset.eqMuniScrollMode && el.dataset.eqMuniScrollMode !== 'unavailable';
  }, null, { timeout: timeout || 8000 });
}

test.describe('/live/stream — Stream Phase 5-A.1 地震子画面 市区町村震度詳細', () => {

  test('1: municipal intensity list appears below the main hypocenter card when points exist', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-1', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    await expect(page.locator('[data-testid="live-stream-earthquake-popup"]')).toBeVisible();
    const panel = page.locator('[data-testid="live-stream-earthquake-municipal-panel"]');
    await expect(panel).toBeVisible();
    expect(await panel.getAttribute('data-eq-muni-count')).toBe('14');
    expect(await page.locator('[data-testid="live-stream-earthquake-municipal-row"]').count()).toBeGreaterThan(0);
    expect(errors).toEqual([]);
  });

  test('2: municipal rows are sorted by intensity descending', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-2', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const ranks = { '7': 70, '6強': 65, '6弱': 60, '5強': 55, '5弱': 50, '4': 40, '3': 30, '2': 20, '1': 10, '不明': 0 };
    const intensities = await page.locator('[data-testid="live-stream-earthquake-municipal-row"]').evaluateAll(
      els => els.map(el => el.dataset.intensity)
    );
    // scrolling mode duplicates the row list once for the seamless marquee loop; only check the first half.
    const half = intensities.slice(0, intensities.length / 2 || intensities.length);
    const rankValues = half.map(v => ranks[v] ?? 0);
    const sorted = [...rankValues].sort((a, b) => b - a);
    expect(rankValues).toEqual(sorted);
  });

  test('3: municipalities with coordinates become mini-map markers', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-3', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const markers = page.locator('#eq-map [data-testid="live-stream-earthquake-municipal-marker"]');
    expect(await markers.count()).toBeGreaterThan(0);
  });

  test('4: municipalities without coordinates stay in the list but are never markers', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-4', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const panel = page.locator('[data-testid="live-stream-earthquake-municipal-panel"]');
    expect(await panel.getAttribute('data-eq-muni-missing-count')).toBe('1');
    const unresolvedRow = page.locator('[data-testid="live-stream-earthquake-municipal-row"][data-city="架空町"]');
    expect(await unresolvedRow.count()).toBeGreaterThan(0);
    await expect(unresolvedRow.first()).toHaveAttribute('data-has-coordinate', 'false');
    const markerForUnresolved = page.locator('[data-testid="live-stream-earthquake-municipal-marker"][data-city="架空町"]');
    expect(await markerForUnresolved.count()).toBe(0);
  });

  test('5: many municipalities trigger automatic list scrolling', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-5', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const panel = page.locator('[data-testid="live-stream-earthquake-municipal-panel"]');
    expect(await panel.getAttribute('data-eq-muni-scroll-mode')).toBe('scrolling');
  });

  test('5b: few municipalities stay static (no scrolling)', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-small-5b', 38.4, 142.0, 4.2, '2', SMALL_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const panel = page.locator('[data-testid="live-stream-earthquake-municipal-panel"]');
    expect(await panel.getAttribute('data-eq-muni-scroll-mode')).toBe('static');
    const eqMap = page.locator('#eq-map');
    expect(await eqMap.getAttribute('data-eq-mini-map-mode')).toBe('fit');
  });

  test('6: the earthquake target does not switch away while the list is still scrolling (hold active)', async ({ page }) => {
    // 2件の地震のうち、広域(スクロール要)の対象が先に来るよう occurred_at を新しくする。
    await mockAllLiveApis(page, {
      eqItems: [
        eqItem('eq-wide-6', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS),
        eqItem('eq-small-6', 38.4, 142.0, 4.2, '2', SMALL_POINTS),
      ],
    });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const idBefore = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');
    expect(await page.evaluate(() => document.body.dataset.streamPanelHold)).toBe('earthquake-detail');

    await page.waitForTimeout(9000); // > 8s ローカル巡回境界をまたぐ
    const idAfter = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');
    expect(idAfter).toBe(idBefore);
  });

  test('7: a wide-area earthquake tours the mini-map across multiple frames', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-7', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const eqMap = page.locator('#eq-map');
    expect(await eqMap.getAttribute('data-eq-mini-map-mode')).toBe('tour');
    const total = Number(await eqMap.getAttribute('data-eq-mini-map-frame-total'));
    expect(total).toBeGreaterThan(1);
  });

  test('8: the mini-map frame advances but the earthquake target still does not switch until the tour finishes', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-8', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForEqMuniReady(page);

    const eqMap = page.locator('#eq-map');
    const idBefore = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');
    const frame1 = Number(await eqMap.getAttribute('data-eq-mini-map-frame-index'));

    await page.waitForTimeout(4500); // > frameIntervalMs(4s) 一回分
    const frame2 = Number(await eqMap.getAttribute('data-eq-mini-map-frame-index'));
    const idAfter = await page.locator('[data-testid="live-stream-earthquake-popup"]').getAttribute('data-event-id');

    expect(frame2).toBeGreaterThan(frame1);
    expect(idAfter).toBe(idBefore);
  });

  test('9: P2P/epicenter fetch failure does not crash the screen', async ({ page }) => {
    await mockAllLiveApis500(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(1500);

    await expect(page.locator('[data-testid="live-stream-earthquake-status"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-earthquake-municipal-panel"]')).toBeHidden();
    expect(errors).toEqual([]);
  });

  test('10: stale municipal markers/list do not linger once the earthquake disappears', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-10', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForEqMuniReady(page);
    expect(await page.locator('[data-testid="live-stream-earthquake-municipal-marker"]').count()).toBeGreaterThan(0);

    // 次の fetch で 0件に切り替わる (12h ウィンドウ外に出た想定)
    await mockAllLiveApis(page, { eqItems: [] });
    await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
    await page.waitForFunction(() => document.getElementById('eq-muni').hidden === true, null, { timeout: 5000 });

    expect(await page.locator('[data-testid="live-stream-earthquake-municipal-marker"]').count()).toBe(0);
    expect(await page.locator('[data-testid="live-stream-earthquake-municipal-row"]').count()).toBe(0);
  });

  test('11: demo=1 goes through the same detail pipeline (not a separate fallback)', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?demo=1&focus=off'));
    await waitForEqMuniReady(page);

    const diag = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot().earthquakeDetail);
    expect(diag).toBeTruthy();
    expect(diag.municipalCount).toBeGreaterThan(0);
    expect(errors).toEqual([]);
  });

  test('12: state=calm shows no municipal detail or markers', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-12', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=calm'));
    await page.waitForTimeout(1000);

    await expect(page.locator('[data-testid="live-stream-earthquake-municipal-panel"]')).toBeHidden();
    expect(await page.locator('[data-testid="live-stream-earthquake-municipal-marker"]').count()).toBe(0);
    expect(errors).toEqual([]);
  });

  test('13: Phase 5-A stability — repeated refresh does not accumulate municipal marker/row DOM', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem('eq-wide-13', 39.2, 142.1, 6.1, '5弱', WIDE_AREA_POINTS)] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert&runtimeSpeed=test'));
    await waitForEqMuniReady(page);

    const before = await page.locator('[data-testid="live-stream-earthquake-municipal-marker"]').count();
    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    const after = await page.locator('[data-testid="live-stream-earthquake-municipal-marker"]').count();
    expect(after).toBe(before);
    expect(errors).toEqual([]);
  });

  test('14: normal /live has no side effects from the earthquake detail feature', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await page.waitForTimeout(1500);
    expect(await page.locator('#eq-muni').count()).toBe(0);
    expect(await page.locator('[data-testid="live-stream-earthquake-municipal-panel"]').count()).toBe(0);
    expect(errors).toEqual([]);
  });
});
