'use strict';
/**
 * live-train-label-layer.spec.js — 鉄道路線名・駅名ラベル表示 E2E確認
 *
 * Phase 7-A.4: 鉄道運行影響レイヤーON時に路線名・駅名ラベルを表示。
 * - レイヤーON/OFFでラベル表示が切り替わる
 * - zoom 8〜10 で路線名ラベルが表示される
 * - zoom 13 以上で駅名ラベルが表示される
 * - 障害路線ラベルに状態バッジが付く
 * - 表示数が上限内に収まる
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

const TRAIN_OK_EMPTY = {
    status: 'ok', stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-18T10:00:00+09:00',
    items: [],
};

const TRAIN_WITH_GINZA_SUSPENDED = {
    status: 'ok', stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-18T10:00:00+09:00',
    items: [{
        railway_id: 'odpt.Railway:TokyoMetro.Ginza',
        operator_id: 'odpt.Operator:TokyoMetro',
        operator_name: '東京メトロ',
        railway_name: '銀座線',
        status: 'suspended',
        status_label: '運転見合わせ',
        severity: 4,
        description: '大雨の影響',
        updated_at: '2026-06-18T09:58:00+09:00',
        source: 'ODPT',
        lat: 35.6746, lng: 139.7613,
    }],
};

// 路線GeoJSONモック（銀座線 + 山手線）
const STATIC_WITH_ROUTES = {
    type: 'FeatureCollection',
    features: [
        {
            type: 'Feature',
            properties: { osm_id: '1001', name: '銀座線', name_en: 'Ginza Line', railway: 'subway' },
            geometry: { type: 'LineString', coordinates: [[139.76, 35.67], [139.77, 35.68]] },
        },
        {
            type: 'Feature',
            properties: { osm_id: '1002', name: '山手線', name_en: 'Yamanote Line', railway: 'rail' },
            geometry: { type: 'LineString', coordinates: [[139.78, 35.70], [139.79, 35.71]] },
        },
    ],
};

// 駅GeoJSONモック（主要駅のみ）
const STATIC_STATIONS = {
    type: 'FeatureCollection',
    features: [
        {
            type: 'Feature',
            properties: { name: '新宿', name_en: 'Shinjuku', railway: 'station', train: 'yes' },
            geometry: { type: 'Point', coordinates: [139.7006, 35.6896] },
        },
        {
            type: 'Feature',
            properties: { name: '渋谷', name_en: 'Shibuya', railway: 'station', train: 'yes' },
            geometry: { type: 'Point', coordinates: [139.7020, 35.6580] },
        },
        {
            type: 'Feature',
            properties: { name: '池袋', name_en: 'Ikebukuro', railway: 'station', train: 'yes' },
            geometry: { type: 'Point', coordinates: [139.7100, 35.7295] },
        },
        {
            type: 'Feature',
            properties: { name: '東京', name_en: 'Tokyo', railway: 'station', train: 'yes' },
            geometry: { type: 'Point', coordinates: [139.7670, 35.6814] },
        },
        {
            type: 'Feature',
            properties: { name: '銀座', name_en: 'Ginza', railway: 'station' },
            geometry: { type: 'Point', coordinates: [139.7650, 35.6713] },
        },
    ],
};

const STATIC_URL   = '/layers/railways/kanto_railways.geojson';
const STATION_URL  = '/layers/railways/kanto_stations.geojson';

async function mockBaseLiveApis(page, trainResponse = TRAIN_OK_EMPTY) {
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
}

test.describe('/live — 鉄道路線名・駅名ラベル (Phase 7-A.4)', () => {

    test('liveTrainLabelLayer がグローバルに存在し公開APIを持つ', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify({ type: 'FeatureCollection', features: [] }) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));
        await page.goto('/live.html');

        const api = await page.evaluate(() => ({
            hasSetVisible:       typeof window.liveTrainLabelLayer?.setVisible       === 'function',
            hasSetRouteFeatures: typeof window.liveTrainLabelLayer?.setRouteFeatures === 'function',
            hasSetDisruptions:   typeof window.liveTrainLabelLayer?.setDisruptions   === 'function',
        }));
        expect(api.hasSetVisible).toBe(true);
        expect(api.hasSetRouteFeatures).toBe(true);
        expect(api.hasSetDisruptions).toBe(true);
    });

    test('レイヤーOFF時は路線名ラベルが表示されない', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        let stationCalled = false;
        await page.route(STATION_URL, r => {
            stationCalled = true;
            return r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) });
        });

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        // トグルOFF（デフォルト）でラベルは表示されない
        await page.waitForTimeout(400);

        const labels = await page.locator('.tll-route-label').count();
        expect(labels).toBe(0);
        expect(stationCalled).toBe(false);
    });

    test('レイヤーON時（zoom 9）に路線名ラベルが表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(500);

        const labels = await page.locator('.tll-route-label').count();
        expect(labels).toBeGreaterThan(0);
    });

    test('zoom 10では駅名ラベルが表示されない', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        let stationCalled = false;
        await page.route(STATION_URL, r => {
            stationCalled = true;
            return r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) });
        });

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(500);

        // zoom 10 では station ラベルが表示されない（limit = 0）
        const stationLabels = await page.locator('.tll-station-label').count();
        expect(stationLabels).toBe(0);
        expect(stationCalled).toBe(false);
    });

    test('zoom 13以上で主要駅名ラベルが表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        const stationPromise = page.waitForResponse(STATION_URL, { timeout: 5000 }).catch(() => null);
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 13));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await stationPromise;
        await page.waitForTimeout(500);

        // zoom 13 では主要駅ラベルが表示される
        const stationLabels = await page.locator('.tll-station-label').count();
        expect(stationLabels).toBeGreaterThan(0);
    });

    test('障害路線ラベルに状態バッジが表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(500);

        // 障害路線ラベルには状態バッジが表示される
        const badges = await page.locator('.tll-status-badge').count();
        expect(badges).toBeGreaterThan(0);
    });

    test('障害路線ラベルに「見合わせ」テキストが含まれる', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(500);

        await expect(page.locator('.tll-status-badge')).toContainText('見合わせ');
    });

    test('zoom 13では障害路線近傍駅を主要駅でなくても表示する', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        const stationPromise = page.waitForResponse(STATION_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.675, 139.765], 13));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await stationPromise;
        await page.waitForTimeout(500);

        await expect(page.locator('.tll-station-label').filter({ hasText: '銀座' })).toHaveCount(1);
    });

    test('レイヤーOFFでラベルが消える', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(500);

        // ON時にラベルが表示されていることを確認
        const onCount = await page.locator('.tll-route-label').count();
        expect(onCount).toBeGreaterThan(0);

        // OFFにするとラベルが消える
        await page.locator('#toggle-train').uncheck();
        await page.waitForTimeout(300);
        const offCount = await page.locator('.tll-route-label').count();
        expect(offCount).toBe(0);
    });

    test('路線名ラベルの表示数が上限（zoom 8〜10: max 20）を超えない', async ({ page }) => {
        // 30路線のモックデータを生成
        const manyRoutes = {
            type: 'FeatureCollection',
            features: Array.from({ length: 30 }, (_, i) => ({
                type: 'Feature',
                properties: { osm_id: String(3000 + i), name: `テスト路線${i}`, railway: 'rail' },
                geometry: {
                    type: 'LineString',
                    coordinates: [[139.70 + i * 0.01, 35.65], [139.71 + i * 0.01, 35.70]],
                },
            })),
        };

        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(manyRoutes) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        // zoom 8-10 では max 20 件
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(500);

        const labelCount = await page.locator('.tll-route-label').count();
        expect(labelCount).toBeLessThanOrEqual(20);
    });

    test('駅データ取得失敗でもラベル層はクラッシュしない', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_ROUTES) }));
        // 駅データは503エラー
        await page.route(STATION_URL, r => r.fulfill({ status: 503, body: 'error' }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 13));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(600);

        // 駅データ失敗でも路線ラベルは表示される
        const routeLabels = await page.locator('.tll-route-label').count();
        expect(routeLabels).toBeGreaterThan(0);
    });

    test('zoom 8未満ではラベルが表示されない', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify({ type: 'FeatureCollection', features: [] }) }));
        await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_STATIONS) }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 7));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(600);

        const labels = await page.locator('.tll-route-label, .tll-station-label').count();
        expect(labels).toBe(0);
    });

});
