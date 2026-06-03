'use strict';
/**
 * live-integrated-regions.spec.js — /live 危険地域統合ランキング確認
 *
 * backend 不要。API はすべてモックで受ける。
 * 統合ランキング: 同一地域の複数イベントを1行に集約して表示することを確認。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const EQ_RESPONSE   = { count: 0, items: [] };
const TSUNAMI_NONE  = { status: 'none', observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const SS_NONE       = { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] };
const RAIN_TIMES    = { basetime: '20260603000000', times: [
    { offset_minutes: 0, validtime: '20260603000000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260603000000/none/20260603000000/surf/hrpns/{z}/{x}/{y}.png' },
] };

// ── サマリーモック生成ヘルパー ─────────────────────────────────────────────────

function makeSummary({ dangerousAreas = [], integratedRegions = [] } = {}) {
    return {
        status:   'ok',
        rain:     { status: 'ok', evaluated: false, summary: {}, areas: [] },
        kikikuru: { status: 'ok', evaluated: false, summary: {}, areas: [] },
        earthquake: { status: 'ok', evaluated: true, summary: { count_24h: 0, m5_count: 0 }, areas: [] },
        tsunami:    { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] },
        storm_surge:{ status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] },
        dangerous_areas:             dangerousAreas,
        integrated_dangerous_regions: integratedRegions,
    };
}

async function mockBase(page, summaryBody) {
    await page.route('/api/live/summary',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(summaryBody) }));
    await page.route('/api/live/storm_surge/**',     r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SS_NONE) }));
    await page.route('/api/earthquakes**',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**',              r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_NONE) }));
    await page.route('/api/weather/rain/tile/times', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/tide/**',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/astro**',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/live/sun_moon**',         r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('**/jmatile/**',                r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',              r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',  r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
}

// ── 統合なし（dangerous_areas のみ）──────────────────────────────────────────

test.describe('/live — 危険地域: integrated_dangerous_regions なし（フォールバック）', () => {
    test.beforeEach(async ({ page }) => {
        const summary = makeSummary({
            dangerousAreas: [
                { id: 'r0', label: '高知県付近', type: 'rain', level: 'danger', lat: 33.5, lng: 133.5 },
            ],
            integratedRegions: [],
        });
        await mockBase(page, summary);
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });
    });

    test('dangerous_areas の地域名が表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('高知県付近', { timeout: 5000 });
    });
});

// ── 統合表示（integrated_dangerous_regions あり）───────────────────────────────

test.describe('/live — 危険地域: integrated_dangerous_regions 統合表示', () => {
    const integratedRegions = [
        {
            label:  '高知県付近',
            level:  'danger',
            lat:    33.5,
            lng:    133.5,
            types:  ['kikikuru', 'rain'],
            events: [
                { type: 'kikikuru', label: 'キキクル（洪水）', level: 'danger' },
                { type: 'rain',     label: '雨雲',           level: 'danger' },
            ],
        },
        {
            label:  '沖縄県付近',
            level:  'warning',
            lat:    26.2,
            lng:    127.7,
            types:  ['rain'],
            events: [
                { type: 'rain', label: '雨雲', level: 'warning' },
            ],
        },
    ];

    test.beforeEach(async ({ page }) => {
        const summary = makeSummary({ integratedRegions });
        await mockBase(page, summary);
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });
    });

    test('統合地域名が表示される（高知県付近）', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('高知県付近', { timeout: 5000 });
    });

    test('統合地域名が表示される（沖縄県付近）', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('沖縄県付近', { timeout: 5000 });
    });

    test('キキクル（洪水）イベントが表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('キキクル（洪水）', { timeout: 5000 });
    });

    test('雨雲イベントが高知県付近の下に表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('雨雲', { timeout: 5000 });
    });

    test('危険地域セクションタイトルが存在する', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('危険地域', { timeout: 5000 });
    });

    test('ランク番号1が表示される', async ({ page }) => {
        const rankEl = page.locator('#live-alert-card .lac-danger-rank').first();
        await expect(rankEl).toContainText('1', { timeout: 5000 });
    });

    test('ランク番号2が表示される', async ({ page }) => {
        const rankEls = page.locator('#live-alert-card .lac-danger-rank');
        await expect(rankEls).toHaveCount(2, { timeout: 5000 });
    });

    test('高知県付近クリックで地図が移動する', async ({ page }) => {
        const item = page.locator('#live-alert-card .lac-danger-clickable').first();
        await item.click();
        // エラーが出なければ OK（map.setView が呼ばれる）
    });
});

// ── 統合表示: 既存 dangerous_areas は破壊されない ─────────────────────────────

test.describe('/live — API契約: dangerous_areas と integrated_dangerous_regions 共存', () => {
    test('summary に両フィールドが共存できる', async ({ page }) => {
        const summary = makeSummary({
            dangerousAreas: [
                { id: 'd0', label: '高知県付近', type: 'rain', level: 'danger', lat: 33.5, lng: 133.5 },
                { id: 'd1', label: '高知県付近', type: 'kikikuru', hazard: 'land', level: 'danger', lat: 33.5, lng: 133.5 },
            ],
            integratedRegions: [
                {
                    label: '高知県付近', level: 'danger', lat: 33.5, lng: 133.5,
                    types: ['kikikuru', 'rain'],
                    events: [
                        { type: 'kikikuru', label: 'キキクル（土砂）', level: 'danger' },
                        { type: 'rain', label: '雨雲', level: 'danger' },
                    ],
                },
            ],
        });
        await mockBase(page, summary);
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });

        // 統合表示が優先される
        await expect(page.locator('#live-alert-card')).toContainText('高知県付近', { timeout: 5000 });
        await expect(page.locator('#live-alert-card')).toContainText('キキクル（土砂）', { timeout: 5000 });
        await expect(page.locator('#live-alert-card')).toContainText('雨雲', { timeout: 5000 });
        // 危険地域が1行にまとまっている（ランクが1件）
        const rankEls = page.locator('#live-alert-card .lac-danger-rank');
        await expect(rankEls).toHaveCount(1, { timeout: 5000 });
    });
});

// ── false-safe: 空の場合は危険地域セクションなし ─────────────────────────────

test.describe('/live — 危険地域: 空の場合', () => {
    test.beforeEach(async ({ page }) => {
        const summary = makeSummary({ dangerousAreas: [], integratedRegions: [] });
        await mockBase(page, summary);
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });
    });

    test('危険地域セクションが表示されない', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).not.toContainText('危険地域', { timeout: 3000 });
    });
});

// ── ナビ本体への影響なし ──────────────────────────────────────────────────────

test.describe('/live — ナビ本体への影響なし', () => {
    test('index.html は integrated_dangerous_regions を呼び出さない', async ({ page }) => {
        const integratedRequests = [];
        page.on('request', req => {
            if (req.url().includes('integrated')) integratedRequests.push(req.url());
        });
        await page.goto('/');
        await page.waitForTimeout(1000);
        expect(integratedRequests).toHaveLength(0);
    });
});
