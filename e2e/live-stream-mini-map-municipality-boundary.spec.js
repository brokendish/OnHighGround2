'use strict';
// Phase 8-B / 8-B.1: /live/stream 小画面 (地震・キキクル/豪雨) の市区町村境界線・条件付きラベル表示の検証。
//
// 境界データは全国8地方ブロック単位の GeoJSON (frontend/layers/administrative/municipality_boundaries/)
// に分割されており、小画面の表示範囲 (bbox) と交差するブロックだけを遅延ロード・キャッシュする。
// preferCanvas:true の地図で境界線を Canvas 描画しているため、DOM の <path> 数では検証できない。
// LiveStreamMunicipalityBoundary.getDiagnostics() の instances[key].visibleCount/labelCount と
// loadedBlocks を使う。

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const OBSERVED_AT = '2026-07-03T13:00:00+09:00';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

function streamUrl(query) {
  const sep = query.includes('?') ? '&' : '?';
  return `${DOCKER_BASE}/live/stream${query}${sep}focusSpeed=test&runtimeSpeed=test&demoNow=${DEMO_NOW}`;
}

function eqItem(overrides) {
  return Object.assign({
    event_id: 'eq-boundary-1', lat: 35.65, lng: 139.7, magnitude: 5.5, max_intensity: '5強',
    occurred_at: OBSERVED_AT, epicenter_name: '東京湾',
    points: [
      { pref: '東京都', addr: '千代田区', isArea: false, scale: 50 },
      { pref: '東京都', addr: '新宿区', isArea: false, scale: 45 },
      { pref: '東京都', addr: '渋谷区', isArea: false, scale: 45 },
      { pref: '東京都', addr: '港区', isArea: false, scale: 40 },
      { pref: '東京都', addr: '大田区', isArea: false, scale: 40 },
      { pref: '東京都', addr: '世田谷区', isArea: false, scale: 30 },
    ],
  }, overrides || {});
}

async function mockAllLiveApis(page, { eqItems, rainAreas, kikiAreas } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ items: eqItems != null ? eqItems : [] }),
  }));
  await page.route('**/api/live/summary**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      rain: { status: 'ok', areas: rainAreas != null ? rainAreas : [] },
      kikikuru: { status: 'ok', areas: kikiAreas != null ? kikiAreas : [] },
    }),
  }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
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

async function waitForBoundaryVisible(page, key, timeout) {
  await page.waitForFunction((k) => {
    const d = typeof LiveStreamMunicipalityBoundary !== 'undefined' ? LiveStreamMunicipalityBoundary.getDiagnostics() : null;
    const inst = d && d.instances && d.instances[k];
    return !!(inst && inst.visibleCount > 0);
  }, key, { timeout: timeout || 10000 });
}

test.describe('/live/stream — Phase 8-B/8-B.1/8-B.2 小画面 市区町村境界線・自治体名表示（全国対応・遠方離島補正）', () => {

  test('1: earthquake mini-map draws municipality boundaries and labels the highest-intensity municipalities (bounded count)', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem()] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForBoundaryVisible(page, 'eq-mini');
    await page.waitForFunction(() => document.querySelectorAll('#eq-map .live-muni-label').length > 0, null, { timeout: 8000 });

    const diag = await page.evaluate(() => LiveStreamMunicipalityBoundary.getDiagnostics().instances['eq-mini']);
    expect(diag.visibleCount).toBeGreaterThan(0);
    expect(diag.labelCount).toBeGreaterThan(0);
    expect(diag.labelCount).toBeLessThanOrEqual(6); // 指示書推奨: 地震小画面 4〜8件程度 (上限6で実装)

    const labelTexts = await page.locator('#eq-map .live-muni-label').allTextContents();
    expect(labelTexts.length).toBe(diag.labelCount);
    // 最高震度 (千代田区, 5強) は必ずラベルされる (優先度「震度が高い」)
    expect(labelTexts).toContain('千代田区');

    expect(errors).toEqual([]);
  });

  test('2: kikikuru/rain mini-map draws boundaries and labels the municipality under the current target point', async ({ page }) => {
    await mockAllLiveApis(page, {
      rainAreas: [{ area_name: '横浜市中区周辺', prefecture: '神奈川県', level: 'danger', type: 'rain', lat: 35.4394, lng: 139.6399, observed_at: OBSERVED_AT }],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForBoundaryVisible(page, 'rain-mini');

    const diag = await page.evaluate(() => LiveStreamMunicipalityBoundary.getDiagnostics().instances['rain-mini']);
    expect(diag.visibleCount).toBeGreaterThan(0);

    await page.waitForFunction(() => document.querySelectorAll('#rain-map .live-muni-label').length > 0, null, { timeout: 8000 });
    const labelTexts = await page.locator('#rain-map .live-muni-label').allTextContents();
    expect(labelTexts).toContain('横浜市中区');

    expect(errors).toEqual([]);
  });

  test('3 (Phase 8-B.1): boundaries and reverse-geocoded labels also work far outside Kanto (Osaka earthquake, Fukuoka rain)', async ({ page }) => {
    await mockAllLiveApis(page, {
      eqItems: [eqItem({
        event_id: 'eq-osaka-1', lat: 34.69, lng: 135.5, epicenter_name: '大阪府北部',
        points: [
          { pref: '大阪府', addr: '大阪市北区', isArea: false, scale: 40 },
          { pref: '兵庫県', addr: '尼崎市', isArea: false, scale: 30 },
        ],
      })],
      rainAreas: [{ area_name: '福岡県 筑後', prefecture: '福岡県', level: 'danger', type: 'rain', lat: 33.31, lng: 130.50, observed_at: OBSERVED_AT }],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForBoundaryVisible(page, 'eq-mini');
    await waitForBoundaryVisible(page, 'rain-mini');

    const diag = await page.evaluate(() => LiveStreamMunicipalityBoundary.getDiagnostics());
    expect(diag.instances['eq-mini'].visibleCount).toBeGreaterThan(0);
    expect(diag.instances['rain-mini'].visibleCount).toBeGreaterThan(0);

    // キキクル/豪雨側は逆引きで市区町村名が特定できる (全国どこでも point-in-polygon が動く)
    await page.waitForFunction(() => document.querySelectorAll('#rain-map .live-muni-label').length > 0, null, { timeout: 8000 });
    const rainLabels = await page.locator('#rain-map .live-muni-label').allTextContents();
    expect(rainLabels.length).toBeGreaterThan(0);

    // 東京・神奈川ブロック (kanto) を経由せず、近畿・九州のブロックが読み込まれている
    expect(diag.loadedBlocks).toEqual(expect.arrayContaining(['kinki', 'kyushu_okinawa']));

    await expect(page.locator('[data-testid="live-stream-earthquake-popup"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-rain-popup"]')).toBeVisible();

    expect(errors).toEqual([]);
  });

  test('4 (Phase 8-B.1): does not load all 8 regional blocks for a single Kanto-only event (lazy loading)', async ({ page }) => {
    await mockAllLiveApis(page, { eqItems: [eqItem()] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForBoundaryVisible(page, 'eq-mini');
    await page.waitForTimeout(1500); // moveend/再描画が落ち着くのを待つ

    const diag = await page.evaluate(() => LiveStreamMunicipalityBoundary.getDiagnostics());
    expect(diag.loadedBlocks.length).toBeLessThan(8);
    expect(diag.loadedBlocks).toContain('kanto');

    expect(errors).toEqual([]);
  });

  test('5 (Phase 8-B.2): an earthquake near the Ogasawara Islands still loads the kanto block and shows the boundary/label for 小笠原村', async ({ page }) => {
    // 小笠原村の行政区域は本州から遠く離れているため、kanto ブロックの本土向け bbox からは
    // 素で外れる。BLOCK_EXTRA_BBOXES による個別補正が効いているかを確認する。
    await mockAllLiveApis(page, {
      eqItems: [eqItem({
        event_id: 'eq-ogasawara-1', lat: 27.0, lng: 142.2, epicenter_name: '小笠原諸島西方沖',
        points: [{ pref: '東京都', addr: '小笠原村', isArea: false, scale: 40 }],
      })],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForBoundaryVisible(page, 'eq-mini');
    await page.waitForFunction(() => document.querySelectorAll('#eq-map .live-muni-label').length > 0, null, { timeout: 8000 });

    const diag = await page.evaluate(() => LiveStreamMunicipalityBoundary.getDiagnostics());
    expect(diag.loadedBlocks).toContain('kanto');
    expect(diag.loadedBlocks.length).toBeLessThan(8); // 遠方離島補正があっても全ブロック常時ロードにはならない
    expect(diag.instances['eq-mini'].visibleCount).toBeGreaterThan(0);

    const labelTexts = await page.locator('#eq-map .live-muni-label').allTextContents();
    expect(labelTexts).toContain('小笠原村');

    expect(errors).toEqual([]);
  });

  test('6 (Phase 8-B.2): heavy rain near Miyakojima still loads the kyushu_okinawa block and reverse-geocodes the municipality', async ({ page }) => {
    await mockAllLiveApis(page, {
      rainAreas: [{ area_name: '沖縄県 宮古島地方', prefecture: '沖縄県', level: 'danger', type: 'rain', lat: 24.79, lng: 125.28, observed_at: OBSERVED_AT }],
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await waitForBoundaryVisible(page, 'rain-mini');
    await page.waitForFunction(() => document.querySelectorAll('#rain-map .live-muni-label').length > 0, null, { timeout: 8000 });

    const diag = await page.evaluate(() => LiveStreamMunicipalityBoundary.getDiagnostics());
    expect(diag.loadedBlocks).toContain('kyushu_okinawa');
    expect(diag.instances['rain-mini'].visibleCount).toBeGreaterThan(0);

    const labelTexts = await page.locator('#rain-map .live-muni-label').allTextContents();
    expect(labelTexts).toContain('宮古島市');

    expect(errors).toEqual([]);
  });

  test('7: boundary GeoJSON fetch failure does not break the main earthquake/kikikuru display', async ({ page }) => {
    await page.route('**/layers/administrative/municipality_boundaries/*.geojson', route => route.fulfill({ status: 404, body: 'not found' }));
    await mockAllLiveApis(page, { eqItems: [eqItem()] });
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(3000);

    await expect(page.locator('[data-testid="live-stream-earthquake-popup"]')).toBeVisible();
    const diag = await page.evaluate(() => LiveStreamMunicipalityBoundary.getDiagnostics());
    expect(diag.lastError).toBeTruthy();
    expect(diag.instances['eq-mini'].visibleCount).toBe(0);
    // 404 自体のブラウザ標準ログは許容するが、アプリ側が繰り返し console.error を出し続けないこと
    // (pageerror は捕捉していないので、ここでは主要機能が生きていることのみを確認する)。
    expect(await page.locator('[data-testid="live-stream-panel-earthquake"]').isVisible()).toBe(true);
  });

  test('8: national (full-Japan) overview zoom does not draw boundaries or fetch any block (calm state)', async ({ page }) => {
    // 地震も豪雨も対象なし (calm) の場合、小地図は全国俯瞰 (低ズーム) に留まる。
    await mockAllLiveApis(page, {});
    const errors = await gotoAndCapturePageErrors(page, streamUrl('?state=calm'));
    await page.waitForTimeout(3000);

    const diag = await page.evaluate(() => LiveStreamMunicipalityBoundary.getDiagnostics());
    expect(diag.instances['eq-mini'].visibleCount).toBe(0);
    expect(diag.instances['rain-mini'].visibleCount).toBe(0);
    expect(diag.loadedBlocks.length).toBe(0); // 低ズームでは境界データを一切フェッチしない

    expect(errors).toEqual([]);
  });

  test('9: does not regress /live or the rest of the /live/stream panels', async ({ page }) => {
    const errorsLive = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    await expect(page.locator('body')).toBeVisible();
    expect(errorsLive).toEqual([]);

    await mockAllLiveApis(page, { eqItems: [eqItem()] });
    const errorsStream = await gotoAndCapturePageErrors(page, streamUrl('?state=alert'));
    await page.waitForTimeout(3000);

    await expect(page.locator('[data-testid="live-stream-panel-earthquake"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-panel-rain"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-panel-rail"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-ticker-body"]')).toBeVisible();

    expect(errorsStream).toEqual([]);
  });
});
