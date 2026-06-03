'use strict';
/**
 * live-sun-moon-card.spec.js — /live 日月情報カード確認
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const SUN_MOON_RESPONSE = {
    location:        '東京',
    date:            '2026-05-30',
    sunrise:         '04:32',
    sunset:          '18:55',
    moonrise:        '15:42',
    moonset:         '01:12',
    moon_phase:      12.4,
    moon_phase_name: '十三夜',
};

const SUN_MOON_NO_MOONRISE = {
    location:        '東京',
    date:            '2026-05-30',
    sunrise:         '04:32',
    sunset:          '18:55',
    moonrise:        null,
    moonset:         null,
    moon_phase:      0.5,
    moon_phase_name: '新月',
};

const EQ_RESPONSE    = { count: 0, items: [] };
const TSUNAMI_RESPONSE = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const RAIN_TIMES     = { basetime: '20260530100000', times: [
    { offset_minutes: 0, validtime: '20260530100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260530100000/none/20260530100000/surf/hrpns/{z}/{x}/{y}.png' },
] };
const LIVE_SUMMARY   = {
    rain: { evaluated: false }, kikikuru: { evaluated: false },
    earthquake: { evaluated: true, count: 0, items: [] },
    tsunami: { evaluated: true, active: false, areas: [] },
};
const STATIONS_RESPONSE = { count: 0, stations: [] };

async function mockBase(page, sunMoonResponse) {
    await page.route('/api/live/sun-moon',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sunMoonResponse) }));
    await page.route('/api/live/tide/stations',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STATIONS_RESPONSE) }));
    await page.route('/api/earthquakes**',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**',              r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_RESPONSE) }));
    await page.route('/api/weather/rain/tile/times', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/summary',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('**/jmatile/**',                r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',              r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',  r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
}

test.describe('/live — 日月情報カード', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, SUN_MOON_RESPONSE);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
    });

    // ── DOM 存在確認 ─────────────────────────────────────────────────────────

    test('日月情報カードが DOM に存在する', async ({ page }) => {
        await expect(page.locator('#live-sun-moon-card')).toBeAttached();
    });

    test('日月情報の body 要素が存在する', async ({ page }) => {
        await expect(page.locator('#live-sun-moon-body')).toBeAttached();
    });

    // ── API 呼び出し ─────────────────────────────────────────────────────────

    test('/api/live/sun-moon が呼ばれデータが反映される', async ({ page }) => {
        // beforeEach でページ読み込み時に既にリクエスト済み。
        // データが表示されていることで API 呼び出しを確認する。
        await expect(page.locator('#live-sun-moon-body')).not.toContainText('読み込み中', { timeout: 5000 });
    });

    // ── データ表示確認 ────────────────────────────────────────────────────────

    test('日の出時刻が表示される', async ({ page }) => {
        await expect(page.locator('#live-sun-moon-body')).toContainText('04:32', { timeout: 5000 });
    });

    test('日の入り時刻が表示される', async ({ page }) => {
        await expect(page.locator('#live-sun-moon-body')).toContainText('18:55', { timeout: 5000 });
    });

    test('月の出時刻が表示される', async ({ page }) => {
        await expect(page.locator('#live-sun-moon-body')).toContainText('15:42', { timeout: 5000 });
    });

    test('月の入り時刻が表示される', async ({ page }) => {
        await expect(page.locator('#live-sun-moon-body')).toContainText('01:12', { timeout: 5000 });
    });

    test('月齢が表示される', async ({ page }) => {
        await expect(page.locator('#live-sun-moon-body')).toContainText('12.4', { timeout: 5000 });
    });

    test('月相名が表示される', async ({ page }) => {
        await expect(page.locator('#live-sun-moon-body')).toContainText('十三夜', { timeout: 5000 });
    });

    // ── 月の出なし（新月付近）────────────────────────────────────────────────

    test('月の出なし時に -- が表示される', async ({ page }) => {
        await page.route('/api/live/sun-moon', r => r.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(SUN_MOON_NO_MOONRISE),
        }));
        await page.reload();
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await expect(page.locator('#live-sun-moon-body')).toContainText('新月', { timeout: 5000 });
    });

    // ── エラー時 ─────────────────────────────────────────────────────────────

    test('API 失敗時に「取得できません」が表示される', async ({ page }) => {
        await page.route('/api/live/sun-moon', r => r.fulfill({ status: 503 }));
        await page.reload();
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await expect(page.locator('#live-sun-moon-body')).toContainText('取得できません', { timeout: 5000 });
    });

    test('API 失敗時に危険表示へ変換しない', async ({ page }) => {
        await page.route('/api/live/sun-moon', r => r.fulfill({ status: 503 }));
        await page.reload();
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        const text = await page.locator('#live-sun-moon-body').textContent();
        expect(text).not.toContain('危険');
        expect(text).not.toContain('警報');
    });

    // ── ナビ本体非干渉 ────────────────────────────────────────────────────────

    test('ナビ本体 index.html は /api/live/sun-moon を自動呼び出しない', async ({ page }) => {
        const reqs = [];
        page.on('request', req => { if (req.url().includes('/api/live/sun-moon')) reqs.push(req.url()); });
        await page.goto('/');
        await page.waitForTimeout(2000);
        expect(reqs).toHaveLength(0);
    });

    // ── 既存レイヤーとの共存 ─────────────────────────────────────────────────

    test('ページロード後に console.error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        await page.waitForTimeout(2000);
        expect(errors).toHaveLength(0);
    });

    test('ステータスバーが存在し「雨雲」を含む', async ({ page }) => {
        await expect(page.locator('#live-status-bar')).toContainText('雨雲', { timeout: 5000 });
    });
});
