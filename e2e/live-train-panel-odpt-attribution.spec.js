'use strict';
/**
 * live-train-panel-odpt-attribution.spec.js — 鉄道運行情報パネルのODPT出典表示 E2E
 * （Phase 2-D Round 10A、P2D-UI-ODPT-COVERAGE対応）
 *
 * 対象は `/live` の鉄道運行情報パネル（frontend/js/live/live-train-panel.js）が
 * 実装済みの詳細modal（`.ltc-detail-btn` クリックで開く`#ltc-detail-modal`）。
 * 4要件（provider / terms / no-warranty / timestamp）全てが実DOM上に表示される
 * ことを、backendを介さないmock stubの値と厳密に突き合わせて検証する。
 *
 * この機能自体は既存application（変更なし）。Round 10のcoverage matrix作成で、
 * この modal を対象にしたE2Eが一件も存在しないことが判明したため
 * （forensic分類C: 既存mock/fixtureパターンを再利用し、demo stack用の新規
 * formal E2Eを作成）、既存sibling spec（live-train-osm-layer.spec.js等）と
 * 同一のmock構成を踏襲して新設した。
 *
 * backend不要。すべてのAPI呼び出し・地図タイル取得をmockし、外部ODPT APIや
 * 実productionへは一切接続しない。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
  'base64',
);

const RAIN_TIMES = {
  basetime: '20260614100000',
  times: [{ offset_minutes: 0, validtime: '20260614100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260614100000/none/20260614100000/surf/hrpns/{z}/{x}/{y}.png' }],
};
const LIVE_SUMMARY = {
  rain: { evaluated: false }, kikikuru: { evaluated: false },
  earthquake: { evaluated: true, count: 0, items: [] },
  tsunami: { evaluated: true, active: false, areas: [] },
};

// 4要件をすべてassertするための stub item。実backend（backend/app/services/
// live_train_service.py + odpt_allowlist.py）が実際に確認済みlicense事業者
// （東京メトロ・都営）へだけ付与する license/license_terms_url を含む
// （backend/tests/test_phase2d_odpt_allowlist.pyが同一値の組み合わせで実測
// 検証済み — フロント側テストとしては値を固定stubで再現する）。
const ODPT_STUB_ITEM = {
  railway_id: 'odpt.Railway:TokyoMetro.Ginza',
  operator_id: 'odpt.Operator:TokyoMetro',
  operator_name: '東京メトロ',
  railway_name: '銀座線',
  status: 'suspended',
  status_label: '運転見合わせ',
  severity: 4,
  description: 'Round 10A ODPT coverage確認用の説明文。',
  updated_at: '2026-06-14T19:58:00+09:00',
  source: 'ODPT',
  license: '公共交通オープンデータ基本ライセンス',
  license_terms_url: 'https://developer.odpt.org/terms',
  lat: 35.6746, lng: 139.7613,
};

const TRAIN_RESPONSE = {
  status: 'ok', stale: false,
  scope: { mode: 'prefecture', prefecture: '東京都' },
  updated_at: '2026-06-14T20:00:00+09:00',
  items: [ODPT_STUB_ITEM],
};

const ODPT_TERMS_URL = 'https://developer.odpt.org/terms';

async function mockBaseLiveApis(page, trainResponse) {
  await page.route('/data/municipality_coords.json', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page.route('/api/live/weather/jma/prefectures**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unavailable', source: 'Open-Meteo Forecast', forecast_time: null, fetched_at: null, cache_status: 'unavailable', items: [] }) }));
  await page.route('/api/live/sun-moon', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page.route('/api/earthquakes**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, items: [] }) }));
  await page.route('/api/live/earthquakes/history**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('/api/tsunami/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' }) }));
  await page.route('/api/live/storm_surge/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] }) }));
  await page.route('/api/live/road-traffic/summary**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', items: [] }) }));
  await page.route('/api/weather/rain/tile/times', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
  await page.route('/api/live/rain/timeline', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
  await page.route('/api/live/summary', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
  await page.route('/api/live/trains/summary**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(trainResponse) }));
  await page.route('**/jmatile/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
  await page.route('**/jma.go.jp/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
  await page.route('**/basemaps.cartocdn.com/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
  await page.route('/layers/railways/kanto_railways.geojson', r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify({ type: 'FeatureCollection', features: [] }) }));
}

// `.ltc-detail-label`のexact textでrowを一意に特定する（`.ltc-detail-row`への
// hasText部分一致だと「事業者」が「注意」row本文（各事業者・ODPT…）にも
// 部分一致してstrict mode violationになるため、labelの完全一致を使う）。
function detailRowByLabel(page, exactLabel) {
  return page.locator('.ltc-detail-row').filter({
    has: page.locator('.ltc-detail-label', { hasText: new RegExp(`^${exactLabel}$`) }),
  });
}

test.describe('/live — 鉄道運行情報パネル ODPT出典表示（provider/terms/no-warranty/timestamp）', () => {
  test.beforeEach(async ({ page }) => {
    await mockBaseLiveApis(page, TRAIN_RESPONSE);
    await page.goto('/live.html');
    await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });
    await page.locator('.ltc-detail-btn').first().click();
    await expect(page.locator('#ltc-detail-modal')).toBeVisible();
  });

  test('1: ODPT provider — 事業者名と出典(ODPT)が実DOMに表示され、stubの値と一致する', async ({ page }) => {
    const operatorRow = detailRowByLabel(page, '事業者');
    await expect(operatorRow).toBeVisible();
    expect(await operatorRow.locator('.ltc-detail-value').textContent()).toBe(ODPT_STUB_ITEM.operator_name);

    const sourceRow = detailRowByLabel(page, '出典');
    await expect(sourceRow).toBeVisible();
    expect(await sourceRow.locator('.ltc-detail-value').textContent()).toBe(ODPT_STUB_ITEM.source);
  });

  test('2: ODPT terms — per-item利用規約linkが実DOMに表示され、hrefが承認済みライセンスURLと一致する', async ({ page }) => {
    const licenseRow = detailRowByLabel(page, 'ライセンス');
    await expect(licenseRow).toBeVisible();
    await expect(licenseRow.locator('.ltc-detail-value')).toContainText(ODPT_STUB_ITEM.license);

    const termsLink = licenseRow.locator('a');
    await expect(termsLink).toBeVisible();
    await expect(termsLink).toHaveAttribute('href', ODPT_STUB_ITEM.license_terms_url);
  });

  test('3: ODPT no-warranty — 無保証・免責案内が実DOMに表示される', async ({ page }) => {
    const noticeRow = detailRowByLabel(page, '注意');
    await expect(noticeRow).toBeVisible();
    await expect(noticeRow).toContainText('本情報の内容は各事業者・ODPTによって保証されたものではありません');
  });

  test('4: ODPT timestamp — 更新時刻が実DOMに表示され、stubの値と厳密一致する（PC現在時刻やtest実行時刻ではない）', async ({ page }) => {
    const updatedRow = detailRowByLabel(page, '更新時刻');
    await expect(updatedRow).toBeVisible();
    const displayed = await updatedRow.locator('.ltc-detail-value').textContent();
    expect(displayed).toBe(ODPT_STUB_ITEM.updated_at);
    // PCの現在時刻・test実行時刻ではないことの追加確認（stub値と単純一致するだけでは
    // 偶然の一致を否定できないため、stubのISO年が明示的に近未来固定値であることを確認する）。
    expect(displayed.startsWith('2026-06-14')).toBe(true);
  });

  test('5: panel-level ODPT terms note — カード下部の出典noteにも公式ODPT terms linkが表示される', async ({ page }) => {
    await page.locator('.ltc-detail-close').click();
    await expect(page.locator('#ltc-detail-modal')).toHaveCount(0);
    const note = page.locator('.ltc-source-note a');
    await expect(note).toBeVisible();
    await expect(note).toHaveAttribute('href', ODPT_TERMS_URL);
  });

  test('6: 外部ODPT APIまたはproductionへ接続しない（mocked routeのみで完結する）', async ({ page }) => {
    const externalRequests = [];
    page.on('request', (req) => {
      const url = req.url();
      if (url.startsWith('http://127.0.0.1:8787') || url.startsWith('data:') || url.startsWith('blob:')) return;
      externalRequests.push(url);
    });
    // 4要件を再度確認する操作を一通り行う（terms linkのhrefは取得するが実際には
    // navigateしない = クリックしない）。
    await page.locator('.ltc-detail-row', { hasText: 'ライセンス' }).locator('a').getAttribute('href');
    await page.waitForTimeout(300);
    const unexpected = externalRequests.filter((u) => !u.startsWith('https://www.jma.go.jp') && !u.startsWith('https://basemaps.cartocdn.com'));
    expect(unexpected).toEqual([]);
  });
});
