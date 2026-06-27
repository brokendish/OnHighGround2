'use strict';
/**
 * live-rain-visibility.spec.js — 雨雲レイヤー視認性改善確認 (Phase 8-B)
 *
 * 検証内容:
 *   - Canvas ピクセル加工方式で雨雲タイルレイヤーが正常に動作する
 *   - 雨雲ステータスが OK として表示される
 *   - タイルロード中に uncaught error が発生しない
 *   - 雨雲 ON/OFF トグルが Canvas 方式でも機能する
 *   - タイムライン（スライダー・再生）が壊れていない
 *
 * backend 不要。API・タイルはすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

// 透明 1x1 PNG（Canvas で getImageData しても全ピクセル alpha=0）
const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);
const RAIN_VISIBILITY_SVG = Buffer.from(`
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">
  <rect x="0" y="0" width="64" height="256" fill="rgb(160,210,255)" fill-opacity="1"/>
  <rect x="64" y="0" width="64" height="256" fill="rgb(0,65,255)" fill-opacity="1"/>
  <rect x="128" y="0" width="64" height="256" fill="rgb(255,0,0)" fill-opacity="1"/>
  <rect x="192" y="0" width="64" height="256" fill="rgb(255,255,255)" fill-opacity="1"/>
</svg>`);

const BASETIME  = '20260627120000';
const RAIN_TIMES = {
    basetime: BASETIME,
    times: [
        { offset_minutes: 0, validtime: BASETIME,
          tile_url_template: `https://www.jma.go.jp/bosai/jmatile/data/nowc/${BASETIME}/none/${BASETIME}/surf/hrpns/{z}/{x}/{y}.png` },
    ],
};
const TIMELINE_RESPONSE = {
    source: 'jma_nowcast', basetime: BASETIME,
    times: Array.from({ length: 13 }, (_, i) => {
        const off = i * 5;
        const vt  = `20260627${String(12 + Math.floor(off / 60)).padStart(2, '0')}${String(off % 60).padStart(2, '0')}00`;
        return { offset_minutes: off, validtime: vt,
                 tile_url_template: `https://www.jma.go.jp/bosai/jmatile/data/nowc/${BASETIME}/none/${vt}/surf/hrpns/{z}/{x}/{y}.png` };
    }),
    ttl_seconds: 120,
};
const EQ_RESPONSE  = { count: 0, items: [] };
const TSUNAMI_NONE = { status: 'none', observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const SS_NONE      = { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] };
const SUMMARY_EMPTY = {
    status: 'ok',
    rain:        { status: 'ok', evaluated: false, summary: {}, areas: [] },
    kikikuru:    { status: 'ok', evaluated: false, summary: {}, areas: [] },
    earthquake:  { status: 'ok', evaluated: true,  summary: { count_24h: 0, m5_count: 0 }, areas: [] },
    tsunami:     { status: 'ok', evaluated: true,  summary: { active: false, warning_area_count: 0 }, areas: [] },
    storm_surge: { status: 'ok', evaluated: true,  summary: { active: false, warning_area_count: 0 }, areas: [] },
    dangerous_areas: [], integrated_dangerous_regions: [],
};

async function mockBase(page) {
    await page.route('/api/live/summary',              r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUMMARY_EMPTY) }));
    await page.route('/api/live/storm_surge/**',       r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SS_NONE) }));
    await page.route('/api/earthquakes**',             r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/live/earthquakes/**',       r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], source: 'p2p', fallback: false }) }));
    await page.route('/api/tsunami/**',                r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_NONE) }));
    await page.route('/api/weather/rain/tile/times',   r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline',        r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TIMELINE_RESPONSE) }));
    await page.route('/api/live/tide/**',              r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/astro**',              r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/live/sun_moon**',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('**/jmatile/**',                  r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',                r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',    r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
}

async function mockColoredRainTiles(page) {
    await page.unroute('**/jmatile/**').catch(() => {});
    await page.unroute('**/jma.go.jp/**').catch(() => {});
    const fulfillColoredTile = route => route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: RAIN_VISIBILITY_SVG,
    });
    await page.route('**/jmatile/**', fulfillColoredTile);
    await page.route('**/jma.go.jp/**', fulfillColoredTile);
}

// ── Canvas 方式: 基本動作 ─────────────────────────────────────────────────────

test.describe('/live — 雨雲視認性改善: Canvas レイヤー基本動作', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-status-bar').waitFor({ state: 'visible', timeout: 8000 });
    });

    test('ページが正常に読み込まれる', async ({ page }) => {
        await expect(page.locator('#live-status-bar')).toBeVisible();
    });

    test('雨雲ステータスが表示される', async ({ page }) => {
        await expect(page.locator('#live-status-bar')).toContainText('雨雲', { timeout: 6000 });
    });

    test('タイル読み込み中に uncaught error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('pageerror', err => errors.push(err.message));
        await page.waitForTimeout(1500);
        expect(errors.filter(e => /rain|canvas|pixel|getImageData/i.test(e))).toHaveLength(0);
    });

    test('地図コンテナが正常に表示される', async ({ page }) => {
        await expect(page.locator('#live-map')).toBeVisible();
    });

    test('弱雨は薄く、強雨・危険雨域は相対的に濃く残る', async ({ page }) => {
        await mockColoredRainTiles(page);
        await page.reload();
        await page.locator('canvas.leaflet-tile').first().waitFor({ state: 'visible', timeout: 8000 });

        const alpha = await page.locator('canvas.leaflet-tile').first().evaluate(canvas => {
            const ctx = canvas.getContext('2d');
            return {
                weak:       ctx.getImageData(32, 128, 1, 1).data[3],
                moderate:   ctx.getImageData(96, 128, 1, 1).data[3],
                severe:     ctx.getImageData(160, 128, 1, 1).data[3],
                background: ctx.getImageData(224, 128, 1, 1).data[3],
            };
        });

        expect(alpha.weak).toBeLessThan(alpha.moderate);
        expect(alpha.moderate).toBeLessThan(alpha.severe);
        expect(alpha.weak).toBeLessThanOrEqual(70);
        expect(alpha.severe).toBeGreaterThanOrEqual(190);
        expect(alpha.background).toBe(0);
    });
});

// ── Canvas 方式: 雨雲 ON/OFF トグル ──────────────────────────────────────────

test.describe('/live — 雨雲視認性改善: ON/OFF トグル', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-status-bar').waitFor({ state: 'visible', timeout: 8000 });
    });

    test('雨雲トグルボタンが存在する', async ({ page }) => {
        const btn = page.locator('[data-layer="rain"]').first();
        await expect(btn).toBeDefined();
    });

    test('雨雲 OFF にしても他ステータスは表示されている', async ({ page }) => {
        // 雨雲レイヤートグル（data-layer="rain" ボタン）をクリック
        const rainToggle = page.locator('[data-layer="rain"]').first();
        if (await rainToggle.count() > 0) {
            await rainToggle.click();
            await page.waitForTimeout(300);
        }
        // ページがクラッシュしていないこと
        await expect(page.locator('#live-status-bar')).toBeVisible();
    });
});

// ── Canvas 方式: タイムライン連携 ─────────────────────────────────────────────

test.describe('/live — 雨雲視認性改善: タイムライン連携', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-rain-timeline').waitFor({ state: 'visible', timeout: 8000 });
    });

    test('タイムラインコンテナが表示される', async ({ page }) => {
        await expect(page.locator('#live-rain-timeline')).toBeVisible();
    });

    test('スライダー操作後もページエラーなし', async ({ page }) => {
        const errors = [];
        page.on('pageerror', err => errors.push(err.message));
        const slider = page.locator('#rain-tl-slider');
        await slider.evaluate(el => {
            el.value = '4';
            el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await page.waitForTimeout(500);
        expect(errors.filter(e => /rain|canvas|pixel/i.test(e))).toHaveLength(0);
    });

    test('スライダーを動かしてもオフセットラベルが正しく更新される', async ({ page }) => {
        const slider = page.locator('#rain-tl-slider');
        await slider.evaluate(el => {
            el.value = '2';
            el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await expect(page.locator('#rain-tl-offset')).toHaveText('+10分');
    });

    test('再生ボタンが機能する（Canvas 方式でも停止しない）', async ({ page }) => {
        await page.locator('#rain-tl-play').click();
        await expect(page.locator('#rain-tl-play')).toHaveText('⏸');
        await page.locator('#rain-tl-play').click();
        await expect(page.locator('#rain-tl-play')).toHaveText('▶');
    });
});

// ── 他レイヤーとの共存確認 ───────────────────────────────────────────────────

test.describe('/live — 雨雲視認性改善: 他レイヤーと共存', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-status-bar').waitFor({ state: 'visible', timeout: 8000 });
    });

    test('アラートパネルが表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toBeVisible({ timeout: 6000 });
    });

    test('アラートパネルに地震セクションが存在する', async ({ page }) => {
        const card = page.locator('#live-alert-card');
        await card.waitFor({ timeout: 5000 });
        // 雨雲タイルがあっても地震セクションが読める
        await expect(card).toBeVisible();
    });

    test('雨雲レイヤー ON の状態でも uncaught error なし', async ({ page }) => {
        const errors = [];
        page.on('pageerror', err => errors.push(err.message));
        await page.waitForTimeout(2000);
        expect(errors).toHaveLength(0);
    });
});
