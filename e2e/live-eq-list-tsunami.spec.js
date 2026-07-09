'use strict';
/**
 * live-eq-list-tsunami.spec.js — 津波警報中の地震リスト展開確認
 *
 * 津波警報発令中（＝ M5以上地震が存在する状況）でも
 * 地震リストを展開・操作できることを確認する。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

// M5以上の地震3件
const EQ_M5_MULTI = {
    count: 3,
    items: [
        {
            event_id:       'eq-m5-001',
            occurred_at:    '2026-06-09T10:00:00+09:00',
            epicenter_name: '岩手県沖',
            lat:            39.5,
            lng:            142.0,
            magnitude:      6.2,
            max_intensity:  '5弱',
        },
        {
            event_id:       'eq-m5-002',
            occurred_at:    '2026-06-09T09:30:00+09:00',
            epicenter_name: '宮城県沖',
            lat:            38.3,
            lng:            141.8,
            magnitude:      5.5,
            max_intensity:  '4',
        },
        {
            event_id:       'eq-m5-003',
            occurred_at:    '2026-06-09T09:00:00+09:00',
            epicenter_name: '福島県沖',
            lat:            37.4,
            lng:            141.2,
            magnitude:      5.1,
            max_intensity:  '3',
        },
    ],
};

// 活発な津波警報（岩手県沖地震に連動した想定）
const TSUNAMI_ACTIVE = {
    source:      'mock',
    status:      'active',
    observed_at: '2026-06-09T10:01:00+09:00',
    updated_at:  '2026-06-09T10:01:00+09:00',
    ttl_seconds: 60,
    areas: [
        {
            code:             null,
            name:             '岩手県',
            level:            'warning',
            level_label:      '津波警報',
            expected_height:  '1m',
            arrival_time:     null,
            is_target:        true,
        },
        {
            code:             null,
            name:             '宮城県',
            level:            'advisory',
            level_label:      '津波注意報',
            expected_height:  '0.5m',
            arrival_time:     null,
            is_target:        true,
        },
    ],
    message: '津波警報が発表されています。',
};

// summary API: 津波警報あり + M5地震3件
const SUMMARY_WITH_TSUNAMI_AND_M5 = {
    updated_at: '2026-06-09T10:02:00+09:00',
    status: 'ok',
    rain: {
        status: 'ok', evaluated: false,
        summary: { strong_rain_detected: null },
        areas: [],
    },
    kikikuru: {
        status: 'ok', evaluated: false,
        summary: { danger_detected: null },
        areas: [],
    },
    earthquake: {
        status: 'ok', evaluated: true,
        summary: { count_24h: 3, m5_count: 3, m6_count: 1 },
        areas: [],
    },
    tsunami: {
        status: 'ok', evaluated: true,
        summary: { active: true, warning_area_count: 1 },
        areas: [
            { name: '岩手県', level: 'warning',  level_label: '津波警報' },
            { name: '宮城県', level: 'advisory', level_label: '津波注意報' },
        ],
    },
    storm_surge: {
        status: 'ok', evaluated: true,
        summary: { active: false },
        areas: [],
    },
    dangerous_areas: [
        { id: 'eq-岩手県沖', type: 'earthquake', level: 'danger', label: '岩手県沖', lat: 39.5, lng: 142.0 },
        { id: 'eq-宮城県沖', type: 'earthquake', level: 'warning', label: '宮城県沖', lat: 38.3, lng: 141.8 },
    ],
    integrated_dangerous_regions: [],
};

const STORM_SURGE_NONE = {
    status: 'ok', evaluated: true,
    summary: { active: false, warning_area_count: 0 },
    areas: [],
};

const SUN_MOON = {
    location: '東京', date: '2026-06-09',
    sunrise: '04:28', sunset: '19:01',
    moonrise: '08:14', moonset: '22:33',
    moon_phase: 2.1, moon_phase_name: '三日月',
};

const RAIN_TIMES = {
    basetime: '20260609100000',
    times: [
        {
            offset_minutes: 0,
            validtime: '20260609100000',
            tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260609100000/none/20260609100000/surf/hrpns/{z}/{x}/{y}.png',
        },
    ],
};

async function mockLiveWithTsunami(page) {
    await page.route('/data/municipality_coords.json', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
    );
    await page.route('/api/live/weather/jma/prefectures**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unavailable', source: 'Open-Meteo Forecast', forecast_time: null, fetched_at: null, cache_status: 'unavailable', items: [] }) }));
    await page.route('/api/live/sun-moon', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUN_MOON) }),
    );
    await page.route('/api/earthquakes**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_M5_MULTI) }),
    );
    await page.route('/api/tsunami/**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_ACTIVE) }),
    );
    await page.route('/api/live/storm_surge/**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STORM_SURGE_NONE) }),
    );
    await page.route('/api/live/summary', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUMMARY_WITH_TSUNAMI_AND_M5) }),
    );
    await page.route('/api/weather/rain/tile/times', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }),
    );
    await page.route('/api/live/rain/timeline', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }),
    );
    await page.route('**/jmatile/**', route => {
        if (route.request().url().includes('targetTimes.json')) {
            return route.fulfill({
                status: 200, contentType: 'application/json',
                body: JSON.stringify([{ basetime: '20260609100000', validtime: '20260609100000', member: 'immed0', elements: ['land'] }]),
            });
        }
        return route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG });
    });
    await page.route('**/jma.go.jp/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
    await page.route('**/basemaps.cartocdn.com/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
}

test.describe('/live — 津波警報中の地震リスト展開', () => {

    test.beforeEach(async ({ page }) => {
        await mockLiveWithTsunami(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('津波警報中でも警戒カードが表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toBeVisible();
    });

    test('津波警報バッジが表示される', async ({ page }) => {
        const card = page.locator('#live-alert-card');
        await expect(card).toContainText('津波警報');
    });

    test('M5以上バッジが警戒カードに表示される', async ({ page }) => {
        const card = page.locator('#live-alert-card');
        await expect(card).toContainText('M5以上');
        await expect(card).toContainText('3件');
    });

    test('M5以上の地震代表マーカーがcanvasに描画される', async ({ page }) => {
        await expect
            .poll(() => page.evaluate(() => window.liveLayers?.earthquake?.getData?.()?.length ?? 0))
            .toBe(3);

        const canvasStats = await page.evaluate(() => {
            const canvases = Array.from(document.querySelectorAll('.leaflet-overlay-pane canvas'));
            let redPixels = 0;
            for (const canvas of canvases) {
                const ctx = canvas.getContext('2d');
                const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                for (let i = 0; i < data.length; i += 4) {
                    const r = data[i];
                    const g = data[i + 1];
                    const b = data[i + 2];
                    const a = data[i + 3];
                    if (a > 0 && r > 180 && g < 90 && b < 90) redPixels++;
                }
            }
            return { canvasCount: canvases.length, redPixels };
        });

        expect(canvasStats.canvasCount).toBeGreaterThan(0);
        expect(canvasStats.redPixels).toBeGreaterThan(0);
    });

    test('M5以上バッジに展開矢印が表示される', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 3000 });
        await expect(toggle.locator('.lac-expand-arrow')).toBeVisible();
    });

    test('M5以上バッジをクリックすると地震リストが展開される', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 3000 });

        // 初期状態: リストは非表示
        const listWrap = page.locator('.lac-eq-list-wrap');
        await expect(listWrap).toBeHidden();

        // クリックで展開
        await toggle.click();
        await expect(listWrap).toBeVisible({ timeout: 2000 });
    });

    test('展開した地震リストにM5以上の地震が含まれる', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 3000 });
        await toggle.click();

        const listWrap = page.locator('.lac-eq-list-wrap');
        await expect(listWrap).toBeVisible({ timeout: 2000 });
        await expect(listWrap).toContainText('岩手県沖');
        await expect(listWrap).toContainText('宮城県沖');
        await expect(listWrap).toContainText('福島県沖');
    });

    test('展開した地震リスト項目をクリックするとポップアップが表示される', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 3000 });
        await toggle.click();

        const listWrap = page.locator('.lac-eq-list-wrap');
        await expect(listWrap).toBeVisible({ timeout: 2000 });

        const eqItem = listWrap.locator('.lac-eq-clickable').first();
        await expect(eqItem).toBeVisible();
        await eqItem.click();

        // Leaflet popup が表示される
        await expect(page.locator('.leaflet-popup')).toBeVisible({ timeout: 3000 });
    });

    test('地震リスト展開後に折りたたみできる', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 3000 });

        // 展開
        await toggle.click();
        await expect(page.locator('.lac-eq-list-wrap')).toBeVisible({ timeout: 2000 });

        // 折りたたみ
        await toggle.click();
        await expect(page.locator('.lac-eq-list-wrap')).toBeHidden({ timeout: 2000 });
    });

    test('津波警報カードは地震リスト展開後も表示継続する', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 3000 });
        await toggle.click();
        await expect(page.locator('.lac-eq-list-wrap')).toBeVisible({ timeout: 2000 });

        // 津波情報行が表示されたまま
        await expect(page.locator('#live-alert-card')).toContainText('津波警報');
    });

    test('console error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('console', msg => {
            if (msg.type() === 'error') errors.push(msg.text());
        });
        const pageErrors = [];
        page.on('pageerror', err => pageErrors.push(err.message));

        await page.reload();
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 3000 });
        await toggle.click();
        await expect(page.locator('.lac-eq-list-wrap')).toBeVisible({ timeout: 2000 });

        expect(pageErrors).toHaveLength(0);
    });

});

test.describe('/live — 津波警報中の地震リスト展開（モバイル）', () => {

    test.beforeEach(async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 520 });
        await mockLiveWithTsunami(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('スマホ幅でも地震リストを展開・スクロール・項目クリックでき、津波カードも維持される', async ({ page }) => {
        const card = page.locator('#live-alert-card');
        await expect(card).toBeVisible({ timeout: 5000 });
        await expect(card).toContainText('津波警報');

        await page.locator('.sheet-handle').click();
        await expect(card).toHaveClass(/is-expanded/);

        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 3000 });
        await toggle.click();

        const listWrap = page.locator('.lac-eq-list-wrap');
        await expect(listWrap).toBeVisible({ timeout: 2000 });
        await expect(listWrap.locator('.lac-eq-item')).toHaveCount(3);

        const scrollState = await page.evaluate(() => {
            const scroll = document.querySelector('#live-alert-card .sheet-scroll');
            const before = scroll ? scroll.scrollTop : 0;
            if (scroll) scroll.scrollTop = scroll.scrollHeight;
            return {
                before,
                after: scroll ? scroll.scrollTop : 0,
                scrollHeight: scroll ? scroll.scrollHeight : 0,
                clientHeight: scroll ? scroll.clientHeight : 0,
            };
        });
        expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight);
        expect(scrollState.after).toBeGreaterThanOrEqual(scrollState.before);

        await listWrap.locator('.lac-eq-clickable').first().click();
        await expect(page.locator('.leaflet-popup')).toBeVisible({ timeout: 3000 });
        await expect(card).toContainText('津波警報');

        await page.locator('.sheet-close-btn').click();
        await expect(card).toHaveClass(/is-sheet-closed/);
        await expect(page.locator('#live-sheet-restore')).toBeVisible();
    });

});

test.describe('/live — 津波警報中フォールバックパス（summary API 失敗時）', () => {

    test.beforeEach(async ({ page }) => {
        await mockLiveWithTsunami(page);
        // summary API を 503 にしてフォールバックパスを強制
        await page.route('/api/live/summary', route => route.fulfill({ status: 503, body: '' }));
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('フォールバックパスでも M5以上バッジが表示される', async ({ page }) => {
        const card = page.locator('#live-alert-card');
        await expect(card).toContainText('M5以上', { timeout: 5000 });
    });

    test('フォールバックパスでも地震リスト展開ができる', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 5000 });

        await toggle.click();
        await expect(page.locator('.lac-eq-list-wrap')).toBeVisible({ timeout: 2000 });
        await expect(page.locator('.lac-eq-list-wrap')).toContainText('岩手県沖');
    });

});
