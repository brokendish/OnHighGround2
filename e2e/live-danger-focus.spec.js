'use strict';
/**
 * live-danger-focus.spec.js — 危険地域フォーカス機能確認 (Phase 5-D)
 *
 * backend 不要。API はすべてモックで受ける。
 * 完了条件:
 *   - 危険地域カードがクリック可能
 *   - 地図へ flyTo で移動できる
 *   - console.log が出る
 *   - ポップアップが表示される
 *   - 強調リングが表示される
 *   - false-safe (集計変更なし)
 *   - ナビ本体への影響なし
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const EQ_RESPONSE  = { count: 0, items: [] };
const TSUNAMI_NONE = { status: 'none', observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const SS_NONE      = { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] };
const RAIN_TIMES   = {
    basetime: '20260603000000',
    times: [{ offset_minutes: 0, validtime: '20260603000000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260603000000/none/20260603000000/surf/hrpns/{z}/{x}/{y}.png' }],
};

const INTEGRATED_REGIONS = [
    {
        label:  '高知県付近',
        level:  'danger',
        lat:    33.56,
        lng:    133.53,
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

function makeSummary({ integratedRegions = [] } = {}) {
    return {
        status:   'ok',
        rain:     { status: 'ok', evaluated: false, summary: {}, areas: [] },
        kikikuru: { status: 'ok', evaluated: false, summary: {}, areas: [] },
        earthquake: { status: 'ok', evaluated: true, summary: { count_24h: 0, m5_count: 0 }, areas: [] },
        tsunami:    { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] },
        storm_surge:{ status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] },
        dangerous_areas:              [],
        integrated_dangerous_regions: integratedRegions,
    };
}

async function mockBase(page, summaryBody) {
    await page.route('/api/live/summary',             r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(summaryBody) }));
    await page.route('/api/live/storm_surge/**',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SS_NONE) }));
    await page.route('/api/earthquakes**',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**',               r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_NONE) }));
    await page.route('/api/weather/rain/tile/times',  r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline',       r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/tide/**',             r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/astro**',             r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/live/sun_moon**',          r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('**/jmatile/**',                 r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',               r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',   r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
}

// ── クリック可能確認 ──────────────────────────────────────────────────────────

test.describe('/live — 危険地域フォーカス: クリック可能', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, makeSummary({ integratedRegions: INTEGRATED_REGIONS }));
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });
    });

    test('危険地域アイテムに lac-danger-clickable クラスがある', async ({ page }) => {
        const items = page.locator('#live-alert-card .lac-danger-clickable');
        await expect(items).not.toHaveCount(0, { timeout: 5000 });
    });

    test('クリック可能アイテムに data-lat がある', async ({ page }) => {
        const item = page.locator('#live-alert-card .lac-danger-clickable').first();
        const lat = await item.getAttribute('data-lat');
        expect(lat).not.toBeNull();
        expect(parseFloat(lat)).not.toBeNaN();
    });

    test('クリック可能アイテムに data-lng がある', async ({ page }) => {
        const item = page.locator('#live-alert-card .lac-danger-clickable').first();
        const lng = await item.getAttribute('data-lng');
        expect(lng).not.toBeNull();
        expect(parseFloat(lng)).not.toBeNaN();
    });

    test('クリック可能アイテムに data-label がある', async ({ page }) => {
        const item = page.locator('#live-alert-card .lac-danger-clickable').first();
        const label = await item.getAttribute('data-label');
        expect(label).toBe('高知県付近');
    });

    test('2番目のアイテムの data-label が沖縄県付近', async ({ page }) => {
        const item = page.locator('#live-alert-card .lac-danger-clickable').nth(1);
        const label = await item.getAttribute('data-label');
        expect(label).toBe('沖縄県付近');
    });
});

// ── 地図フォーカス ────────────────────────────────────────────────────────────

test.describe('/live — 危険地域フォーカス: 地図移動', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, makeSummary({ integratedRegions: INTEGRATED_REGIONS }));
        await page.goto('/live.html');
        await page.locator('#live-alert-card .lac-danger-clickable').first().waitFor({ timeout: 8000 });
    });

    test('クリックで page error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('pageerror', err => errors.push(err.message));
        await page.locator('#live-alert-card .lac-danger-clickable').first().click();
        await page.waitForTimeout(500);
        expect(errors).toHaveLength(0);
    });

    test('クリックで console.log が出力される（live danger region focus）', async ({ page }) => {
        const logs = [];
        page.on('console', msg => { if (msg.type() === 'log') logs.push(msg.text()); });
        await page.locator('#live-alert-card .lac-danger-clickable').first().click();
        await page.waitForTimeout(300);
        const focusLog = logs.find(l => l.startsWith('live danger region focus:'));
        expect(focusLog).toBeTruthy();
        expect(focusLog).toContain('高知県付近');
        expect(focusLog).toContain('lat=33.56');
        expect(focusLog).toContain('lng=133.53');
    });
});

// ── ポップアップ ──────────────────────────────────────────────────────────────

test.describe('/live — 危険地域フォーカス: ポップアップ', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, makeSummary({ integratedRegions: INTEGRATED_REGIONS }));
        await page.goto('/live.html');
        await page.locator('#live-alert-card .lac-danger-clickable').first().waitFor({ timeout: 8000 });
        await page.locator('#live-alert-card .lac-danger-clickable').first().click();
        await page.waitForTimeout(500);
    });

    test('ポップアップが表示される', async ({ page }) => {
        await expect(page.locator('.leaflet-popup')).toBeVisible({ timeout: 3000 });
    });

    test('ポップアップに地域名が含まれる', async ({ page }) => {
        await expect(page.locator('.leaflet-popup-content')).toContainText('高知県付近', { timeout: 3000 });
    });

    test('ポップアップにイベント名が含まれる', async ({ page }) => {
        await expect(page.locator('.leaflet-popup-content')).toContainText('キキクル（洪水）', { timeout: 3000 });
    });
});

// ── 強調リング ────────────────────────────────────────────────────────────────

test.describe('/live — 危険地域フォーカス: 強調リング', () => {
    test('クリックで Leaflet にレイヤー（CircleMarker）が追加される', async ({ page }) => {
        await mockBase(page, makeSummary({ integratedRegions: INTEGRATED_REGIONS }));
        await page.goto('/live.html');
        await page.locator('#live-alert-card .lac-danger-clickable').first().waitFor({ timeout: 8000 });

        const before = await page.evaluate(() => Object.keys(liveMap._layers).length);
        await page.locator('#live-alert-card .lac-danger-clickable').first().click();
        await page.waitForTimeout(300);
        const after = await page.evaluate(() => Object.keys(liveMap._layers).length);
        expect(after).toBeGreaterThan(before);
    });
});

// ── false-safe ────────────────────────────────────────────────────────────────

test.describe('/live — 危険地域フォーカス: false-safe', () => {
    test('クリックしても summary は再取得されない（集計変化なし）', async ({ page }) => {
        let summaryCount = 0;
        await mockBase(page, makeSummary({ integratedRegions: INTEGRATED_REGIONS }));
        await page.route('/api/live/summary', r => {
            summaryCount++;
            r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(makeSummary({ integratedRegions: INTEGRATED_REGIONS })) });
        });
        await page.goto('/live.html');
        await page.locator('#live-alert-card .lac-danger-clickable').first().waitFor({ timeout: 8000 });

        await page.locator('#live-alert-card .lac-danger-clickable').first().click();
        await page.waitForTimeout(500);

        expect(summaryCount).toBe(1);   // 起動時のみ
    });

    test('integrated_dangerous_regions のデータは変化しない', async ({ page }) => {
        await mockBase(page, makeSummary({ integratedRegions: INTEGRATED_REGIONS }));
        await page.goto('/live.html');
        await page.locator('#live-alert-card .lac-danger-clickable').first().waitFor({ timeout: 8000 });

        await page.locator('#live-alert-card .lac-danger-clickable').first().click();
        await page.waitForTimeout(500);

        // クリック後もランキング行数は変化しない（2件のまま）
        const items = page.locator('#live-alert-card .lac-danger-clickable');
        await expect(items).toHaveCount(2, { timeout: 3000 });
    });
});

// ── ナビ本体への影響なし ──────────────────────────────────────────────────────

test.describe('/live — 危険地域フォーカス: ナビ本体影響なし', () => {
    test('index.html は危険地域 API を自動呼び出しない', async ({ page }) => {
        let dangerApiCalled = false;
        await page.route('/api/live/summary', () => { dangerApiCalled = true; });
        await page.goto('/');
        await page.waitForTimeout(1000);
        expect(dangerApiCalled).toBe(false);
    });
});
