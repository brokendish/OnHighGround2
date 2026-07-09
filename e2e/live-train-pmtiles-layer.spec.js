'use strict';
/**
 * live-train-pmtiles-layer.spec.js — 全国鉄道路線 PMTiles ベース表示 E2E確認
 *
 * Phase 7-A.5-A: PMTiles ベース表示（全国）
 * Phase 7-A.5-B: 駅アイコン・駅名表示
 * Phase 7-A.5-C: 障害情報との連携・フォールバック
 *
 * backend 不要。PMTilesエンドポイントと live API をモック。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const RAIN_TIMES = {
    basetime: '20260627100000',
    times: [{ offset_minutes: 0, validtime: '20260627100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260627100000/none/20260627100000/surf/hrpns/{z}/{x}/{y}.png' }],
};
const LIVE_SUMMARY = {
    rain: { evaluated: false }, kikikuru: { evaluated: false },
    earthquake: { evaluated: true, count: 0, items: [] },
    tsunami: { evaluated: true, active: false, areas: [] },
};
const TRAIN_OK_EMPTY = {
    status: 'ok', stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-27T20:00:00+09:00',
    items: [],
};
const TRAIN_WITH_GINZA_SUSPENDED = {
    status: 'ok', stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-27T20:00:00+09:00',
    items: [{
        railway_id: 'odpt.Railway:TokyoMetro.Ginza',
        operator_id: 'odpt.Operator:TokyoMetro',
        operator_name: '東京メトロ',
        railway_name: '銀座線',
        status: 'suspended',
        status_label: '運転見合わせ',
        severity: 4,
        description: '大雨の影響',
        updated_at: '2026-06-27T19:58:00+09:00',
        source: 'ODPT',
        lat: 35.6746, lng: 139.7613,
    }],
};

const PMTILES_URL = '/layers/railways/railways_japan.pmtiles';
const KANTO_GEOJSON_URL = '/layers/railways/kanto_railways.geojson';
const STATION_URL = '/layers/railways/kanto_stations.geojson';

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
const STATIONS_FC = {
    type: 'FeatureCollection',
    features: [{
        type: 'Feature',
        properties: { name: '渋谷', railway: 'station', train: 'yes' },
        geometry: { type: 'Point', coordinates: [139.7016, 35.6580] },
    }],
};

// 最小限の有効 PMTiles バイナリ（ヘッダーのみ・タイルなし）
// プロトコル確認用: 実際のレンダリングは行わない
function buildMinimalPmtilesBuffer() {
    const buf = Buffer.alloc(512, 0);
    buf.write('PMTiles', 0, 'ascii');
    buf[7] = 3; // version
    return buf;
}

async function mockBaseLiveApis(page, trainResponse = TRAIN_OK_EMPTY) {
    await page.route('/data/municipality_coords.json', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/live/weather/jma/prefectures**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unavailable', source: 'Open-Meteo Forecast', forecast_time: null, fetched_at: null, cache_status: 'unavailable', items: [] }) }));
    await page.route('/api/live/sun-moon', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/earthquakes**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, items: [] }) }));
    await page.route('/api/live/earthquakes/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], source: 'p2p', fallback: false }) }));
    await page.route('/api/tsunami/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' }) }));
    await page.route('/api/live/storm_surge/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] }) }));
    await page.route('/api/weather/rain/tile/times', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/summary', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('/api/live/trains/summary**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(trainResponse) }));
    await page.route('/api/live/tide/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
    await page.route('/api/live/road/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unavailable', items: [] }) }));
    await page.route('/api/weather/warnings**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warnings: [] }) }));
    await page.route('/layers/roads/**', r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify({ type: 'FeatureCollection', features: [] }) }));
    await page.route('**/jmatile/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route(STATION_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIONS_FC) }));
}

// protomaps-leaflet CDN をテスト環境でスタブ化する。
// 実際のレンダリングは行わず、Leaflet layerGroup を返すだけの最小実装。
// 依存: Leaflet(L) が window に読み込まれていること（live.html の読み込み順で保証）。
const PROTOMAPS_STUB_JS = `
(function() {
    function stubSym() { this.draw = function() {}; }
    stubSym.prototype = {};
    window.protomapsL = {
        leafletLayer: function(opts) {
            return L.layerGroup ? L.layerGroup() : {
                addTo: function(m) { m.addLayer(this); return this; },
                remove: function() {}
            };
        },
        LineSymbolizer: stubSym,
        CircleSymbolizer: stubSym,
        CenteredTextSymbolizer: stubSym,
        LineLabelSymbolizer: stubSym,
    };
})();
`;

// protomaps-leaflet CDN をスタブ化するルートを追加する
async function mockProtomapsLeaflet(page) {
    await page.route('**/protomaps-leaflet**', route => route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: PROTOMAPS_STUB_JS,
    }));
}

// 初期化完了を待つ（#live-loading が消える → live-main.js の最後まで完了）
async function waitForLiveReady(page) {
    await page.waitForFunction(
        () => !!window.liveTrainPmtilesLayer && !!window.liveLayers,
        { timeout: 8000 },
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase 7-A.5-A: PMTiles ベース表示
// ─────────────────────────────────────────────────────────────────────────────

test.describe('Phase 7-A.5-A: PMTiles ベース表示（全国鉄道路線）', () => {

    test('window.liveTrainPmtilesLayer が定義されている', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        const defined = await page.evaluate(() => typeof window.liveTrainPmtilesLayer);
        expect(defined).toBe('object');
    });

    test('liveTrainPmtilesLayer.setVisible と isReady が関数として存在する', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        const api = await page.evaluate(() => ({
            setVisible: typeof window.liveTrainPmtilesLayer?.setVisible,
            isReady:    typeof window.liveTrainPmtilesLayer?.isReady,
        }));
        expect(api.setVisible).toBe('function');
        expect(api.isReady).toBe('function');
    });

    test('PMTilesファイルが存在しない場合 isReady() は false を返す（フォールバック）', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        // PMTiles probe の非同期完了を待つ
        await page.waitForTimeout(600);

        const ready = await page.evaluate(() => window.liveTrainPmtilesLayer?.isReady?.() ?? false);
        expect(ready).toBe(false);
    });

    test('PMTilesファイルが存在しない場合もページエラーが発生しない', async ({ page }) => {
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));

        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(600);

        expect(errors).toHaveLength(0);
    });

    test('PMTilesが存在する場合、鉄道レイヤーONでプローブリクエストが送信される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await mockProtomapsLeaflet(page);
        const pmtilesBuf = buildMinimalPmtilesBuffer();
        let probeReceived = false;

        await page.route(PMTILES_URL, async (route) => {
            probeReceived = true;
            route.fulfill({
                status: 200,
                contentType: 'application/x-protomaps',
                body: pmtilesBuf,
            });
        });
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(600);

        expect(probeReceived).toBe(true);
    });

    test('鉄道レイヤーOFFで PMTiles と GeoJSON 両方が非表示になる', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        // ON にしてから OFF
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(300);
        await page.locator('#toggle-train').uncheck();
        await page.waitForTimeout(200);

        // PMTiles レイヤー非表示
        const pmtilesReady = await page.evaluate(() => window.liveTrainPmtilesLayer?.isReady?.() ?? false);
        expect(pmtilesReady).toBe(false);

        // 路線 SVG パスが消えているか
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBe(0);
    });

    test('PMTiles確認中にOFFへ戻しても古いON処理が復活しない', async ({ page }) => {
        await mockBaseLiveApis(page);
        await mockProtomapsLeaflet(page);
        const pmtilesBuf = buildMinimalPmtilesBuffer();

        await page.route(PMTILES_URL, async (route) => {
            await new Promise(r => setTimeout(r, 450));
            await route.fulfill({
                status: 200,
                contentType: 'application/x-protomaps',
                body: pmtilesBuf,
            });
        });
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(50);
        await page.locator('#toggle-train').uncheck();
        await page.waitForTimeout(700);

        const pmtilesReady = await page.evaluate(() => window.liveTrainPmtilesLayer?.isReady?.() ?? false);
        expect(pmtilesReady).toBe(false);
        const pathCount = await page.locator('.leaflet-overlay-pane svg path').count();
        expect(pathCount).toBe(0);
    });

    test('live-layers.js の train.setVisible が PMTiles レイヤーを呼び出す', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        // liveLayers.train.setVisible が window.liveTrainPmtilesLayer を呼ぶ
        const called = await page.evaluate(async () => {
            let called = false;
            const orig = window.liveTrainPmtilesLayer.setVisible;
            window.liveTrainPmtilesLayer.setVisible = async (v) => {
                called = true;
                return orig(v);
            };
            await window.liveLayers.train.setVisible(true);
            await new Promise(r => setTimeout(r, 100));
            return called;
        });
        expect(called).toBe(true);
    });

});

// ─────────────────────────────────────────────────────────────────────────────
// Phase 7-A.5-B: 駅ラベル表示（GeoJSON フォールバック）
// ─────────────────────────────────────────────────────────────────────────────

test.describe('Phase 7-A.5-B: 駅ラベル表示', () => {

    test('zoom 11以上で駅ラベルが表示される（GeoJSONフォールバック）', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.evaluate(() => window.liveMap.setView([35.658, 139.701], 12));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(600);

        const labelCount = await page.locator('.tll-station-label').count();
        expect(labelCount).toBeGreaterThanOrEqual(1);
    });

    test('鉄道レイヤーOFF後に駅ラベルも消える', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.evaluate(() => window.liveMap.setView([35.658, 139.701], 12));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(400);
        await page.locator('#toggle-train').uncheck();
        await page.waitForTimeout(200);

        const labelCount = await page.locator('.tll-station-label').count();
        expect(labelCount).toBe(0);
    });

    test('zoom 7以下では駅ラベルが表示されない', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.evaluate(() => window.liveMap.setView([36.0, 138.0], 6));
        await page.locator('#toggle-train').check();
        await page.waitForTimeout(500);

        const labelCount = await page.locator('.tll-station-label').count();
        expect(labelCount).toBe(0);
    });

});

// ─────────────────────────────────────────────────────────────────────────────
// Phase 7-A.5-C: 障害情報連携 + フォールバック動作
// ─────────────────────────────────────────────────────────────────────────────

test.describe('Phase 7-A.5-C: 障害情報連携', () => {

    test('PMTilesが使えない場合も障害カードに路線名が表示される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.waitForFunction(
            () => document.getElementById('lac-train-slot')?.textContent?.includes('銀座線'),
            { timeout: 5000 },
        );
        const slotText = await page.locator('#lac-train-slot').textContent();
        expect(slotText).toContain('銀座線');
    });

    test('PMTiles不在でもODPT API結果が障害カードに反映される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await page.waitForFunction(
            () => document.getElementById('lac-train-slot')?.textContent?.includes('銀座線'),
            { timeout: 5000 },
        );
        const slotText = await page.locator('#lac-train-slot').textContent();
        expect(slotText).toContain('銀座線');
        expect(slotText).toContain('運転見合わせ');
        expect(slotText).toContain('東京メトロ');
    });

    test('PMTiles不在でも障害路線が GeoJSON オーバーレイで強調される', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        const staticPromise = page.waitForResponse(KANTO_GEOJSON_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await staticPromise;
        await page.waitForTimeout(400);

        // 障害路線 (suspended) は太線で強調される
        const paths = await page.locator('.leaflet-overlay-pane svg path').all();
        expect(paths.length).toBeGreaterThanOrEqual(1);

        const lastPath = paths[paths.length - 1];
        const strokeWidth = await lastPath.evaluate(el => Number(el.getAttribute('stroke-width')));
        expect(strokeWidth).toBeGreaterThanOrEqual(3.0);
    });

    test('PMTilesが有効な場合、GeoJSONの非障害路線は透明になる', async ({ page }) => {
        await mockBaseLiveApis(page, TRAIN_WITH_GINZA_SUSPENDED);
        await mockProtomapsLeaflet(page);

        const pmtilesBuf = buildMinimalPmtilesBuffer();
        await page.route(PMTILES_URL, r => r.fulfill({
            status: 200,
            contentType: 'application/x-protomaps',
            body: pmtilesBuf,
        }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        const staticPromise = page.waitForResponse(KANTO_GEOJSON_URL, { timeout: 5000 });
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 10));
        await page.locator('#toggle-train').check();
        await staticPromise;
        // PMTiles probe の非同期完了を待つ
        await page.waitForTimeout(800);

        // PMTiles が有効なら isReady() = true
        const ready = await page.evaluate(() => window.liveTrainPmtilesLayer?.isReady?.() ?? false);
        expect(ready).toBe(true);

        // GeoJSON側: 山手線（非障害）は weight=0（透明）のはず
        const paths = await page.locator('.leaflet-overlay-pane svg path').all();
        const weights = await Promise.all(paths.map(p =>
            p.evaluate(el => Number(el.getAttribute('stroke-width') || '0'))
        ));
        // weight=0 の透明パスが存在すること（非障害路線）
        expect(weights.some(w => w === 0)).toBe(true);
    });

    test('liveTrainOsmLayer グローバルが PMTiles 導入後も存在する', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        const api = await page.evaluate(() => ({
            hasSetDisruptions: typeof window.liveTrainOsmLayer?.setDisruptions,
            hasSetVisible:     typeof window.liveTrainOsmLayer?.setVisible,
            hasFocusRailway:   typeof window.liveTrainOsmLayer?.focusRailway,
        }));
        expect(api.hasSetDisruptions).toBe('function');
        expect(api.hasSetVisible).toBe('function');
        expect(api.hasFocusRailway).toBe('function');
    });

});

// ─────────────────────────────────────────────────────────────────────────────
// 回帰確認
// ─────────────────────────────────────────────────────────────────────────────

test.describe('回帰確認', () => {

    test('/live 基本表示がページエラーなし', async ({ page }) => {
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));

        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);
        await page.waitForTimeout(500);

        expect(errors).toHaveLength(0);
    });

    test('地震・雨雲・キキクルレイヤーが PMTiles 導入後も操作可能', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await expect(page.locator('#toggle-rain')).toBeVisible();
        await expect(page.locator('#toggle-kikikuru')).toBeVisible();
        await expect(page.locator('#toggle-earthquake')).toBeVisible();
        await expect(page.locator('#toggle-train')).toBeVisible();
    });

    test('道路交通レイヤーが PMTiles 導入後も操作可能', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        await expect(page.locator('#toggle-road-traffic')).toBeVisible();
    });

    test('liveTrainLayer (CircleMarker) が PMTiles 導入後も存在する', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);

        const api = await page.evaluate(() => ({
            hasSetData:    typeof window.liveTrainLayer?.setData,
            hasSetVisible: typeof window.liveTrainLayer?.setVisible,
            hasFocusItem:  typeof window.liveTrainLayer?.focusItem,
        }));
        expect(api.hasSetData).toBe('function');
        expect(api.hasSetVisible).toBe('function');
        expect(api.hasFocusItem).toBe('function');
    });

    test('鉄道レイヤー複数回ON/OFFが安定して動作する', async ({ page }) => {
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));

        await mockBaseLiveApis(page);
        await page.route(PMTILES_URL, r => r.fulfill({ status: 404 }));
        await page.route(KANTO_GEOJSON_URL, r => r.fulfill({ status: 200, contentType: 'application/geo+json', body: JSON.stringify(STATIC_WITH_GINZA) }));

        await page.goto('/live.html');
        await waitForLiveReady(page);
        await page.evaluate(() => window.liveMap.setView([35.68, 139.77], 9));

        // 3回 ON/OFF を繰り返す
        for (let i = 0; i < 3; i++) {
            await page.locator('#toggle-train').check();
            await page.waitForTimeout(150);
            await page.locator('#toggle-train').uncheck();
            await page.waitForTimeout(100);
        }

        expect(errors).toHaveLength(0);
    });

});
