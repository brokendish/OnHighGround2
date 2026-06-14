'use strict';
/**
 * live-train-osm-layer.spec.js — OSM鉄道路線ベースレイヤー + 障害強調 E2E確認
 *
 * backend 不要。Overpass API + live API をすべてモック。
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

// Overpass レスポンス: 銀座線を含む2路線
const OVERPASS_WITH_GINZA = {
    version: 0.6, elements: [
        {
            type: 'way', id: 1001,
            geometry: [{ lat: 35.67, lon: 139.76 }, { lat: 35.68, lon: 139.77 }],
            tags: { railway: 'subway', name: '銀座線', 'name:en': 'Ginza Line' },
        },
        {
            type: 'way', id: 1002,
            geometry: [{ lat: 35.70, lon: 139.78 }, { lat: 35.71, lon: 139.79 }],
            tags: { railway: 'rail', name: '山手線', 'name:en': 'Yamanote Line' },
        },
    ],
};
const OVERPASS_EMPTY = { version: 0.6, elements: [] };

async function mockBaseLiveApis(page, trainResponse = TRAIN_OK_EMPTY) {
    await page.route('/data/municipality_coords.json', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/live/sun-moon', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/earthquakes**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, items: [] }) }));
    await page.route('/api/tsunami/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' }) }));
    await page.route('/api/live/storm_surge/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] }) }));
    await page.route('/api/weather/rain/tile/times', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/summary', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('/api/live/trains/summary**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(trainResponse) }));
    await page.route('**/jmatile/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
}

test.describe('/live — OSM鉄道路線ベースレイヤー', () => {

    test('zoom8以上でトグルON時にOverpass APIが呼ばれ路線が表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route('/api/live/trains/osm**', r => r.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify(OVERPASS_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#live-train-card')).toContainText('交通影響', { timeout: 5000 });

        // Overpass fetch の完了を waitForResponse で確実に待つ
        const overpassPromise = page.waitForResponse('/api/live/trains/osm**', { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setZoom(9));
        await page.locator('#toggle-train').check();
        await overpassPromise;
        await page.waitForTimeout(200); // DOM 反映待ち

        // GeoJSON 路線が SVG path として描画される
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBeGreaterThanOrEqual(2);
    });

    test('通常路線は薄グレー・低opacity・細線で表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route('/api/live/trains/osm**', r => r.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify(OVERPASS_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#live-train-card')).toContainText('交通影響', { timeout: 5000 });

        const overpassPromise = page.waitForResponse('/api/live/trains/osm**', { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setZoom(9));
        await page.locator('#toggle-train').check();
        await overpassPromise;

        const attrs = await page.locator('.leaflet-overlay-pane svg path').first().evaluate(el => ({
            stroke: el.getAttribute('stroke'),
            strokeWidth: el.getAttribute('stroke-width'),
            strokeOpacity: el.getAttribute('stroke-opacity'),
        }));
        expect(attrs.stroke).toBe('#888888');
        expect(Number(attrs.strokeWidth)).toBeLessThanOrEqual(2);
        expect(Number(attrs.strokeOpacity)).toBeLessThanOrEqual(0.35);
    });

    for (const [status, label, severity, color] of [
        ['delay', '遅延', 2, '#FFD54F'],
        ['partial_suspension', '一部運休', 3, '#FF9800'],
        ['suspended', '運転見合わせ', 4, '#F44336'],
    ]) {
        test(`障害路線 ${status} は状態色で強調表示される`, async ({ page }) => {
            await mockBaseLiveApis(page, trainWithGinzaStatus(status, label, severity));
            await page.route('/api/live/trains/osm**', r => r.fulfill({
                status: 200, contentType: 'application/json',
                body: JSON.stringify(OVERPASS_WITH_GINZA),
            }));

            await page.goto('/live.html');
            await expect(page.locator('#live-train-card')).toContainText('銀座線', { timeout: 5000 });

            const overpassPromise = page.waitForResponse('/api/live/trains/osm**', { timeout: 5000 });
            await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
            await page.locator('#toggle-train').check();
            await overpassPromise;

            const attrs = await page.locator('.leaflet-overlay-pane svg path').last().evaluate(el => ({
                stroke: el.getAttribute('stroke'),
                strokeWidth: el.getAttribute('stroke-width'),
                strokeOpacity: el.getAttribute('stroke-opacity'),
            }));
            expect(attrs.stroke).toBe(color);
            expect(Number(attrs.strokeWidth)).toBeGreaterThanOrEqual(3);
            expect(Number(attrs.strokeOpacity)).toBeGreaterThanOrEqual(0.85);
        });
    }

    test('zoom7以下ではOverpassを呼ばない', async ({ page }) => {
        let overpassCalled = false;
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route('/api/live/trains/osm**', async r => {
            overpassCalled = true;
            await r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERPASS_EMPTY) });
        });

        await page.goto('/live.html');
        await expect(page.locator('#live-train-card')).toContainText('交通影響', { timeout: 5000 });

        await page.evaluate(() => window.liveMap.setZoom(7));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(800); // デバウンス + 余裕

        expect(overpassCalled).toBe(false);
    });

    test('Overpass失敗時もCircleMarkerフォールバックが表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route('/api/live/trains/osm**', r => r.fulfill({ status: 503, body: 'error' }));

        await page.goto('/live.html');
        // API レスポンス処理を待つ（銀座線がカードに表示される）
        await expect(page.locator('#live-train-card')).toContainText('銀座線', { timeout: 5000 });

        await page.evaluate(() => window.liveMap.setZoom(9));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(800);

        // Overpass 失敗 → OSM マッチなし → CircleMarker で表示（Leaflet SVGでは path として描画）
        const markers = await page.locator('.leaflet-overlay-pane svg path.leaflet-interactive').count();
        expect(markers).toBeGreaterThan(0);
    });

    test('障害路線がOSM路線にマッチした場合GeoJSON pathが表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route('/api/live/trains/osm**', r => r.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify(OVERPASS_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#live-train-card')).toContainText('銀座線', { timeout: 5000 });

        const overpassPromise = page.waitForResponse('/api/live/trains/osm**', { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await overpassPromise;
        await page.waitForTimeout(200);

        // 2路線が GeoJSON path として描画される
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBeGreaterThanOrEqual(2);
    });

    test('OSMマッチ路線のポップアップに事業者・状態・出典が表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route('/api/live/trains/osm**', r => r.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify(OVERPASS_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#live-train-card')).toContainText('銀座線', { timeout: 5000 });

        const overpassPromise = page.waitForResponse('/api/live/trains/osm**', { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await overpassPromise;
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
        await page.route('/api/live/trains/osm**', r => r.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify(OVERPASS_WITH_GINZA),
        }));

        await page.goto('/live.html');
        await expect(page.locator('#live-train-card')).toContainText('交通影響', { timeout: 5000 });

        const overpassPromise = page.waitForResponse('/api/live/trains/osm**', { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setZoom(9));
        await page.locator('#toggle-train').check();
        await overpassPromise;
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
        await page.route('/api/live/trains/osm**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERPASS_EMPTY) }));
        await page.goto('/live.html');

        const api = await page.evaluate(() => ({
            hasSetDisruptions: typeof window.liveTrainOsmLayer?.setDisruptions === 'function',
            hasSetVisible:     typeof window.liveTrainOsmLayer?.setVisible     === 'function',
        }));
        expect(api.hasSetDisruptions).toBe(true);
        expect(api.hasSetVisible).toBe(true);
    });

    test('liveTrainLayer に updateMatched が存在する', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_OK_EMPTY);
        await page.route('/api/live/trains/osm**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERPASS_EMPTY) }));
        await page.goto('/live.html');

        const ok = await page.evaluate(() => typeof window.liveTrainLayer?.updateMatched === 'function');
        expect(ok).toBe(true);
    });

});
