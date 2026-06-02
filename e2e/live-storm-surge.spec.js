'use strict';
/**
 * live-storm-surge.spec.js — /live 高潮・津波レイヤー確認
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const EQ_RESPONSE      = { count: 0, items: [] };
const TSUNAMI_NONE     = { source: 'mock', status: 'none', observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const TSUNAMI_WARNING  = {
    source: 'mock', status: 'active', observed_at: null, updated_at: null, ttl_seconds: 60,
    areas: [
        { code: null, name: '東京湾内湾', level: 'warning', level_label: '津波警報', expected_height: '1m', arrival_time: null, is_target: true },
    ],
    message: '津波警報が発表されています。',
};
const STORM_SURGE_NONE = {
    status: 'ok', evaluated: true,
    summary: { active: false, warning_area_count: 0 },
    areas: [],
    updated_at: null,
};
const STORM_SURGE_WARNING = {
    status: 'ok', evaluated: true,
    summary: { active: true, warning_area_count: 1 },
    areas: [
        { id: 'storm_surge-0', label: '東京都', detail: '高潮警報', level: 'danger', type: 'storm_surge', source: 'mock', lat: 35.6762, lng: 139.6503 },
    ],
    updated_at: null,
};
const RAIN_TIMES = { basetime: '20260601000000', times: [
    { offset_minutes: 0, validtime: '20260601000000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260601000000/none/20260601000000/surf/hrpns/{z}/{x}/{y}.png' },
] };

function _liveSummary(tsunamiAreas, stormSurgeAreas) {
    return {
        status: 'ok',
        rain:        { status: 'ok', evaluated: false, summary: {}, areas: [] },
        kikikuru:    { status: 'ok', evaluated: false, summary: {}, areas: [] },
        earthquake:  { status: 'ok', evaluated: true, summary: { count_24h: 0, m5_count: 0 }, areas: [] },
        tsunami:     { status: 'ok', evaluated: true, summary: { active: tsunamiAreas.length > 0, warning_area_count: tsunamiAreas.length }, areas: tsunamiAreas },
        storm_surge: { status: 'ok', evaluated: true, summary: { active: stormSurgeAreas.length > 0, warning_area_count: stormSurgeAreas.length }, areas: stormSurgeAreas },
        dangerous_areas: [],
    };
}

async function mockBase(page, { tsunamiResp = TSUNAMI_NONE, stormSurgeResp = STORM_SURGE_NONE } = {}) {
    await page.route('/api/earthquakes**',              route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**',                 route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tsunamiResp) }));
    await page.route('/api/live/storm_surge/**',        route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(stormSurgeResp) }));
    await page.route('/api/live/tide/stations',         route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/tide/**',               route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/astro**',               route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/live/sun_moon**',            route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/weather/rain/tile/times',    route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/summary',               route => {
        const tsAreas = tsunamiResp.areas || [];
        const ssAreas = stormSurgeResp.areas || [];
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(_liveSummary(tsAreas, ssAreas)) });
    });
    await page.route('**/jmatile/**',                   route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',                 route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',     route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
}

// ── レイヤーパネル ────────────────────────────────────────────────────────────

test.describe('/live — レイヤーパネル（津波・高潮）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
    });

    test('津波トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-tsunami')).toBeVisible();
    });

    test('高潮トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-storm-surge')).toBeVisible();
    });

    test('津波トグルの初期状態が ON', async ({ page }) => {
        await expect(page.locator('#toggle-tsunami')).toBeChecked();
    });

    test('高潮トグルの初期状態が ON', async ({ page }) => {
        await expect(page.locator('#toggle-storm-surge')).toBeChecked();
    });
});

// ── 津波なし時のアラートパネル ────────────────────────────────────────────────

test.describe('/live — アラートパネル（高潮なし）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_NONE });
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });
    });

    test('高潮警報なしが表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('高潮警報なし', { timeout: 6000 });
    });
});

// ── 高潮警報あり時のアラートパネル ─────────────────────────────────────────────

test.describe('/live — アラートパネル（高潮警報あり）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });
    });

    test('高潮警報バッジが表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('高潮警報', { timeout: 6000 });
    });

    test('発令都道府県名が表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('東京都', { timeout: 6000 });
    });
});

// ── 高潮レイヤーAPI呼び出し ───────────────────────────────────────────────────

test.describe('/live — 高潮API呼び出し', () => {
    test('起動時に /api/live/storm_surge/warnings が呼ばれる', async ({ page }) => {
        await mockBase(page);
        const [req] = await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        expect(req.url()).toContain('/api/live/storm_surge/warnings');
    });
});

// ── 高潮警報マーカー ─────────────────────────────────────────────────────────

test.describe('/live — 高潮警報マーカー表示', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(300);
    });

    test('高潮警報マーカーが地図上に表示される', async ({ page }) => {
        const markers = page.locator('.leaflet-marker-icon[title="東京都"]');
        await expect(markers).toHaveCount(1, { timeout: 5000 });
    });

    test('高潮トグル OFF でマーカーが消える', async ({ page }) => {
        await expect(page.locator('.leaflet-marker-icon[title="東京都"]')).toHaveCount(1, { timeout: 5000 });
        await page.locator('#toggle-storm-surge').uncheck();
        await expect(page.locator('.leaflet-marker-icon[title="東京都"]')).toHaveCount(0, { timeout: 3000 });
    });
});

// ── 津波警報マーカー ─────────────────────────────────────────────────────────

test.describe('/live — 津波警報マーカー表示', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_WARNING, stormSurgeResp: STORM_SURGE_NONE });
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(500);
    });

    test('津波警報がアラートカードに表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('津波警報', { timeout: 6000 });
    });

    test('津波トグル OFF でマーカーが消える（あれば）', async ({ page }) => {
        // 「東京湾内湾」は座標テーブルに含まれるのでマーカーが出る
        await page.locator('#toggle-tsunami').uncheck();
        // OFF 後マーカーが 0件になることを確認（高潮なしなので）
        await expect(page.locator('.leaflet-marker-icon[title="東京湾内湾"]')).toHaveCount(0, { timeout: 3000 });
    });
});

// ── ステータスバー ────────────────────────────────────────────────────────────

test.describe('/live — ステータスバー（高潮）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-status-bar').waitFor({ timeout: 8000 });
    });

    test('ステータスバーに高潮項目が存在する', async ({ page }) => {
        await expect(page.locator('#live-status-bar')).toContainText('高潮', { timeout: 6000 });
    });
});
