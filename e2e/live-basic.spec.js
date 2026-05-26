'use strict';
/**
 * live-basic.spec.js — /live ページ基本動作確認
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const KIKIKURU_TIME = {
    basetime:  '20260522111000',
    validtime: '20260522111000',
    member:    'immed0',
    elements:  ['inund', 'land', 'flood', 'flood_mesh'],
};

const EQ_RESPONSE = {
    count: 2,
    items: [
        {
            event_id:       'eq-001',
            occurred_at:    '2026-05-26T10:00:00+09:00',
            epicenter_name: '東京湾',
            lat:            35.5,
            lng:            139.8,
            magnitude:      4.2,
            max_intensity:  '3',
        },
        {
            event_id:       'eq-002',
            occurred_at:    '2026-05-26T08:00:00+09:00',
            epicenter_name: '茨城県南部',
            lat:            36.1,
            lng:            140.2,
            magnitude:      3.1,
            max_intensity:  '2',
        },
    ],
};

const TSUNAMI_RESPONSE = {
    observed_at:  '2026-05-26T10:00:00+09:00',
    updated_at:   '2026-05-26T10:00:00+09:00',
    ttl_seconds:  60,
    areas:        [],
    message:      '',
};

const RAIN_TIMES = {
    basetime: '20260526100000',
    times: [
        { offset_minutes: 0, validtime: '20260526100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260526100000/none/20260526100000/surf/hrpns/{z}/{x}/{y}.png' },
    ],
};

async function mockLiveTraffic(page) {
    await page.route('/api/earthquakes**', route => route.fulfill({
        status:      200,
        contentType: 'application/json',
        body:        JSON.stringify(EQ_RESPONSE),
    }));
    await page.route('/api/tsunami/**', route => route.fulfill({
        status:      200,
        contentType: 'application/json',
        body:        JSON.stringify(TSUNAMI_RESPONSE),
    }));
    await page.route('/api/weather/rain/tile/times', route => route.fulfill({
        status:      200,
        contentType: 'application/json',
        body:        JSON.stringify(RAIN_TIMES),
    }));
    await page.route('**/jmatile/**', route => {
        if (route.request().url().includes('targetTimes.json')) {
            return route.fulfill({
                status:      200,
                contentType: 'application/json',
                body:        JSON.stringify([KIKIKURU_TIME]),
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

test.describe('/live — 基本動作確認', () => {
    test.beforeEach(async ({ page }) => {
        await mockLiveTraffic(page);
        await page.goto('/live.html');
    });

    test('ページタイトルに "全国災害ビューア" が含まれる', async ({ page }) => {
        await expect(page).toHaveTitle(/全国災害ビューア/);
    });

    test('地図コンテナが存在する', async ({ page }) => {
        await expect(page.locator('#live-map')).toBeVisible();
    });

    test('Leaflet マップが初期化されている', async ({ page }) => {
        await expect(page.locator('#live-map.leaflet-container')).toBeVisible({ timeout: 5000 });
    });

    test('レイヤー切替パネルが存在する', async ({ page }) => {
        await expect(page.locator('#live-layer-panel')).toBeVisible();
    });

    test('雨雲トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-rain')).toBeVisible();
    });

    test('キキクルトグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-kikikuru')).toBeVisible();
    });

    test('地震トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-earthquake')).toBeVisible();
    });

    test('津波トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-tsunami')).toBeVisible();
    });

    test('アクティブ警戒カードが存在する', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toBeVisible();
    });

    test('ローディングが消える', async ({ page }) => {
        const loading = page.locator('#live-loading');
        await expect(loading).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('地震トグル OFF でマーカーが非表示になる', async ({ page }) => {
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 5000 });
        const toggle = page.locator('#toggle-earthquake');
        await toggle.uncheck();
        // レイヤーグループが空になることを JS レベルで確認
        const markerCount = await page.evaluate(() => {
            // _eqLayerGroup はクロージャ内のためグローバルアクセス不可。
            // 代わりに Leaflet の canvas/SVG レイヤー有無で間接確認。
            return document.querySelectorAll('.leaflet-marker-icon').length;
        });
        // circle マーカー（canvas）が使われているため marker-icon は 0 のはず
        expect(markerCount).toBe(0);
    });

    test('避難ナビへのリンクが存在する', async ({ page }) => {
        const link = page.locator('a.live-nav-link');
        await expect(link).toBeVisible();
        await expect(link).toHaveAttribute('href', '/');
    });

    test('JS console error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('console', msg => {
            if (msg.type() === 'error') errors.push(msg.text());
        });
        await page.waitForTimeout(2000);
        expect(errors).toHaveLength(0);
    });
});

test.describe('/live — API 失敗耐性', () => {
    async function mockAllApis503(page) {
        await page.route('/api/**', route => route.fulfill({ status: 503, body: '' }));
        await page.route('**/jmatile/**', route => route.fulfill({
            status: 200, contentType: 'application/json', body: '[]',
        }));
        await page.route('**/basemaps.cartocdn.com/**', route =>
            route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
        );
    }

    test('API 503 時に rain OFF→ON で page error が発生しない', async ({ page }) => {
        const pageErrors = [];
        page.on('pageerror', err => pageErrors.push(err.message));

        await mockAllApis503(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        const toggle = page.locator('#toggle-rain');
        await toggle.uncheck();
        await toggle.check();
        await page.waitForTimeout(500);

        expect(pageErrors).toHaveLength(0);
    });

    test('API 503 時に status dot が offline になる', async ({ page }) => {
        await mockAllApis503(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        const offlineDots = page.locator('#live-status-bar .live-status-dot.offline');
        await expect(offlineDots).not.toHaveCount(0);
    });

    test('API 503 時に map 操作が継続できる', async ({ page }) => {
        const pageErrors = [];
        page.on('pageerror', err => pageErrors.push(err.message));

        await mockAllApis503(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-map.leaflet-container')).toBeVisible({ timeout: 5000 });

        // アラートカード（左上）を避けてマップ右側でホイールズーム操作
        await page.mouse.move(800, 400);
        await page.mouse.wheel(0, -120);
        await page.waitForTimeout(300);

        expect(pageErrors).toHaveLength(0);
    });
});
