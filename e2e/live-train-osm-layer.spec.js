'use strict';
/**
 * live-train-osm-layer.spec.js — OSM鉄道路線ベースレイヤー + 障害強調 E2E確認
 *
 * backend 不要。静的GeoJSONエンドポイント + live APIをモック。
 *
 * Phase 7-A.3 変更点:
 *   - 通常路線は路線公式カラーで表示（白系 #bbbbbb → 路線色）
 *   - 障害状態でも路線色を維持。線幅・dashArray・ハローで状態を表現。
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

// 銀座線の公式カラー（Phase 7-A.3 以降の期待値）
const GINZA_LINE_COLOR = '#F39700';

// 銀座線が suspended の障害データ
const TRAIN_WITH_GINZA_SUSPENDED = {
    status: 'ok', stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-14T20:00:00+09:00',
    items: [{
        railway_id: 'odpt.Railway:TokyoMetro.Ginza',
        operator_id: 'odpt.Operator:TokyoMetro',
        operator_name: '東京メトロ',
        railway_name: '銀座線',
        status: 'suspended',
        status_label: '運転見合わせ',
        severity: 4,
        description: '大雨の影響',
        updated_at: '2026-06-14T19:58:00+09:00',
        source: 'ODPT',
        lat: 35.6746, lng: 139.7613,
    }],
};
const TRAIN_OK_EMPTY = {
    status: 'ok', stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-14T20:00:00+09:00',
    items: [],
};

function trainWithGinzaStatus(status, label, severity) {
    return {
        status: 'ok', stale: false,
        scope: { mode: 'prefecture', prefecture: '東京都' },
        updated_at: '2026-06-14T20:00:00+09:00',
        items: [{
            railway_id: 'odpt.Railway:TokyoMetro.Ginza',
            operator_id: 'odpt.Operator:TokyoMetro',
            operator_name: '東京メトロ',
            railway_name: '銀座線',
            status,
            status_label: label,
            severity,
            description: `${label}の確認`,
            updated_at: '2026-06-14T19:58:00+09:00',
            source: 'ODPT',
            lat: 35.6746, lng: 139.7613,
        }],
    };
}

// 静的GeoJSONモック: 銀座線 + 山手線 (FeatureCollection形式)
const STATIC_WITH_GINZA = {
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
const STATIC_EMPTY = { type: 'FeatureCollection', features: [] };
const STATIC_WITH_DUPLICATE_AND_NOISE = {
    type: 'FeatureCollection',
    features: [
        {
            type: 'Feature',
            properties: { osm_id: '2001', name: '東京メトロ銀座線', name_en: 'Ginza Line', railway: 'subway' },
            geometry: { type: 'LineString', coordinates: [[139.76, 35.67], [139.77, 35.68]] },
        },
        {
            type: 'Feature',
            properties: { osm_id: '2002', name: '東京メトロ銀座線', name_en: 'Ginza Line', railway: 'subway' },
            geometry: { type: 'LineString', coordinates: [[139.77, 35.68], [139.78, 35.69]] },
        },
        {
            type: 'Feature',
            properties: { osm_id: '2003', name: '', name_en: '', railway: 'rail' },
            geometry: { type: 'LineString', coordinates: [[139.761, 35.671], [139.762, 35.672]] },
        },
        {
            type: 'Feature',
            properties: { osm_id: '2004', name: '東海道貨物線', name_en: 'Tokaido Freight Line', railway: 'rail' },
            geometry: { type: 'LineString', coordinates: [[139.763, 35.673], [139.764, 35.674]] },
        },
        {
            type: 'Feature',
            properties: { osm_id: '2005', name: '銀座線車庫線', name_en: 'Ginza Depot Track', railway: 'service', service: 'yard' },
            geometry: { type: 'LineString', coordinates: [[139.765, 35.675], [139.766, 35.676]] },
        },
    ],
};

const STATIC_URL = '/layers/railways/kanto_railways.geojson';

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

test.describe('/live — OSM鉄道路線ベースレイヤー', () => {

    test('zoom8以上でトグルON時に静的GeoJSONが取得され路線が表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({
            status: 200, contentType: 'application/geo+json',
            body: JSON.stringify(STATIC_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(200);

        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBeGreaterThanOrEqual(2);
    });

    // Phase 7-A.3: 通常路線は路線公式カラーで表示される（白系 #bbbbbb ではない）
    test('通常路線は路線公式カラー・低opacity・細線で表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({
            status: 200, contentType: 'application/geo+json',
            body: JSON.stringify(STATIC_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(200);

        // 最初のpath = 銀座線（モックの先頭feature）→ 公式カラー #F39700
        const attrs = await page.locator('.leaflet-overlay-pane svg path').first().evaluate(el => ({
            stroke: el.getAttribute('stroke'),
            strokeWidth: el.getAttribute('stroke-width'),
            strokeOpacity: el.getAttribute('stroke-opacity'),
        }));
        // 路線公式カラーで表示（白系 #bbbbbb ではない）
        expect(attrs.stroke).toBe(GINZA_LINE_COLOR);
        // 通常時は細線・低opacity
        expect(Number(attrs.strokeWidth)).toBeLessThanOrEqual(3);
        expect(Number(attrs.strokeOpacity)).toBeLessThanOrEqual(0.75);
    });

    // Phase 7-A.3: 障害状態でも路線色を維持し、線幅で状態を表現する
    for (const [status, label, severity, expectedWeight] of [
        ['delay',              '遅延',       2, 3.5],
        ['partial_suspension', '一部運休',   3, 4.0],
        ['suspended',          '運転見合わせ', 4, 4.5],
    ]) {
        test(`障害路線 ${status} は路線色を維持しつつ太線で強調表示される`, async ({ page }) => {
            await mockBaseLiveApis(page, trainWithGinzaStatus(status, label, severity));
            await page.route(STATIC_URL, r => r.fulfill({
                status: 200, contentType: 'application/geo+json',
                body: JSON.stringify(STATIC_WITH_GINZA),
            }));

            await page.goto('/live.html');
            await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

            const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
            await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
            await page.locator('#toggle-train').check();
            await staticPromise;
            await page.waitForTimeout(300);

            // bringToFront() で障害路線（銀座線）は DOM 末尾に移動する → .last()
            const attrs = await page.locator('.leaflet-overlay-pane svg path').last().evaluate(el => ({
                stroke: el.getAttribute('stroke'),
                strokeWidth: el.getAttribute('stroke-width'),
                strokeOpacity: el.getAttribute('stroke-opacity'),
            }));
            // 障害状態でも路線公式カラーを維持
            expect(attrs.stroke).toBe(GINZA_LINE_COLOR);
            // 通常より太線
            expect(Number(attrs.strokeWidth)).toBeGreaterThanOrEqual(3);
            expect(Number(attrs.strokeOpacity)).toBeGreaterThanOrEqual(0.85);
        });
    }

    // Phase 7-A.3: 一部運休は破線で表示される
    test('一部運休路線は破線（dashArray）で表示される', async ({ page }) => {
        await mockBaseLiveApis(page, trainWithGinzaStatus('partial_suspension', '一部運休', 3));
        await page.route(STATIC_URL, r => r.fulfill({
            status: 200, contentType: 'application/geo+json',
            body: JSON.stringify(STATIC_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(300);

        const dashArray = await page.locator('.leaflet-overlay-pane svg path').last().evaluate(
            el => el.getAttribute('stroke-dasharray')
        );
        expect(dashArray).toBeTruthy();
        expect(dashArray).not.toBe('none');
    });

    // Phase 7-A.3: 障害路線はハローレイヤー（背景の強調縁）を持つ
    test('障害路線（suspended）はハローパスが追加される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(STATIC_URL, r => r.fulfill({
            status: 200, contentType: 'application/geo+json',
            body: JSON.stringify(STATIC_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(300);

        // 山手線(1) + 銀座線ハロー(1) + 銀座線主線(1) = 最低3パス
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBeGreaterThanOrEqual(3);
    });

    test('同一路線featureは路線単位にまとめ、無名線・貨物線・service線は表示しない', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({
            status: 200, contentType: 'application/geo+json',
            body: JSON.stringify(STATIC_WITH_DUPLICATE_AND_NOISE),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 12));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(200);

        const paths = page.locator('.leaflet-overlay-pane svg path');
        await expect(paths).toHaveCount(1);

        const attrs = await paths.first().evaluate(el => ({
            stroke: el.getAttribute('stroke'),
            d: el.getAttribute('d'),
        }));
        expect(attrs.stroke).toBe(GINZA_LINE_COLOR);
        expect(attrs.d.split('M').length - 1).toBeGreaterThanOrEqual(2);
    });

    test('zoom7以下では静的GeoJSONを取得せず路線も表示されない', async ({ page }) => {
        let staticCalled = false;
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, async r => {
            staticCalled = true;
            await r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_EMPTY) });
        });

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        await page.evaluate(() => window.liveMap.setZoom(7));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(800);

        expect(staticCalled).toBe(false);
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBe(0);
    });

    test('静的GeoJSON失敗時もCircleMarkerフォールバックが表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(STATIC_URL, r => r.fulfill({ status: 503, body: 'error' }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

        await page.evaluate(() => window.liveMap.setZoom(9));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(800);

        // 静的GeoJSON失敗 → OSMマッチなし → CircleMarkerで表示
        const markers = await page.locator('.leaflet-overlay-pane svg path.leaflet-interactive').count();
        expect(markers).toBeGreaterThan(0);
    });

    test('障害路線がOSM路線にマッチした場合GeoJSON pathが表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(STATIC_URL, r => r.fulfill({
            status: 200, contentType: 'application/geo+json',
            body: JSON.stringify(STATIC_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(200);

        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBeGreaterThanOrEqual(2);
    });

    test('OSMマッチ路線のポップアップに事業者・状態・出典が表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(STATIC_URL, r => r.fulfill({
            status: 200, contentType: 'application/geo+json',
            body: JSON.stringify(STATIC_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('銀座線', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(200);

        const paths = page.locator('.leaflet-overlay-pane svg path.leaflet-interactive');
        const pathCount = await paths.count();
        expect(pathCount).toBeGreaterThanOrEqual(2);

        // bringToFront() で障害路線（銀座線）は DOM 末尾に移動する → .last()
        await paths.last().click({ force: true });
        await expect(page.locator('.leaflet-popup-content')).toContainText('東京メトロ', { timeout: 3000 });
        await expect(page.locator('.leaflet-popup-content')).toContainText('出典: ODPT');
    });

    test('レイヤートグルOFFでOSM路線が非表示になる', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({
            status: 200, contentType: 'application/geo+json',
            body: JSON.stringify(STATIC_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#lac-train-slot')).toContainText('交通影響', { timeout: 5000 });

        const staticPromise = page.waitForResponse(STATIC_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(200);

        const onCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(onCount).toBeGreaterThanOrEqual(2);

        await page.locator('#toggle-train').uncheck();
        await page.waitForTimeout(300);
        const offCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(offCount).toBe(0);
    });

    test('liveTrainOsmLayer がグローバルに存在し公開APIを持つ', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_EMPTY) }));
        await page.goto('/live.html');

        const api = await page.evaluate(() => ({
            hasSetDisruptions: typeof window.liveTrainOsmLayer?.setDisruptions === 'function',
            hasSetVisible:     typeof window.liveTrainOsmLayer?.setVisible     === 'function',
            hasFocusRailway:   typeof window.liveTrainOsmLayer?.focusRailway   === 'function',
        }));
        expect(api.hasSetDisruptions).toBe(true);
        expect(api.hasSetVisible).toBe(true);
        expect(api.hasFocusRailway).toBe(true);
    });

    test('liveTrainLayer に updateMatched が存在する', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route(STATIC_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_EMPTY) }));
        await page.goto('/live.html');

        const ok = await page.evaluate(() => typeof window.liveTrainLayer?.updateMatched === 'function');
        expect(ok).toBe(true);
    });

});
