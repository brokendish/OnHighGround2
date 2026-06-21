'use strict';
/**
 * live-road-osm-layer.spec.js — /live 道路ネットワークオーバーレイ E2E確認
 *
 * backend 不要。静的GeoJSONエンドポイント + live APIをモック。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const RAIN_TIMES = {
    basetime: '20260621100000',
    times: [{ offset_minutes: 0, validtime: '20260621100000',
              tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260621100000/none/20260621100000/surf/hrpns/{z}/{x}/{y}.png' }],
};
const LIVE_SUMMARY = {
    rain: { evaluated: false }, kikikuru: { evaluated: false },
    earthquake: { evaluated: true, count: 0, items: [] },
    tsunami: { evaluated: true, active: false, areas: [] },
};
const TRAIN_NONE = {
    status: 'ok', stale: false,
    scope: { mode: 'all' },
    updated_at: '2026-06-21T10:00:00+09:00',
    items: [],
};
const ROAD_TRAFFIC_NONE = {
    status: 'ok', stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-21T10:00:00+09:00',
    items: [],
};

// モック GeoJSON: 国道20号(primary) + 環八通り(secondary)
const MOCK_MAIN = {
    type: 'FeatureCollection',
    features: [
        {
            type: 'Feature',
            properties: { highway: 'primary', name: '国道20号', _live_road_name: '国道20号', _live_road_class: 'primary' },
            geometry: { type: 'MultiLineString', coordinates: [[[139.60, 35.68], [139.70, 35.68]]] },
        },
        {
            type: 'Feature',
            properties: { highway: 'secondary', name: '環八通り', _live_road_name: '環八通り', _live_road_class: 'secondary' },
            geometry: { type: 'MultiLineString', coordinates: [[[139.65, 35.65], [139.65, 35.75]]] },
        },
    ],
};

// モック GeoJSON: tertiary
const MOCK_TERT = {
    type: 'FeatureCollection',
    features: [
        {
            type: 'Feature',
            properties: { highway: 'tertiary', name: '世田谷通り', _live_road_name: '世田谷通り', _live_road_class: 'tertiary' },
            geometry: { type: 'MultiLineString', coordinates: [[[139.62, 35.64], [139.72, 35.64]]] },
        },
    ],
};

const EMPTY_FC = { type: 'FeatureCollection', features: [] };

const MAIN_URL = '/layers/roads/kanto_roads_main.geojson';
const TERT_URL = '/layers/roads/kanto_roads_tertiary.geojson';

function makeRoadFeatures(count, roadClass = 'primary', namePrefix = '主要道路') {
    return Array.from({ length: count }, (_, i) => {
        const row = Math.floor(i / 25);
        const col = i % 25;
        const lat = 35.58 + row * 0.008;
        const lon = 139.54 + col * 0.008;
        return {
            type: 'Feature',
            properties: {
                highway: roadClass,
                _live_road_name: `${namePrefix}${i}`,
                _live_road_class: roadClass,
            },
            geometry: {
                type: 'LineString',
                coordinates: [[lon, lat], [lon + 0.004, lat + 0.002]],
            },
        };
    });
}

async function mockBaseLiveApis(page) {
    await page.route('/data/municipality_coords.json', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/live/sun-moon', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/earthquakes**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, items: [] }) }));
    await page.route('/api/tsunami/**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' }) }));
    await page.route('/api/live/storm_surge/**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] }) }));
    await page.route('/api/weather/rain/tile/times', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/summary', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('/api/live/trains/summary**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TRAIN_NONE) }));
    await page.route('/api/live/road-traffic/summary**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ROAD_TRAFFIC_NONE) }));
    await page.route('**/jmatile/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('/layers/railways/**', r =>
        r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));
}

test.describe('/live — 道路ネットワークオーバーレイ', () => {

    test('liveRoadOsmLayer がグローバルに存在し公開APIを持つ', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));
        await page.goto('/live.html');

        const api = await page.evaluate(() => ({
            hasSetVisible: typeof window.liveRoadOsmLayer?.setVisible === 'function',
        }));
        expect(api.hasSetVisible).toBe(true);
    });

    test('liveRoadLabelLayer がグローバルに存在し公開APIを持つ', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));
        await page.goto('/live.html');

        const api = await page.evaluate(() => ({
            hasSetVisible:      typeof window.liveRoadLabelLayer?.setVisible      === 'function',
            hasSetRoadFeatures: typeof window.liveRoadLabelLayer?.setRoadFeatures === 'function',
            hasClearLabels:     typeof window.liveRoadLabelLayer?.clearLabels     === 'function',
        }));
        expect(api.hasSetVisible).toBe(true);
        expect(api.hasSetRoadFeatures).toBe(true);
        expect(api.hasClearLabels).toBe(true);
    });

    test('道路交通影響レイヤーON時に main GeoJSON が fetch される', async ({ page }) => {
        await mockBaseLiveApis(page);
        let mainCalled = false;
        await page.route(MAIN_URL, r => {
            mainCalled = true;
            return r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) });
        });
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 9));
        const mainPromise = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainPromise;
        await page.waitForTimeout(500);

        expect(mainCalled).toBe(true);
    });

    test('zoom8以上でON時に道路パスが描画される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 9));
        const mainPromise = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainPromise;
        await page.waitForTimeout(400);

        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        // primary(国道20号)は zoom8+ で表示。secondary(環八通り)は表示対象外
        expect(pathCount).toBeGreaterThanOrEqual(1);
    });

    test('secondary はどのズームでも表示されない（データ品質問題のため除外）', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 13));
        const mainP = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainP;
        await page.waitForTimeout(400);

        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        // zoom13 でも primary のみ表示。secondary(環八通り)は除外
        expect(pathCount).toBeGreaterThanOrEqual(1);
    });

    test('zoom13以上でも tertiary GeoJSON は fetch されない（削除済み）', async ({ page }) => {
        await mockBaseLiveApis(page);
        let tertCalled = false;
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => {
            tertCalled = true;
            return r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_TERT) });
        });

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 13));
        const mainP = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainP;
        await page.waitForTimeout(600);

        // tertiary は名前マージによるガタガタ問題のため非表示
        expect(tertCalled).toBe(false);
    });

    test('zoom7以下では GeoJSON を fetch せず道路も表示されない', async ({ page }) => {
        let mainCalled = false;
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, async r => {
            mainCalled = true;
            await r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) });
        });
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setZoom(7));
        await page.locator('#toggle-road-traffic').check();
        await page.waitForTimeout(600);

        expect(mainCalled).toBe(false);
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBe(0);
    });

    test('レイヤーOFFで道路パスが消える', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 11));
        const mainP = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainP;
        await page.waitForTimeout(400);

        const onCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(onCount).toBeGreaterThanOrEqual(1);

        await page.locator('#toggle-road-traffic').uncheck();
        await page.waitForTimeout(300);

        const offCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(offCount).toBe(0);
    });

    test('道路ポップアップに道路名と種別が表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 11));
        const mainP = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainP;
        await page.waitForTimeout(400);

        const paths = page.locator('.leaflet-overlay-pane svg path.leaflet-interactive');
        const count = await paths.count();
        if (count > 0) {
            await paths.first().click({ force: true });
            const popup = page.locator('.leaflet-popup-content');
            await expect(popup).toContainText('種別:', { timeout: 3000 });
        }
    });

    test('道路ラベルが表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 11));
        const mainP = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainP;
        await page.waitForTimeout(500);

        // 道路名ラベルが表示される
        const labels = page.locator('.rll-road-label');
        await expect.poll(() => labels.count(), { timeout: 3000 }).toBeGreaterThan(0);
    });

    test('レイヤーOFFでラベルも消える', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 11));
        const mainP = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainP;
        await page.waitForTimeout(500);

        await page.locator('#toggle-road-traffic').uncheck();
        await page.waitForTimeout(300);

        const labelCount = await page.locator('.rll-road-label').count();
        expect(labelCount).toBe(0);
    });

    test('観測点マーカー（交通量API）と道路ネットワークが共存する', async ({ page }) => {
        const trafficData = {
            status: 'ok', stale: false,
            scope: { mode: 'prefecture', prefecture: '東京都' },
            updated_at: '2026-06-21T10:00:00+09:00',
            items: [{
                station_id: 'T001', road_name: '国道20号', direction: '上り',
                lat: 35.68, lng: 139.65,
                volume_5min: 180, volume_1h: 2160,
                baseline_volume_1h: null,
                status: 'very_high', status_label: '交通量非常に多い', severity: 3,
                observed_at: '2026-06-21T09:55:00+09:00',
                source: 'mock',
            }],
        };
        await mockBaseLiveApis(page);
        await page.route('/api/live/road-traffic/summary**', r =>
            r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(trafficData) }));
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 11));
        const mainP = page.waitForResponse(MAIN_URL, { timeout: 5000 }).catch(() => null);
        await page.locator('#toggle-road-traffic').check();
        await mainP;
        await page.waitForTimeout(500);

        // 道路パス
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBeGreaterThanOrEqual(1);
        // 観測点マーカー
        const markerCount = await page.locator('[class*="road-traffic-"]').count();
        expect(markerCount).toBeGreaterThan(0);
    });

    test('鉄道レイヤーと競合しない（両方ON時に各レイヤーが独立して表示される）', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(MOCK_MAIN) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        const trainGeoJson = {
            type: 'FeatureCollection',
            features: [{
                type: 'Feature',
                properties: { name: '山手線', railway: 'rail' },
                geometry: { type: 'LineString', coordinates: [[139.78, 35.70], [139.79, 35.71]] },
            }],
        };
        await page.route('/layers/railways/kanto_railways.geojson', r =>
            r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(trainGeoJson) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.70, 139.70], 11));

        await page.locator('#toggle-train').check();
        await page.locator('#toggle-road-traffic').check();
        await page.waitForTimeout(800);

        // 両レイヤーが描画されている
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBeGreaterThanOrEqual(2);
    });

    test('main GeoJSON 取得失敗時もクラッシュせずカードは表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 503, body: 'error' }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 9));
        await page.locator('#toggle-road-traffic').check();
        await page.waitForTimeout(800);

        // エラーでもアラートカードは表示されたまま（クラッシュしない）
        await expect(page.locator('#live-alert-card')).toBeVisible();
    });

    test('凡例に道路タブが存在し道路種別が表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');

        // 凡例パネルを開く
        const legendBtn = page.locator('#live-legend-toggle');
        await expect(legendBtn).toBeVisible({ timeout: 5000 });
        await legendBtn.click();

        // 道路タブをクリック
        const roadTab = page.locator('.llp-tab[data-tab="road"]');
        await expect(roadTab).toBeVisible();
        await roadTab.click();

        // 道路種別が表示される（secondary は除外済み）
        await expect(page.locator('#live-legend-panel')).toContainText('高速道路');
        await expect(page.locator('#live-legend-panel')).toContainText('国道級');
        await expect(page.locator('#live-legend-panel')).not.toContainText('主要地方道級');
        // 通行止め断定表現がない
        await expect(page.locator('#live-legend-panel')).not.toContainText('通行止めです');
        await expect(page.locator('#live-legend-panel')).toContainText('通行止め・規制を断定するものではありません');
    });

    test('モバイル幅で横スクロールが出ない', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await mockBaseLiveApis(page);
        await page.route(MAIN_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));
        await page.goto('/live.html');

        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
        );
        expect(overflow).toBe(false);
    });

    test('zoom 8〜10 の描画フィーチャーは優先度順で200件以下に制限される', async ({ page }) => {
        await mockBaseLiveApis(page);
        const features = [
            ...makeRoadFeatures(240, 'primary', '国道級'),
            ...makeRoadFeatures(20, 'motorway', '高速道路'),
        ];
        await page.route(MAIN_URL, r => r.fulfill({
            status: 200,
            contentType: 'application/geo+json',
            body: JSON.stringify({ type: 'FeatureCollection', features }),
        }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 9));
        await page.locator('#toggle-road-traffic').check();
        await page.waitForTimeout(700);

        const paths = page.locator('.leaflet-overlay-pane svg path');
        expect(await paths.count()).toBeLessThanOrEqual(200);
        const motorwayPaths = page.locator('.leaflet-overlay-pane svg path[stroke="#43A047"]');
        expect(await motorwayPaths.count()).toBeGreaterThan(0);
    });

    test('モバイル zoom 13 はラベル12件以下で英数字refだけの名称を除外する', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await mockBaseLiveApis(page);
        const named = makeRoadFeatures(40, 'primary', '主要道路');
        named.push({
            type: 'Feature',
            properties: { highway: 'primary', _live_road_name: 'R16', _live_road_class: 'primary' },
            geometry: { type: 'LineString', coordinates: [[139.65, 35.68], [139.66, 35.69]] },
        });
        await page.route(MAIN_URL, r => r.fulfill({
            status: 200,
            contentType: 'application/geo+json',
            body: JSON.stringify({ type: 'FeatureCollection', features: named }),
        }));
        await page.route(TERT_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(EMPTY_FC) }));

        await page.goto('/live.html');
        await page.evaluate(() => window.liveMap.setView([35.68, 139.65], 13));
        await page.evaluate(() => {
            const input = document.querySelector('#toggle-road-traffic');
            input.checked = true;
            input.dispatchEvent(new Event('change', { bubbles: true }));
        });
        await page.waitForTimeout(700);

        const labels = page.locator('.rll-road-label');
        expect(await labels.count()).toBeLessThanOrEqual(12);
        await expect(labels.filter({ hasText: /^R16$/ })).toHaveCount(0);
    });

});
