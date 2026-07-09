'use strict';
/**
 * live-train-layer.spec.js — /live 鉄道運行影響レイヤー MVP 確認
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const EQ_RESPONSE = { count: 0, items: [] };
const TSUNAMI_RESPONSE = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const STORM_SURGE_NONE = { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] };
const LIVE_SUMMARY = {
    rain: { evaluated: false },
    kikikuru: { evaluated: false },
    earthquake: { evaluated: true, count: 0, items: [] },
    tsunami: { evaluated: true, active: false, areas: [] },
};
const RAIN_TIMES = {
    basetime: '20260614100000',
    times: [
        { offset_minutes: 0, validtime: '20260614100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260614100000/none/20260614100000/surf/hrpns/{z}/{x}/{y}.png' },
    ],
};

const DISRUPTION_RESPONSE = {
    status: 'ok',
    stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-14T20:00:00+09:00',
    items: [
        {
            railway_id: 'odpt.Railway:Keio.Keio',
            operator_id: 'odpt.Operator:Keio',
            operator_name: '京王電鉄',
            railway_name: '京王線',
            status: 'suspended',
            status_label: '運転見合わせ',
            severity: 4,
            description: '大雨の影響で運転を見合わせています',
            updated_at: '2026-06-14T19:58:00+09:00',
            source: 'ODPT',
            lat: 36.15,
            lng: 139.05,
        },
        {
            railway_id: 'odpt.Railway:Odakyu.Odawara',
            operator_id: 'odpt.Operator:Odakyu',
            operator_name: '小田急電鉄',
            railway_name: '小田原線',
            status: 'delay',
            status_label: '遅延',
            severity: 2,
            description: '一部列車に遅れが発生しています',
            updated_at: '2026-06-14T19:57:00+09:00',
            source: 'ODPT',
            lat: 34.95,
            lng: 138.55,
        },
        {
            railway_id: 'odpt.Railway:TokyoMetro.Ginza',
            operator_id: 'odpt.Operator:TokyoMetro',
            operator_name: '東京メトロ',
            railway_name: '銀座線',
            status: 'normal',
            status_label: '平常',
            severity: 0,
            description: '平常通り運転しています',
            updated_at: '2026-06-14T19:56:00+09:00',
            source: 'ODPT',
            lat: 35.68,
            lng: 139.76,
        },
    ],
};

async function mockBaseLiveApis(page, trainResponseFactory = () => DISRUPTION_RESPONSE) {
    await page.route('/data/municipality_coords.json', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/live/weather/jma/prefectures**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unavailable', source: 'Open-Meteo Forecast', forecast_time: null, fetched_at: null, cache_status: 'unavailable', items: [] }) }));
    await page.route('/api/live/sun-moon', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/earthquakes**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/live/earthquakes/history**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('/api/tsunami/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_RESPONSE) }));
    await page.route('/api/live/storm_surge/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STORM_SURGE_NONE) }));
    await page.route('/api/live/road-traffic/summary**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', items: [] }) }));
    await page.route('/api/weather/rain/tile/times', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/summary', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('/api/live/trains/summary**', route => {
        const body = trainResponseFactory(route.request().url());
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.route('**/jmatile/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
}

test.describe('/live — 鉄道運行影響レイヤー', () => {
    test('交通影響カードが表示され、障害あり路線のみ severity 順に表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        await expect(page.locator('#lac-train-slot')).toContainText('交通影響');
        await expect(page.locator('#lac-train-slot')).toContainText('京王線');
        await expect(page.locator('#lac-train-slot')).toContainText('運転見合わせ');
        await expect(page.locator('#lac-train-slot')).toContainText('小田原線');
        await expect(page.locator('#lac-train-slot')).not.toContainText('銀座線');

        const names = await page.locator('#lac-train-slot .ltc-name').allTextContents();
        expect(names.slice(0, 2)).toEqual(['京王線', '小田原線']);
    });

    test('障害なしと取得失敗を誤判定しない', async ({ page }) => {
        let response = { status: 'ok', stale: false, scope: { mode: 'prefecture', prefecture: '東京都' }, updated_at: '2026-06-14T20:00:00+09:00', items: [] };
        await mockBaseLiveApis(page, () => response);
        await page.goto('/live.html');

        await expect(page.locator('#lac-train-slot')).toContainText('東京都で運行障害は確認されていません');

        response = { status: 'unavailable', stale: false, scope: { mode: 'prefecture', prefecture: '東京都' }, updated_at: '2026-06-14T20:01:00+09:00', items: [] };
        await page.locator('#ltc-pref-select').selectOption('大阪府');
        await expect(page.locator('#lac-train-slot')).toContainText('鉄道運行情報を取得できません');
        await expect(page.locator('#lac-train-slot')).not.toContainText('運行障害は確認されていません');
    });

    test('都道府県選択で API パラメーターが切り替わる', async ({ page }) => {
        const requested = [];
        await mockBaseLiveApis(page, url => {
            requested.push(url);
            return { status: 'ok', stale: false, scope: { mode: 'prefecture', prefecture: '福岡県' }, updated_at: '2026-06-14T20:00:00+09:00', items: [] };
        });
        await page.goto('/live.html');
        await page.locator('#ltc-pref-select').selectOption('福岡県');

        await expect.poll(() => requested.some(url => decodeURIComponent(url).includes('prefecture=福岡県'))).toBe(true);
        await expect(page.locator('#lac-train-slot')).toContainText('福岡県で運行障害は確認されていません');
    });

    test('鉄道運行影響レイヤーを ON/OFF でき、ポップアップに出典が表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('京王線');

        await page.locator('#toggle-train').check();
        await expect(page.locator('.leaflet-overlay-pane svg path.leaflet-interactive')).toHaveCount(2, { timeout: 5000 });
        await page.locator('.leaflet-overlay-pane svg path.leaflet-interactive').first().click();
        await expect(page.locator('.leaflet-popup-content')).toContainText('出典: ODPT');
        await expect(page.locator('.leaflet-popup-content')).not.toContainText('undefined');

        await page.locator('#toggle-train').uncheck();
        await expect(page.locator('.leaflet-overlay-pane svg path.leaflet-interactive')).toHaveCount(0, { timeout: 3000 });
    });

    test('モバイル幅で横スクロールが出ない', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        await expect(page.locator('#lac-train-slot')).toBeVisible();
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
        expect(overflow).toBe(false);
    });
});
