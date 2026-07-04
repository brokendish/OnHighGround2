'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const DEMO_1942 = '2026-06-30T19:42:00%2B09:00';
const DEMO_0600 = '2026-06-30T06:00:00%2B09:00';
const DEMO_1800 = '2026-06-30T18:00:00%2B09:00';

function streamUrl(query) {
  return `${DOCKER_BASE}/live/stream${query}`;
}

async function gotoAndCaptureErrors(page, url) {
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', msg => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    const sourceUrl = (msg.location() && msg.location().url) || '';
    // Stream Phase 4-C: 鉄道路線レイヤー (protomaps-leaflet) が PMTiles を fetch() の Range
    // リクエストで読む。同一 page で連続 goto するテスト (このファイル特有) では、前の遷移が
    // 開始した PMTiles fetch がナビゲーションで中断され "Failed to fetch" が無害に出ることがある
    // (実際の不具合ではない)。ブラウザの報告形式により、フルスタック付きのこともあれば
    // "TypeError: Failed to fetch" のみのこともあるため、発生元URL (protomaps-leaflet) も併せて見る。
    // 他の live-stream 系 spec と同様、既知の無害なネットワーク由来ノイズのみをフィルタする。
    const isPmtilesFetchAbort = text.includes('Failed to fetch')
      && (text.includes('protomaps-leaflet') || sourceUrl.includes('protomaps-leaflet'));
    if (isPmtilesFetchAbort) return;
    consoleErrors.push(text);
  });
  page.on('pageerror', error => {
    pageErrors.push(error.message || String(error));
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return { consoleErrors, pageErrors };
}

async function expectNoBrowserErrors(errors) {
  expect(errors.pageErrors, 'page errors').toEqual([]);
  expect(errors.consoleErrors, 'console errors').toEqual([]);
}

async function expectCoreStreamLayout(page) {
  for (const testId of [
    'live-stream-stage',
    'live-stream-header',
    'live-stream-clock',
    'live-stream-date',
    'live-stream-status-bar',
    'live-stream-center',
    'live-stream-center-map',
    'live-stream-center-time',
    'live-stream-alert-level',
    'live-stream-panel-earthquake',
    'live-stream-panel-rain',
    'live-stream-panel-rail',
    'live-stream-panel-tide',
    'live-stream-ticker',
    'live-stream-ticker-body',
  ]) {
    await expect(page.getByTestId(testId), testId).toBeVisible();
  }
}

test.describe('/live/stream — Phase Stream-2-A', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('calm view shows the full broadcast layout and no active target', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=calm&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expectCoreStreamLayout(page);
    await expect(page.getByText('現在、表示対象なし')).toBeVisible();
    await expect(page.getByText('現在 対象なし').first()).toBeVisible();
    await expect(page.getByTestId('live-stream-rail-list').getByText('平常運転')).toBeVisible();
    await expect(page.getByTestId('live-stream-dev-chrome')).toBeHidden();
    await expectNoBrowserErrors(errors);
  });

  // demo=1 を付与することで実データ取得をスキップし、デモシーン固定で E2E を安定化する
  test('alert view shows category panels and center pulses', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expectCoreStreamLayout(page);
    await expect(page.getByTestId('live-stream-earthquake-list').getByText('岩手県沖')).toBeVisible();
    await expect(page.getByTestId('live-stream-rain-list').getByText('静岡県 中部')).toBeVisible();
    await expect(page.getByTestId('live-stream-rail-list').getByText('中央線快速')).toBeVisible();
    await expect(page.getByTestId('live-stream-tide-station-list').getByText('東京')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-earthquake')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-rain')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-rail')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-tide').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('demoNow freezes header and center clocks', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-clock')).toHaveText('19:42:00');
    await expect(page.getByTestId('live-stream-center-time').locator('#clock-short')).toHaveText('19:42');
    const before = await page.getByTestId('live-stream-clock').textContent();
    await page.waitForTimeout(2100);
    await expect(page.getByTestId('live-stream-clock')).toHaveText(before);
    await expectNoBrowserErrors(errors);
  });

  test('clock updates when demoNow is absent', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(page, streamUrl('?state=alert&demo=1&chrome=off'));

    await expect(page.getByTestId('live-stream-clock')).toHaveText(/\d{2}:\d{2}:\d{2}/);
    const before = await page.getByTestId('live-stream-clock').textContent();
    await page.waitForTimeout(2100);
    const after = await page.getByTestId('live-stream-clock').textContent();
    expect(after).not.toBe(before);
    await expectNoBrowserErrors(errors);
  });

  test('tide current marker is always at chart center (centered view)', async ({ page }) => {
    // 中央固定ビュー: demoNow に関わらず現在時刻マーカーは常に中央 (cx≈183)
    let errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_0600}`),
    );
    const marker0600 = page.getByTestId('live-stream-tide-current-marker').first();
    await expect(marker0600).toBeVisible();
    const cx0600 = parseFloat(await marker0600.getAttribute('cx'));
    // x0=30, x1=336 → center = (30+336)/2 = 183
    expect(cx0600).toBeCloseTo(183, 0);
    await expectNoBrowserErrors(errors);

    errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1800}`),
    );
    const marker1800 = page.getByTestId('live-stream-tide-current-marker').first();
    await expect(marker1800).toBeVisible();
    const cx1800 = parseFloat(await marker1800.getAttribute('cx'));
    expect(cx1800).toBeCloseTo(183, 0);
    await expectNoBrowserErrors(errors);
  });

  test('chrome=off hides development controls only', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-dev-chrome')).toBeHidden();
    await expectCoreStreamLayout(page);
    await expectNoBrowserErrors(errors);
  });

  test('/live regression has no stream CSS/DOM leakage', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/live`);

    await expect(page).toHaveTitle(/全国災害ビューア/);
    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    await expect(page.locator('link[href="/css/live/live-stream.css"]')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });

  test('/ regression has no stream CSS/DOM leakage', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/`);

    await expect(page).toHaveTitle(/OnHighGround/);
    await expect(page.locator('#map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    await expect(page.locator('link[href="/css/live/live-stream.css"]')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });
});

test.describe('/live/stream — Phase Stream-2-B.2 rain adapter', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('demo=1 alert view shows rain demo data', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expectCoreStreamLayout(page);
    // デモシーンの雨データが表示される
    await expect(page.getByTestId('live-stream-rain-list').getByText('静岡県 中部')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-rain')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('calm state shows no rain pulse on center map', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=calm&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-pulse-rain')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });

  test('rain status testid is visible in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-rain-status')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('rain list items have testid in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    // SCENES.alert.rain.alerts に 5 件あるので list-item が存在する
    await expect(page.getByTestId('live-stream-rain-list-item').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('rain popup shows active target in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-rain-popup')).toBeVisible();
    await expect(page.getByTestId('live-stream-rain-active')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('rain header count is non-zero in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    // デモ: alerts 5件
    const ctRain = page.locator('#ct-rain');
    await expect(ctRain).not.toHaveText('0');
    await expect(ctRain).not.toHaveText('-');
    await expectNoBrowserErrors(errors);
  });
});

test.describe('/live/stream — Phase Stream-2-B.4 railway adapter', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('demo=1 alert view shows rail demo data', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expectCoreStreamLayout(page);
    // デモシーンの鉄道カード (SCENES.alert.rail.affected) が表示される
    await expect(page.getByTestId('live-stream-rail-list').getByText('中央線快速')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-rail')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('calm state shows no rail affected lines', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=calm&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-rail-empty')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-rail')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });

  test('rail list items have testid in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    // SCENES.alert.rail.affected に 4 件あるので list-item が存在する
    await expect(page.getByTestId('live-stream-rail-list-item').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('rail line name and status testids exist in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-rail-line-name').first()).toBeVisible();
    await expect(page.getByTestId('live-stream-rail-status').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('rail header count is non-zero in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    const ctRail = page.locator('#ct-rail');
    await expect(ctRail).not.toHaveText('0');
    await expect(ctRail).not.toHaveText('-');
    await expectNoBrowserErrors(errors);
  });

  test('rail section testid exists in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-rail-section').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });
});

test.describe('/live/stream — Phase Stream-2-B.3 tide adapter', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('demo=1 alert view shows tide demo data', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expectCoreStreamLayout(page);
    // デモシーンの潮位データ (TIDE_POOL: 東京, 横浜, …) が表示される
    await expect(page.getByTestId('live-stream-tide-station-list').getByText('東京')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-tide').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('calm state shows tide stations without alerts', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=calm&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    // calm でも TIDE_POOL の拠点が表示される (alert はなし)
    await expect(page.getByTestId('live-stream-panel-tide')).toBeVisible();
    await expect(page.getByTestId('live-stream-tide-station-list')).toBeVisible();
    // calm: 潮位パルスなし
    await expect(page.getByTestId('live-stream-pulse-tide')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });

  test('tide status testid is visible in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-tide-status')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('tide station testid exists in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-tide-station').first()).toBeVisible();
    await expect(page.getByTestId('live-stream-tide-station-name').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('tide high/low testids exist in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-tide-high').first()).toBeVisible();
    await expect(page.getByTestId('live-stream-tide-low').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('tide curve testid exists in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    // 正弦波デモ曲線 (renderTide) にも data-testid="live-stream-tide-curve" がある
    await expect(page.getByTestId('live-stream-tide-curve').first()).toBeAttached();
    await expect(page.getByTestId('live-stream-tide-current').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });
});

test.describe('/live/stream — Phase Stream-2-D production cleanup', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  // --- 1. 開発UIはデフォルト非表示 ---
  test('dev controls hidden without devControls=1', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&demoNow=${DEMO_1942}`),
    );
    await expect(page.getByTestId('live-stream-dev-chrome')).toBeHidden();
    await expectNoBrowserErrors(errors);
  });

  test('dev controls visible with devControls=1', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&devControls=1&demoNow=${DEMO_1942}`),
    );
    await expect(page.getByTestId('live-stream-dev-chrome')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  // --- 2. state 未指定のデフォルトは alert (デモサイクル廃止確認) ---
  test('no state param: default is alert display (data-lv=high)', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );
    await expect(page.getByTestId('live-stream-alert-level')).toHaveAttribute('data-lv', 'high');
    await expectNoBrowserErrors(errors);
  });

  // --- 3. 潮位グラフ: 中央固定ビュー確認 ---
  test('tide current marker is at chart center in centered view', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );
    const marker = page.getByTestId('live-stream-tide-current-marker').first();
    await expect(marker).toBeVisible();
    const cx = parseFloat(await marker.getAttribute('cx'));
    // 現在時刻縦線は常に中央: x0=30, x1=336 → center=(30+336)/2=183
    expect(cx).toBeCloseTo(183, 0);
    await expectNoBrowserErrors(errors);
  });

  test('tide marker stays at center at any demoNow (06:00 and 18:00)', async ({ page }) => {
    let errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_0600}`),
    );
    const cx0600 = parseFloat(
      await page.getByTestId('live-stream-tide-current-marker').first().getAttribute('cx'),
    );
    await expectNoBrowserErrors(errors);

    errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1800}`),
    );
    const cx1800 = parseFloat(
      await page.getByTestId('live-stream-tide-current-marker').first().getAttribute('cx'),
    );

    // 両時刻とも中央 (≈183) に固定されていること
    expect(cx0600).toBeCloseTo(183, 0);
    expect(cx1800).toBeCloseTo(183, 0);
    await expectNoBrowserErrors(errors);
  });

  test('tide curve content differs between 06:00 and 18:00 (windowed view)', async ({ page }) => {
    let errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_0600}`),
    );
    await expectNoBrowserErrors(errors);
    const curve0600 = await page.getByTestId('live-stream-tide-curve').first().getAttribute('d');

    errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1800}`),
    );
    await expectNoBrowserErrors(errors);
    const curve1800 = await page.getByTestId('live-stream-tide-curve').first().getAttribute('d');

    // 中央固定でも表示ウィンドウが異なるため曲線の形は変わる (過去・未来の潮位位相差)
    expect(curve1800).not.toBe(curve0600);
  });
});

test.describe('/live/stream — Phase Stream-2-C ticker', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  const TICKER_BODY = 'live-stream-ticker-body';

  test('demo=1 alert: ticker contains earthquake label', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );
    const text = await page.getByTestId(TICKER_BODY).textContent();
    expect(text).toContain('【地震】');
    await expectNoBrowserErrors(errors);
  });

  test('demo=1 alert: ticker contains rain label', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );
    const text = await page.getByTestId(TICKER_BODY).textContent();
    expect(text).toContain('【大雨】');
    await expectNoBrowserErrors(errors);
  });

  test('demo=1 alert: ticker contains rail label', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );
    const text = await page.getByTestId(TICKER_BODY).textContent();
    expect(text).toContain('【鉄道】');
    await expectNoBrowserErrors(errors);
  });

  test('demo=1 alert: ticker contains tide label', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );
    const text = await page.getByTestId(TICKER_BODY).textContent();
    expect(text).toContain('【潮位】');
    await expectNoBrowserErrors(errors);
  });

  test('demo=1 alert: ticker has no undefined/null/NaN/[object', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );
    const text = await page.getByTestId(TICKER_BODY).textContent();
    expect(text).not.toContain('undefined');
    expect(text).not.toContain('null');
    expect(text).not.toContain('NaN');
    expect(text).not.toContain('[object');
    await expectNoBrowserErrors(errors);
  });

  test('state=calm: ticker shows monitoring text', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=calm&chrome=off&demoNow=${DEMO_1942}`),
    );
    const text = await page.getByTestId(TICKER_BODY).textContent();
    expect(text).toContain('監視中');
    await expectNoBrowserErrors(errors);
  });

  test('demo=1 alert: earthquake appears before rain in ticker (priority order)', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );
    const text = await page.getByTestId(TICKER_BODY).textContent();
    expect(text.indexOf('【地震】')).toBeLessThan(text.indexOf('【大雨】'));
    await expectNoBrowserErrors(errors);
  });
});

test.describe('/live/stream — Phase Stream-2-B.1 earthquake adapter', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('demo=1 alert view shows stable earthquake demo data', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expectCoreStreamLayout(page);
    // デモシーンの地震データが表示される
    await expect(page.getByTestId('live-stream-earthquake-list').getByText('岩手県沖')).toBeVisible();
    await expect(page.getByTestId('live-stream-pulse-earthquake')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('calm state suppresses earthquake display regardless of demo flag', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=calm&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByText('現在 対象なし').first()).toBeVisible();
    // calm 時: ct-eq は 0 (デモ履歴はあるが targets がない)
    await expect(page.locator('#ct-eq')).toHaveText('0');
    await expectNoBrowserErrors(errors);
  });

  test('earthquake status testid is visible in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-earthquake-status')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('earthquake history items have testid in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    // HISTORY_12H に 6 件あるので history-item が存在する
    await expect(page.getByTestId('live-stream-earthquake-history-item').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('earthquake popup shows active target in alert demo mode', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-earthquake-popup')).toBeVisible();
    await expect(page.getByTestId('live-stream-earthquake-active')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('calm state shows no earthquake pulse on center map', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=calm&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    await expect(page.getByTestId('live-stream-pulse-earthquake')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });
});
