'use strict';
/**
 * live-tide-layer.spec.js — /live 潮位観測点レイヤー確認
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

// 観測点は zoom=5 で重ならないよう北海道・東京・沖縄に分散させる
const STATIONS_RESPONSE = {
    count: 3,
    stations: [
        { id: 'ABCD', name: '東京検潮所', lat: 35.65, lon: 139.77, prefecture: '東京都', has_data: true },
        { id: 'EFGH', name: '函館検潮所', lat: 41.78, lon: 140.73, prefecture: '北海道', has_data: true },
        { id: 'IJKL', name: '那覇検潮所', lat: 26.22, lon: 127.67, prefecture: '沖縄県', has_data: true },
    ],
};

const DETAIL_RESPONSE = {
    station_id:      'ABCD',
    name:            '東京検潮所',
    lat:             35.65,
    lon:             139.77,
    prefecture:      '東京都',
    current_tide_cm: 120,
    next_high_tide:  { time: '2026-05-30T08:00:00+09:00', tide_cm: 180, remaining_minutes: 60 },
    next_low_tide:   { time: '2026-05-30T14:00:00+09:00', tide_cm: 40,  remaining_minutes: 420 },
    records: [
        { datetime: '2026-05-30T00:00:00+09:00', tide_cm: 100 },
        { datetime: '2026-05-30T06:00:00+09:00', tide_cm: 150 },
        { datetime: '2026-05-30T12:00:00+09:00', tide_cm: 80  },
    ],
    extremes: {
        high_tides: [{ time: '2026-05-30T08:00:00+09:00', tide_cm: 180 }],
        low_tides:  [{ time: '2026-05-30T14:00:00+09:00', tide_cm: 40  }],
    },
};

const EQ_RESPONSE    = { count: 0, items: [] };
const TSUNAMI_RESPONSE = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const RAIN_TIMES     = { basetime: '20260530100000', times: [
    { offset_minutes: 0, validtime: '20260530100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260530100000/none/20260530100000/surf/hrpns/{z}/{x}/{y}.png' },
] };
const LIVE_SUMMARY   = { rain: { evaluated: false }, kikikuru: { evaluated: false }, earthquake: { evaluated: true, count: 0, items: [] }, tsunami: { evaluated: true, active: false, areas: [] } };

async function mockAll(page) {
    // 詳細エンドポイント（/stations/{id}）を先に登録してリスト（/stations）と区別する
    await page.route(/\/api\/live\/tide\/stations\/[^/]+$/, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL_RESPONSE)   }));
    await page.route('/api/live/tide/stations',              route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STATIONS_RESPONSE) }));
    await page.route('/api/earthquakes**',               route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE)       }));
    await page.route('/api/tsunami/**',                  route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_RESPONSE)  }));
    await page.route('/api/weather/rain/tile/times',     route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES)        }));
    await page.route('/api/live/summary',                route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY)      }));
    await page.route('**/jmatile/**',                    route => route.fulfill({ status: 200, contentType: 'image/png',         body: TRANSPARENT_PNG                  }));
    await page.route('**/jma.go.jp/**',                  route => route.fulfill({ status: 200, contentType: 'image/png',         body: TRANSPARENT_PNG                  }));
    await page.route('**/basemaps.cartocdn.com/**',      route => route.fulfill({ status: 200, contentType: 'image/png',         body: TRANSPARENT_PNG                  }));
}

test.describe('/live — 潮位観測点レイヤー', () => {
    test.beforeEach(async ({ page }) => {
        await mockAll(page);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
    });

    // ── UI ──────────────────────────────────────────────────────────────────

    test('潮位観測点トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-tide')).toBeVisible();
    });

    test('潮位観測点トグルの初期状態が OFF', async ({ page }) => {
        const toggle = page.locator('#toggle-tide');
        await expect(toggle).not.toBeChecked();
    });

    // ── ON/OFF ──────────────────────────────────────────────────────────────

    test('トグル ON で /api/live/tide/stations が呼ばれる', async ({ page }) => {
        const [req] = await Promise.all([
            page.waitForRequest('/api/live/tide/stations'),
            page.locator('#toggle-tide').check(),
        ]);
        expect(req.url()).toContain('/api/live/tide/stations');
    });

    test('トグル ON でマーカーが追加される', async ({ page }) => {
        await page.locator('#toggle-tide').check();
        // stations が 3件あるので Leaflet divIcon が 3つ現れる
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(3, { timeout: 5000 });
    });

    test('トグル OFF でマーカーが消える', async ({ page }) => {
        const toggle = page.locator('#toggle-tide');
        await toggle.check();
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(3, { timeout: 5000 });
        await toggle.uncheck();
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(0, { timeout: 3000 });
    });

    // ── マーカークリック ──────────────────────────────────────────────────────

    test('マーカークリックで詳細 API が呼ばれる', async ({ page }) => {
        await page.locator('#toggle-tide').check();
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(3, { timeout: 5000 });

        const [req] = await Promise.all([
            page.waitForRequest(/\/api\/live\/tide\/stations\//),
            page.locator('.leaflet-marker-icon[title="東京検潮所"]').click(),
        ]);
        expect(req.url()).toContain('/api/live/tide/stations/');
    });

    test('ポップアップに観測点名が表示される', async ({ page }) => {
        await page.locator('#toggle-tide').check();
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(3, { timeout: 5000 });
        await page.locator('.leaflet-marker-icon[title="東京検潮所"]').click();

        await expect(page.locator('.live-tide-popup')).toBeVisible({ timeout: 5000 });
    });

    test('ポップアップに現在潮位が表示される', async ({ page }) => {
        await page.locator('#toggle-tide').check();
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(3, { timeout: 5000 });
        await page.locator('.leaflet-marker-icon[title="東京検潮所"]').click();

        // 初期ポップアップ確認後、詳細データが更新されるのを待つ
        await expect(page.locator('.live-tide-popup')).toBeVisible({ timeout: 5000 });
        await expect(page.locator('.live-tide-popup-current')).toBeVisible({ timeout: 8000 });
        const text = await page.locator('.live-tide-popup-current').textContent();
        expect(text).toContain('120');
    });

    test('ポップアップに満潮・干潮情報が表示される', async ({ page }) => {
        await page.locator('#toggle-tide').check();
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(3, { timeout: 5000 });
        await page.locator('.leaflet-marker-icon[title="東京検潮所"]').click();

        await expect(page.locator('.live-tide-popup')).toBeVisible({ timeout: 5000 });
        await expect(page.locator('.live-tide-popup-extremes')).toBeVisible({ timeout: 8000 });
        const text = await page.locator('.live-tide-popup-extremes').textContent();
        expect(text).toContain('満');
        expect(text).toContain('干');
    });

    test('ポップアップにグラフ canvas が存在する', async ({ page }) => {
        await page.locator('#toggle-tide').check();
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(3, { timeout: 5000 });
        await page.locator('.leaflet-marker-icon[title="東京検潮所"]').click();

        await expect(page.locator('.live-tide-popup')).toBeVisible({ timeout: 5000 });
        await expect(page.locator('.live-tide-graph-canvas')).toBeVisible({ timeout: 8000 });
    });

    // ── ステータスバー ───────────────────────────────────────────────────────

    test('ステータスバーに潮位ドットが存在する（OFF 時は unknown）', async ({ page }) => {
        const bar = page.locator('#live-status-bar');
        await expect(bar).toContainText('潮位', { timeout: 5000 });
    });

    test('トグル ON 後にステータスバーの潮位が ok になる', async ({ page }) => {
        await page.locator('#toggle-tide').check();
        await expect(page.locator('.leaflet-marker-icon')).toHaveCount(3, { timeout: 5000 });

        // ok ドットは offline クラスを持たない
        const tideItem = page.locator('#live-status-bar .live-status-item').filter({ hasText: '潮位' });
        await expect(tideItem.locator('.live-status-dot:not(.offline):not(.unknown)')).toBeVisible({ timeout: 5000 });
    });

    // ── 既存機能への影響なし ──────────────────────────────────────────────────

    test('ナビ本体 index.html は影響を受けない（潮位 API を自動呼び出しない）', async ({ page }) => {
        const tideRequests = [];
        page.on('request', req => {
            if (req.url().includes('/api/live/tide/')) tideRequests.push(req.url());
        });
        await page.goto('/');
        await page.waitForTimeout(2000);
        expect(tideRequests).toHaveLength(0);
    });
});
