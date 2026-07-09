'use strict';
/**
 * live-weather-ticker.spec.js — /live 全国気象ミニテロップ確認 (Phase 8-A.1)
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const SUN_MOON_RESPONSE = {
    location: '東京', date: '2026-05-30', sunrise: '04:32', sunset: '18:55',
    moonrise: '15:42', moonset: '01:12', moon_phase: 12.4, moon_phase_name: '十三夜',
};
const EQ_RESPONSE      = { count: 0, items: [] };
const TSUNAMI_RESPONSE = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const RAIN_TIMES       = { basetime: '20260530100000', times: [
    { offset_minutes: 0, validtime: '20260530100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260530100000/none/20260530100000/surf/hrpns/{z}/{x}/{y}.png' },
] };
const LIVE_SUMMARY = {
    rain: { evaluated: false }, kikikuru: { evaluated: false },
    earthquake: { evaluated: true, count: 0, items: [] },
    tsunami: { evaluated: true, active: false, areas: [] },
};
const STATIONS_RESPONSE = { count: 0, stations: [] };

function weatherPoint(overrides) {
    return Object.assign({
        id: 'kanto_tokyo', pref_code: '13', pref_name: '東京都', point_name: '東京',
        display_order: 310, weather_code: 3, weather_category: 'cloudy', weather_label: '曇',
        temperature_c: 28.0, humidity_percent: 76, precipitation_probability_percent: 40,
        flags: { precipitation_high: false, temperature_hot: false, temperature_cold: false, humidity_high: false },
    }, overrides || {});
}

function weatherResponse({ items, cacheStatus, forecastTime, fetchedAt } = {}) {
    return {
        status: cacheStatus === 'unavailable' && !items ? 'unavailable' : 'ok',
        source: 'Open-Meteo Forecast',
        forecast_time: forecastTime || '2026-07-03T13:00:00+09:00',
        fetched_at: fetchedAt || '2026-07-03T13:05:00+09:00',
        cache_status: cacheStatus || 'fresh',
        items: items || [weatherPoint()],
    };
}

async function mockBase(page, weather) {
    await page.route('/api/live/sun-moon',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUN_MOON_RESPONSE) }));
    await page.route('/api/live/tide/stations',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STATIONS_RESPONSE) }));
    await page.route('/api/live/trains/summary**',   r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', stale: false, scope: {}, items: [] }) }));
    await page.route('/api/live/road-traffic/summary**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', items: [] }) }));
    await page.route('/api/live/earthquakes/history**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('/api/live/storm_surge/warnings**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ areas: [] }) }));
    await page.route('/api/earthquakes**',           r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**',              r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_RESPONSE) }));
    await page.route('/api/weather/rain/tile/times', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/summary',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('**/jmatile/**',                r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',              r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',  r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/api/live/weather/jma/prefectures**', r => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(weather || weatherResponse()),
    }));
}

test.describe('/live — 全国気象ミニテロップ (Phase 8-A.1)', () => {

    test('レイヤーパネル内に全国気象カードが表示され、出典がAPI応答通りになる', async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });

        await expect(page.locator('#live-weather-card')).toBeAttached();
        await expect(page.locator('#live-weather-card')).toContainText('全国気象');
        await expect(page.locator('[data-testid="live-weather-source-badge"]')).toHaveText('Open-Meteo Forecast');
    });

    test('ヘッダーに forecast_time / fetched_at がJST HH:mm形式で表示される', async ({ page }) => {
        await mockBase(page, weatherResponse({ forecastTime: '2026-07-03T23:00:00+09:00', fetchedAt: '2026-07-03T23:05:12+09:00' }));
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await expect(page.locator('[data-testid="live-weather-meta"]')).toContainText('23:00時点 / 23:05取得', { timeout: 5000 });
    });

    test('地点セルに天気バッジ・気温・湿度・降水確率が表示される', async ({ page }) => {
        await mockBase(page, weatherResponse({ items: [weatherPoint({ point_name: '那覇', weather_label: '晴', temperature_c: 30 })] }));
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        const cell = page.locator('[data-testid="live-weather-point"]').first();
        await expect(cell).toContainText('那覇', { timeout: 5000 });
        await expect(cell).toContainText('晴');
        await expect(cell).toContainText('30℃');
        await expect(cell.locator('.wm-badge')).toHaveCount(1);
    });

    test('降水確率70%以上・気温35℃以上・湿度85%以上が強調classになる', async ({ page }) => {
        await mockBase(page, weatherResponse({
            items: [weatherPoint({
                id: 'p1', point_name: '強調地点', temperature_c: 35, humidity_percent: 85,
                precipitation_probability_percent: 70,
                flags: { precipitation_high: true, temperature_hot: true, temperature_cold: false, humidity_high: true },
            })],
        }));
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        const cell = page.locator('[data-testid="live-weather-point"]').first();
        await expect(cell.locator('.wm-flag-precip-high')).toHaveCount(1, { timeout: 5000 });
        await expect(cell.locator('.wm-flag-temp-hot')).toHaveCount(1);
        await expect(cell.locator('.wm-flag-humidity-high')).toHaveCount(1);
    });

    test('stale時に「更新遅延」が表示される', async ({ page }) => {
        await mockBase(page, weatherResponse({ cacheStatus: 'stale', forecastTime: '2026-07-03T22:00:00+09:00', fetchedAt: '2026-07-03T22:10:00+09:00' }));
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await expect(page.locator('[data-testid="live-weather-meta"]')).toContainText('更新遅延', { timeout: 5000 });
    });

    test('unavailable時に「更新停止中」が表示され、「天気なし」と誤表示しない', async ({ page }) => {
        await mockBase(page, {
            status: 'unavailable', source: 'Open-Meteo Forecast',
            forecast_time: null, fetched_at: '2026-07-03T21:40:00+09:00',
            cache_status: 'unavailable', items: [],
        });
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        const meta = page.locator('[data-testid="live-weather-meta"]');
        await expect(meta).toContainText('更新停止中', { timeout: 5000 });
        await expect(meta).toContainText('21:40取得');
        await expect(page.locator('[data-testid="live-weather-unavailable"]')).toBeVisible();
    });

    test('frontend が Open-Meteo を直接叩いていない', async ({ page }) => {
        await mockBase(page);
        let directCallSeen = false;
        await page.route('**api.open-meteo.com**', route => { directCallSeen = true; route.abort(); });
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(500);
        expect(directCallSeen).toBe(false);
    });

    test('ナビ本体 index.html は /api/live/weather/jma/prefectures を自動呼び出しない', async ({ page }) => {
        const reqs = [];
        page.on('request', req => { if (req.url().includes('/api/live/weather/jma/prefectures')) reqs.push(req.url()); });
        await page.goto('/');
        await page.waitForTimeout(2000);
        expect(reqs).toHaveLength(0);
    });

    test('ページロード後に console.error が発生せず、日月情報カードも壊れていない', async ({ page }) => {
        await mockBase(page);
        const errors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(2000);
        expect(errors).toHaveLength(0);
        await expect(page.locator('#live-sun-moon-card')).toBeAttached();
        await expect(page.locator('#live-sun-moon-body')).not.toContainText('読み込み中', { timeout: 5000 });
    });
});
