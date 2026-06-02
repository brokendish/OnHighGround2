'use strict';
/**
 * live-earthquake-layer.spec.js — /live 市区町村震度マーカー確認
 *
 * backend 不要。API と座標辞書はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

// 市区町村 points を持つ地震（最新）
const EQ_WITH_POINTS = {
    count: 1,
    items: [
        {
            event_id:       'eq-muni-001',
            occurred_at:    '2026-05-31T06:30:00+09:00',
            epicenter_name: '千葉県北東部',
            lat:             35.7,
            lng:            140.5,
            magnitude:      4.8,
            max_intensity:  '4',
            depth_km:       50,
            points: [
                { pref: '千葉県', addr: '木更津市', isArea: false, scale: 40 },  // 震度4
                { pref: '千葉県', addr: '市原市',   isArea: false, scale: 30 },  // 震度3
                { pref: '東京都', addr: '江東区',   isArea: false, scale: 30 },  // 震度3
            ],
        },
    ],
};

// points なし（フォールバック用）
const EQ_WITHOUT_POINTS = {
    count: 1,
    items: [
        {
            event_id:       'eq-rep-001',
            occurred_at:    '2026-05-31T05:00:00+09:00',
            epicenter_name: '東京湾',
            lat:            35.5,
            lng:            139.8,
            magnitude:      3.2,
            max_intensity:  '3',
            points:         [],
        },
    ],
};

// 座標辞書モック（テスト地点のみ）
const COORDS_MOCK = {
    '千葉県|木更津市': { lat: 35.376, lon: 139.916 },
    '千葉県|市原市':   { lat: 35.497, lon: 140.116 },
    '東京都|江東区':   { lat: 35.672, lon: 139.817 },
};

const TSUNAMI_RESPONSE  = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const RAIN_TIMES        = { basetime: '20260531060000', times: [
    { offset_minutes: 0, validtime: '20260531060000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260531060000/none/20260531060000/surf/hrpns/{z}/{x}/{y}.png' },
] };
const LIVE_SUMMARY      = {
    rain: { evaluated: false }, kikikuru: { evaluated: false },
    earthquake: { evaluated: true, count: 1, items: [] },
    tsunami:    { evaluated: true, active: false, areas: [] },
};
const STATIONS_RESPONSE = { count: 0, stations: [] };
const SUN_MOON_RESPONSE = {
    location: '東京', date: '2026-05-31',
    sunrise: '04:30', sunset: '18:56',
    moonrise: '14:00', moonset: '02:00',
    moon_phase: 3.2, moon_phase_name: '三日月',
};

async function mockBase(page, eqResponse) {
    await page.route('/data/municipality_coords.json', r => r.fulfill({
        status:      200,
        contentType: 'application/json',
        body:        JSON.stringify(COORDS_MOCK),
    }));
    await page.route('/api/live/sun-moon',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUN_MOON_RESPONSE) }));
    await page.route('/api/live/tide/stations',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STATIONS_RESPONSE) }));
    await page.route('/api/live/summary',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('/api/live/storm_surge/**',     r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', evaluated: true, summary: { active: false }, areas: [] }) }));
    await page.route('/api/earthquakes**',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(eqResponse) }));
    await page.route('/api/tsunami/**',              r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_RESPONSE) }));
    await page.route('/api/weather/rain/tile/times', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('**/jmatile/**',                r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',              r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',  r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
}

test.describe('/live — 市区町村震度マーカー', () => {

    // ── 市区町村マーカー表示 ──────────────────────────────────────────────────

    test.describe('points あり → 市区町村マーカー', () => {
        test.beforeEach(async ({ page }) => {
            await mockBase(page, EQ_WITH_POINTS);
            await page.goto('/live.html');
            await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
            // 座標辞書ロードと描画を待つ
            await page.waitForTimeout(800);
        });

        test('市区町村震度マーカーが表示される（divIcon）', async ({ page }) => {
            const markers = page.locator('.leaflet-marker-icon .earthquake-intensity-marker');
            await expect(markers.first()).toBeVisible({ timeout: 5000 });
        });

        test('市区町村マーカーが3件（座標登録済み地点数）表示される', async ({ page }) => {
            const markers = page.locator('.earthquake-intensity-marker');
            await expect(markers).toHaveCount(3, { timeout: 5000 });
        });

        test('震度数字ラベルが表示される', async ({ page }) => {
            const markers = page.locator('.earthquake-intensity-marker');
            const texts = await markers.allTextContents();
            expect(texts.some(t => t.includes('4') || t.includes('3'))).toBe(true);
        });

        test('地震トグル OFF で市区町村マーカーが消える', async ({ page }) => {
            await expect(page.locator('.earthquake-intensity-marker').first()).toBeVisible({ timeout: 5000 });
            await page.locator('#toggle-earthquake').uncheck();
            await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0, { timeout: 3000 });
        });

        test('地震トグル OFF → ON で市区町村マーカーが復帰する', async ({ page }) => {
            await expect(page.locator('.earthquake-intensity-marker').first()).toBeVisible({ timeout: 5000 });
            await page.locator('#toggle-earthquake').uncheck();
            await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0, { timeout: 3000 });
            await page.locator('#toggle-earthquake').check();
            await page.waitForTimeout(500);
            await expect(page.locator('.earthquake-intensity-marker').first()).toBeVisible({ timeout: 3000 });
        });

        test('市区町村マーカークリックでポップアップが開く', async ({ page }) => {
            const marker = page.locator('.earthquake-intensity-marker').first();
            await expect(marker).toBeVisible({ timeout: 5000 });
            await marker.click({ force: true });
            await expect(page.locator('.leaflet-popup')).toBeVisible({ timeout: 3000 });
        });

        test('ポップアップに都道府県・市区町村名が含まれる', async ({ page }) => {
            const marker = page.locator('.earthquake-intensity-marker').first();
            await expect(marker).toBeVisible({ timeout: 5000 });
            await marker.click({ force: true });
            await expect(page.locator('.leaflet-popup')).toBeVisible({ timeout: 3000 });
            const text = await page.locator('.leaflet-popup-content').textContent();
            // 千葉県のいずれかの市区町村名が含まれる
            expect(text).toMatch(/千葉県|東京都/);
            expect(text).toContain('震度');
        });
    });

    // ── フォールバック ────────────────────────────────────────────────────────

    test.describe('points なし → 代表地点マーカー フォールバック', () => {
        test.beforeEach(async ({ page }) => {
            await mockBase(page, EQ_WITHOUT_POINTS);
            await page.goto('/live.html');
            await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
            await page.waitForTimeout(500);
        });

        test('市区町村マーカーは表示されない', async ({ page }) => {
            await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0, { timeout: 3000 });
        });

        test('代表地点フォールバック時に市区町村マーカーは0件のまま', async ({ page }) => {
            // フォールバック時の確認は「市区町村 divIcon がないこと」で担保する。
            // circleMarker は preferCanvas:true でCanvas描画されテスト困難なため対象外。
            await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0, { timeout: 3000 });
        });
    });

    // ── 座標辞書なし → フォールバック ────────────────────────────────────────

    test.describe('座標辞書ロード失敗 → フォールバック', () => {
        test.beforeEach(async ({ page }) => {
            await mockBase(page, EQ_WITH_POINTS);
            // 座標辞書を 503 で失敗させる
            await page.route('/data/municipality_coords.json', r => r.fulfill({ status: 503 }));
            await page.goto('/live.html');
            await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
            await page.waitForTimeout(500);
        });

        test('市区町村マーカーは表示されない', async ({ page }) => {
            await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0, { timeout: 3000 });
        });
    });

    // ── ナビ本体非干渉 ────────────────────────────────────────────────────────

    test('ナビ本体 index.html は市区町村マーカーを自動表示しない', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000);
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0);
    });

    // ── console error なし ───────────────────────────────────────────────────

    test('市区町村マーカー表示中に console.error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        await mockBase(page, EQ_WITH_POINTS);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(1000);
        expect(errors).toHaveLength(0);
    });
});
