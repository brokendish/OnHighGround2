'use strict';
/**
 * live-kikikuru.spec.js — キキクル種別分割 UI テスト
 *
 * 親トグル ON/OFF + 土砂・浸水・洪水の個別サブトグル動作を検証。
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const KIKIKURU_TIME = {
    basetime:  '20260603120000',
    validtime: '20260603120000',
    member:    'immed0',
    elements:  ['inund', 'land', 'flood', 'flood_mesh'],
};

const EQ_RESPONSE    = { count: 0, items: [] };
const TSUNAMI_NONE   = { observed_at: null, areas: [], message: '' };
const STORM_SURGE_NONE = {
    status: 'ok', evaluated: true,
    summary: { active: false, warning_area_count: 0 },
    areas: [],
};
const RAIN_TIMES = {
    basetime: '20260603120000',
    times: [
        { offset_minutes: 0, validtime: '20260603120000',
          tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260603120000/none/20260603120000/surf/hrpns/{z}/{x}/{y}.png' },
    ],
};
const SUN_MOON = {
    location: '東京', date: '2026-06-03',
    sunrise: '04:25', sunset: '19:01',
    moonrise: '10:00', moonset: '22:00',
    moon_phase: 5.0, moon_phase_name: '上弦',
};

async function mockTraffic(page) {
    await page.route('/data/municipality_coords.json', r => r.fulfill({
        status: 200, contentType: 'application/json', body: '{}',
    }));
    await page.route('/api/live/weather/jma/prefectures**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unavailable', source: 'Open-Meteo Forecast', forecast_time: null, fetched_at: null, cache_status: 'unavailable', items: [] }) }));
    await page.route('/api/live/sun-moon', r => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(SUN_MOON),
    }));
    await page.route('/api/earthquakes**', r => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE),
    }));
    await page.route('/api/live/storm_surge/**', r => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(STORM_SURGE_NONE),
    }));
    await page.route('/api/tsunami/**', r => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_NONE),
    }));
    await page.route('/api/weather/rain/tile/times', r => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES),
    }));
    await page.route('/api/live/rain/timeline', r => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES),
    }));
    await page.route('**/jmatile/**', r => {
        if (r.request().url().includes('targetTimes.json')) {
            return r.fulfill({
                status: 200, contentType: 'application/json',
                body: JSON.stringify([KIKIKURU_TIME]),
            });
        }
        return r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG });
    });
    await page.route('**/jma.go.jp/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
    await page.route('**/basemaps.cartocdn.com/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
}

test.describe('キキクル種別分割 UI', () => {
    test.beforeEach(async ({ page }) => {
        await mockTraffic(page);
        await page.goto('/live.html');
    });

    // ── 初期状態 ────────────────────────────────────────────────────────────────

    test('親トグル #toggle-kikikuru が存在する', async ({ page }) => {
        await expect(page.locator('#toggle-kikikuru')).toBeAttached();
    });

    test('親トグルは初期状態で unchecked', async ({ page }) => {
        await expect(page.locator('#toggle-kikikuru')).not.toBeChecked();
    });

    test('サブパネル #kikikuru-sub は初期状態で非表示', async ({ page }) => {
        await expect(page.locator('#kikikuru-sub')).toBeHidden();
    });

    test('土砂サブトグル #toggle-kikikuru-land が存在する', async ({ page }) => {
        await expect(page.locator('#toggle-kikikuru-land')).toBeAttached();
    });

    test('浸水サブトグル #toggle-kikikuru-inund が存在する', async ({ page }) => {
        await expect(page.locator('#toggle-kikikuru-inund')).toBeAttached();
    });

    test('洪水サブトグル #toggle-kikikuru-flood が存在する', async ({ page }) => {
        await expect(page.locator('#toggle-kikikuru-flood')).toBeAttached();
    });

    // ── 親 ON → サブパネル表示 ──────────────────────────────────────────────────

    test('親トグルを ON にするとサブパネルが表示される', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await expect(page.locator('#kikikuru-sub')).toBeVisible();
    });

    test('親 ON 後にサブトグル 土砂 が checked になっている', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await expect(page.locator('#toggle-kikikuru-land')).toBeChecked();
    });

    test('親 ON 後にサブトグル 浸水 が checked になっている', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await expect(page.locator('#toggle-kikikuru-inund')).toBeChecked();
    });

    test('親 ON 後にサブトグル 洪水 が checked になっている', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await expect(page.locator('#toggle-kikikuru-flood')).toBeChecked();
    });

    // ── 親 OFF → サブパネル非表示 ───────────────────────────────────────────────

    test('親 ON → OFF でサブパネルが再び非表示になる', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await expect(page.locator('#kikikuru-sub')).toBeVisible();
        await page.locator('#toggle-kikikuru').uncheck();
        await expect(page.locator('#kikikuru-sub')).toBeHidden();
    });

    // ── サブトグル個別制御 ───────────────────────────────────────────────────────

    test('親 ON 後に 土砂 サブトグルを OFF にできる', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await page.locator('#toggle-kikikuru-land').uncheck();
        await expect(page.locator('#toggle-kikikuru-land')).not.toBeChecked();
        // 他サブトグルは影響を受けない
        await expect(page.locator('#toggle-kikikuru-inund')).toBeChecked();
        await expect(page.locator('#toggle-kikikuru-flood')).toBeChecked();
    });

    test('親 ON 後に 浸水 サブトグルを OFF にできる', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await page.locator('#toggle-kikikuru-inund').uncheck();
        await expect(page.locator('#toggle-kikikuru-inund')).not.toBeChecked();
        await expect(page.locator('#toggle-kikikuru-land')).toBeChecked();
        await expect(page.locator('#toggle-kikikuru-flood')).toBeChecked();
    });

    test('親 ON 後に 洪水 サブトグルを OFF にできる', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await page.locator('#toggle-kikikuru-flood').uncheck();
        await expect(page.locator('#toggle-kikikuru-flood')).not.toBeChecked();
        await expect(page.locator('#toggle-kikikuru-land')).toBeChecked();
        await expect(page.locator('#toggle-kikikuru-inund')).toBeChecked();
    });

    test('全サブトグルを OFF にしても親は ON のまま', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await page.locator('#toggle-kikikuru-land').uncheck();
        await page.locator('#toggle-kikikuru-inund').uncheck();
        await page.locator('#toggle-kikikuru-flood').uncheck();
        await expect(page.locator('#toggle-kikikuru')).toBeChecked();
        await expect(page.locator('#kikikuru-sub')).toBeVisible();
    });

    // ── ラベルテキスト確認 ────────────────────────────────────────────────────────

    test('サブパネルに "土砂災害" ラベルが存在する', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await expect(page.locator('#kikikuru-sub')).toContainText('土砂災害');
    });

    test('サブパネルに "浸水害" ラベルが存在する', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await expect(page.locator('#kikikuru-sub')).toContainText('浸水害');
    });

    test('サブパネルに "洪水害" ラベルが存在する', async ({ page }) => {
        await page.locator('#toggle-kikikuru').check();
        await expect(page.locator('#kikikuru-sub')).toContainText('洪水害');
    });
});
