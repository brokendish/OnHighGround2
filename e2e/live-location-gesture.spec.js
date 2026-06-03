'use strict';
/**
 * live-location-gesture.spec.js
 *   現在地パルス表示 / ダブルタップ上下スワイプズーム の E2E 確認
 *
 * - 現在地: Playwright config の geolocation mock (35.6415, 139.7905) を使用
 * - ジェスチャー: TouchEvent を page.evaluate で発火して zoom 変化を確認
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const KIKIKURU_TIME = {
    basetime: '20260602120000', validtime: '20260602120000', member: 'immed0',
};
const RAIN_TIMES = {
    basetime: '20260602120000',
    times: [{ offset_minutes: 0, validtime: '20260602120000',
              tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260602120000/none/20260602120000/surf/hrpns/{z}/{x}/{y}.png' }],
};
const EQ_RESPONSE  = { count: 0, items: [] };
const TSUNAMI_RESPONSE = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const SUN_MOON_RESPONSE = {
    location: '東京', date: '2026-06-02',
    sunrise: '04:26', sunset: '18:51',
    moonrise: '15:42', moonset: '05:18',
    moon_phase: 15.8, moon_phase_name: '満月',
};
const LIVE_SUMMARY = {
    updated_at: '2026-06-02T12:00:00+09:00', status: 'ok',
    rain:      { status: 'ok', evaluated: false, reason: 'tile_only', summary: { strong_rain_detected: null }, areas: [] },
    kikikuru:  { status: 'ok', evaluated: false, reason: 'tile_only', summary: { danger_detected: null },     areas: [] },
    earthquake:{ status: 'ok', evaluated: true, summary: { count_24h: 0, m5_count: 0, m6_count: 0 }, areas: [] },
    tsunami:   { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 },    areas: [] },
    dangerous_areas: [],
};

async function mockAll(page) {
    await page.route('/data/municipality_coords.json', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/live/summary',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('/api/live/sun-moon',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUN_MOON_RESPONSE) }));
    await page.route('/api/live/tide/stations',      r => r.fulfill({ status: 200, contentType: 'application/json', body: '{"count":0,"stations":[]}' }));
    await page.route('/api/earthquakes**',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**',              r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_RESPONSE) }));
    await page.route('/api/weather/rain/tile/times', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('**/jmatile/**', r => {
        if (r.request().url().includes('targetTimes.json'))
            return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([KIKIKURU_TIME]) });
        return r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG });
    });
    await page.route('**/jma.go.jp/**',             r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
}

// ── 現在地パルス ──────────────────────────────────────────────────────────────

test.describe('/live — 現在地パルス表示', () => {

    test.beforeEach(async ({ page }) => {
        await mockAll(page);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(800);
    });

    test('現在地ボタン（.live-locate-btn）が地図上に表示される', async ({ page }) => {
        await expect(page.locator('.live-locate-btn')).toBeVisible({ timeout: 3000 });
    });

    test('現在地パルスマーカー（.live-location-dot）が表示される', async ({ page }) => {
        // Playwright config の geolocation mock (35.6415, 139.7905) で watchPosition が発火する
        await expect(page.locator('.live-location-dot')).toBeVisible({ timeout: 5000 });
    });

    test('現在地ボタンクリックで地図が現在地付近に移動する', async ({ page }) => {
        await page.locator('.live-locate-btn').click();
        await page.waitForTimeout(400);

        const center = await page.evaluate(() => {
            const c = liveMap.getCenter();
            return { lat: c.lat, lng: c.lng };
        });
        // mock 座標 35.6415, 139.7905 に近い位置
        expect(Math.abs(center.lat - 35.6415)).toBeLessThan(1.0);
        expect(Math.abs(center.lng - 139.7905)).toBeLessThan(1.0);
    });

    test('現在地表示中に console.error / page error が発生しない', async ({ page }) => {
        const errors = [];
        const pageErrors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        page.on('pageerror', err => pageErrors.push(err.message));

        await page.waitForTimeout(1000);
        expect(errors).toHaveLength(0);
        expect(pageErrors).toHaveLength(0);
    });

});

// ── ダブルタップ上下スワイプ ──────────────────────────────────────────────────

test.describe('/live — ダブルタップ上下スワイプズーム', () => {

    test.beforeEach(async ({ page }) => {
        await mockAll(page);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(500);
    });

    // ジェスチャーシミュレーション: 1回の evaluate 内で setTimeout を使い
    // ダブルタップ間隔 (100ms) を確実に 300ms 以内に収める
    function simulateDragZoom(page, deltaY) {
        return page.evaluate((dy) => new Promise((resolve) => {
            const el = document.getElementById('live-map');
            const cx = el.clientWidth  / 2;
            const cy = el.clientHeight / 2;

            function mkTouch(id, x, y) {
                return new Touch({ identifier: id, target: el,
                    clientX: x, clientY: y, pageX: x, pageY: y, screenX: x, screenY: y });
            }
            function fire(type, touches, changed) {
                el.dispatchEvent(new TouchEvent(type,
                    { touches, changedTouches: changed, bubbles: true, cancelable: true }));
            }

            // 1 回目タップ
            const t1 = mkTouch(1, cx, cy);
            fire('touchstart', [t1], [t1]);
            fire('touchend',   [],   [t1]);

            // 100ms 後に 2 回目タップ＋ドラッグ（TAP_MS=300ms 以内）
            setTimeout(() => {
                const t2  = mkTouch(2, cx, cy);
                const t2m = mkTouch(2, cx, cy + dy);
                fire('touchstart', [t2],  [t2]);
                fire('touchmove',  [t2m], [t2m]);
                fire('touchmove',  [t2m], [t2m]);
                fire('touchend',   [],    [t2m]);
                resolve();
            }, 100);
        }), deltaY);
    }

    test('ダブルタップ後に上スワイプするとズームインする', async ({ page }) => {
        const initialZoom = await page.evaluate(() => liveMap.getZoom());

        await simulateDragZoom(page, -80); // 上方向 80px → ズームイン

        await page.waitForTimeout(200);
        const newZoom = await page.evaluate(() => liveMap.getZoom());
        expect(newZoom).toBeGreaterThan(initialZoom);
    });

    test('ダブルタップ後に下スワイプするとズームアウトする', async ({ page }) => {
        await page.evaluate(() => liveMap.setZoom(7, { animate: false }));
        await page.waitForTimeout(200);
        const initialZoom = await page.evaluate(() => liveMap.getZoom());

        await simulateDragZoom(page, 160); // 下方向 160px → 2ズームアウト

        await page.waitForTimeout(200);
        const newZoom = await page.evaluate(() => liveMap.getZoom());
        expect(newZoom).toBeLessThan(initialZoom);
    });

    test('ジェスチャー後に console.error / page error が発生しない', async ({ page }) => {
        const errors = [];
        const pageErrors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        page.on('pageerror', err => pageErrors.push(err.message));

        await page.waitForTimeout(500);
        expect(errors).toHaveLength(0);
        expect(pageErrors).toHaveLength(0);
    });

    test('ナビ本体 index.html にジェスチャーモジュールが混入しない', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);
        const hasGesture = await page.evaluate(() =>
            typeof window._liveGestureLoaded !== 'undefined' ||
            document.querySelector('.live-locate-btn') !== null,
        );
        expect(hasGesture).toBe(false);
    });

});
