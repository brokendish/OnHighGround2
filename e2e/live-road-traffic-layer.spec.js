'use strict';
/**
 * live-road-traffic-layer.spec.js — /live 道路交通影響レイヤー MVP 確認
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const EQ_RESPONSE       = { count: 0, items: [] };
const TSUNAMI_RESPONSE  = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const STORM_SURGE_NONE  = { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] };
const LIVE_SUMMARY      = {
    rain: { evaluated: false },
    kikikuru: { evaluated: false },
    earthquake: { evaluated: true, count: 0, items: [] },
    tsunami: { evaluated: true, active: false, areas: [] },
};
const RAIN_TIMES = {
    basetime: '20260620100000',
    times: [
        { offset_minutes: 0, validtime: '20260620100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260620100000/none/20260620100000/surf/hrpns/{z}/{x}/{y}.png' },
    ],
};
const TRAIN_NONE = {
    status: 'ok', stale: false,
    scope: { mode: 'all' },
    updated_at: '2026-06-20T10:00:00+09:00',
    items: [],
};

// 道路交通影響サンプルデータ
const ROAD_TRAFFIC_DATA = {
    status: 'ok',
    stale: false,
    scope: { mode: 'prefecture', prefecture: '東京都' },
    updated_at: '2026-06-20T10:00:00+09:00',
    items: [
        {
            station_id: 'T001',
            road_name: '国道20号',
            direction: '上り',
            lat: 35.6812,
            lng: 139.7671,
            volume_5min: 180,
            volume_1h: 2160,
            baseline_volume_1h: null,
            status: 'very_high',
            status_label: '交通量非常に多い',
            severity: 3,
            observed_at: '2026-06-20T09:55:00+09:00',
            source: '国土交通省 交通量API（JARTIC提供）[mock]',
        },
        {
            station_id: 'T002',
            road_name: '国道246号',
            direction: '下り',
            lat: 35.6503,
            lng: 139.6941,
            volume_5min: 10,
            volume_1h: 120,
            baseline_volume_1h: null,
            status: 'low',
            status_label: '交通量少ない',
            severity: 2,
            observed_at: '2026-06-20T09:55:00+09:00',
            source: '国土交通省 交通量API（JARTIC提供）[mock]',
        },
        {
            station_id: 'T003',
            road_name: '国道16号',
            direction: '外回り',
            lat: 35.7281,
            lng: 139.8601,
            volume_5min: 40,
            volume_1h: 480,
            baseline_volume_1h: null,
            status: 'normal',
            status_label: '通常',
            severity: 0,
            observed_at: '2026-06-20T09:55:00+09:00',
            source: '国土交通省 交通量API（JARTIC提供）[mock]',
        },
    ],
};

const ROAD_TRAFFIC_UNAVAILABLE = {
    status: 'unavailable',
    stale: false,
    message: '道路交通量情報を取得できません',
    scope: {},
    updated_at: '2026-06-20T10:00:00+09:00',
    items: [],
};

const ROAD_TRAFFIC_EMPTY = {
    status: 'ok',
    stale: false,
    scope: { mode: 'prefecture', prefecture: '青森県' },
    updated_at: '2026-06-20T10:00:00+09:00',
    items: [],
    message: '現在地周辺の道路交通量情報はありません',
};

async function mockBaseLiveApis(page, roadTrafficFactory = () => ROAD_TRAFFIC_DATA) {
    await page.route('/data/municipality_coords.json', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/live/sun-moon', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/earthquakes**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_RESPONSE) }));
    await page.route('/api/live/storm_surge/**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STORM_SURGE_NONE) }));
    await page.route('/api/weather/rain/tile/times', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/summary', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('/api/live/trains/summary**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TRAIN_NONE) }));
    await page.route('/api/live/road-traffic/summary**', route => {
        const body = roadTrafficFactory(route.request().url());
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.route('**/jmatile/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('/api/trains/osm**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ type: 'FeatureCollection', features: [] }) }));
}

test.describe('/live — 道路交通影響レイヤー', () => {

    test('道路交通影響カードが表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        await expect(page.locator('#live-road-traffic-card')).toBeVisible();
        await expect(page.locator('#live-road-traffic-card')).toContainText('道路交通影響');
    });

    test('very_high / low が表示され normal は非表示（ランキング外）', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        await expect(page.locator('#live-road-traffic-card')).toContainText('国道20号');
        await expect(page.locator('#live-road-traffic-card')).toContainText('交通量非常に多い');
        await expect(page.locator('#live-road-traffic-card')).toContainText('国道246号');
        await expect(page.locator('#live-road-traffic-card')).toContainText('交通量少ない');
        // normal はランキング対象外
        await expect(page.locator('#live-road-traffic-card')).not.toContainText('通常');
    });

    test('取得不可とデータなしを分離する', async ({ page }) => {
        // unavailable
        await mockBaseLiveApis(page, () => ROAD_TRAFFIC_UNAVAILABLE);
        await page.goto('/live.html');
        await expect(page.locator('#live-road-traffic-card')).toContainText('道路交通量情報を取得できません');
        await expect(page.locator('#live-road-traffic-card')).not.toContainText('交通影響は確認されていません');

        // データなし (ok + items=[])
        await mockBaseLiveApis(page, () => ROAD_TRAFFIC_EMPTY);
        await page.reload();
        await expect(page.locator('#live-road-traffic-card')).not.toContainText('道路交通量情報を取得できません');
    });

    test('異常なし（normal のみ）のときは適切なメッセージを表示', async ({ page }) => {
        const allNormal = {
            status: 'ok', stale: false,
            scope: { mode: 'prefecture', prefecture: '東京都' },
            updated_at: '2026-06-20T10:00:00+09:00',
            items: [{ ...ROAD_TRAFFIC_DATA.items[2] }],  // normal のみ
        };
        await mockBaseLiveApis(page, () => allNormal);
        await page.goto('/live.html');

        await expect(page.locator('#live-road-traffic-card')).toContainText('目立った道路交通影響は確認されていません');
    });

    test('道路交通影響レイヤーをON/OFFできる', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        // 初期 OFF
        const toggle = page.locator('#toggle-road-traffic');
        await expect(toggle).not.toBeChecked();

        // ON
        await toggle.check();
        await expect(toggle).toBeChecked();

        // OFF
        await toggle.uncheck();
        await expect(toggle).not.toBeChecked();
    });

    test('観測点マーカーがON時に表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        await page.locator('#toggle-road-traffic').check();
        // very_high と low の 2観測点（normal はlayer上でも描画するが severity で表示）
        const markers = page.locator('[class*="road-traffic-"]');
        await expect.poll(() => markers.count(), { timeout: 5000 }).toBeGreaterThan(0);
    });

    test('ポップアップに交通量・観測時刻・出典・注意書きが表示される', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        await page.locator('#toggle-road-traffic').check();
        await page.waitForTimeout(500);

        const markers = page.locator('.road-traffic-very-high, .road-traffic-high, .road-traffic-low, .road-traffic-very-low');
        const count = await markers.count();
        if (count > 0) {
            await markers.first().click({ force: true });
            await expect(page.locator('.leaflet-popup-content')).toContainText('台/5分');
            await expect(page.locator('.leaflet-popup-content')).toContainText('観測時刻');
            await expect(page.locator('.leaflet-popup-content')).toContainText('出典');
            await expect(page.locator('.leaflet-popup-content')).toContainText('通行止め・規制を断定するものではありません');
            await expect(page.locator('.leaflet-popup-content')).not.toContainText('undefined');
            await expect(page.locator('.leaflet-popup-content')).not.toContainText('null');
        }
    });

    test('交通量を通行止めと断定していない（凡例・注意書きの確認）', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        const card = page.locator('#live-road-traffic-card');
        // 「通行止めではない」という注意書きは許容し、断定表現だけを禁止する。
        await expect(card).not.toContainText('通行止めです');
        await expect(card).not.toContainText('通行止め・規制です');
        await expect(card).toContainText('交通量非常に多い（通行止めではありません）');
    });

    test('stale cache 時に stale 通知が表示される', async ({ page }) => {
        const staleData = {
            ...ROAD_TRAFFIC_DATA,
            stale: true,
            message: '最新の道路交通量情報を取得できません。前回取得情報を表示しています',
        };
        await mockBaseLiveApis(page, () => staleData);
        await page.goto('/live.html');

        await expect(page.locator('#live-road-traffic-card')).toContainText('前回取得情報を表示しています');
        // stale でも items が表示される（unavailable と混同しない）
        await expect(page.locator('#live-road-traffic-card')).toContainText('国道20号');
    });

    test('他レイヤー（鉄道・雨雲・津波）に影響しない', async ({ page }) => {
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        // 道路レイヤートグル操作しても他カードが残る
        await page.locator('#toggle-road-traffic').check();
        await page.locator('#toggle-road-traffic').uncheck();

        await expect(page.locator('#live-train-card')).toBeVisible();
        await expect(page.locator('#live-alert-card')).toBeVisible();
    });

    test('モバイル幅で横スクロールが出ない', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await mockBaseLiveApis(page);
        await page.goto('/live.html');

        await expect(page.locator('#live-road-traffic-card')).toBeVisible();
        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
        );
        expect(overflow).toBe(false);
    });

});
