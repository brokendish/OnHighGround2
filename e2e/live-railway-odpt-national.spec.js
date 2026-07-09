'use strict';
/**
 * live-railway-odpt-national.spec.js — /live 鉄道運行情報 全国ODPT対応 (Phase 7-A.5)
 *
 * 関東外の事業者・GeoJSON未一致路線・座標なし路線を混ぜても /live が破綻しないこと、
 * 東京駅・関東固定の旧挙動が復活していないことを確認する。
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const EQ_RESPONSE = { count: 0, items: [] };
const TSUNAMI_RESPONSE = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const STORM_SURGE_NONE = { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] };
const LIVE_SUMMARY = {
    rain: { evaluated: false },
    kikikuru: { evaluated: false },
    earthquake: { evaluated: true, count: 0, items: [] },
    tsunami: { evaluated: true, active: false, areas: [] },
};
const RAIN_TIMES = { basetime: '20260708100000', times: [] };

// e2e/helpers/server.js はテスト用の最小静的サーバーで、PMTiles の Range 配信
// (HTTP 206 + Content-Range) に対応していない。そのため全国PMTilesベースレイヤー
// (live-train-pmtiles-layer.js) を有効化すると protomaps-leaflet が
// "no content-length header" エラーを出すが、これはこのテスト用サーバー固有の
// 既知の制約であり、本番 nginx (Range 対応) やアプリのロジック不具合ではない。
function _isBenignTestServerError(text) {
    return /content-length header|Byte Serving/.test(text);
}

function trainItem(overrides) {
    return Object.assign({
        railway_id: 'odpt.Railway:JR-West.Kobe',
        operator_id: 'odpt.Operator:JR-West',
        operator_name: 'JR西日本',
        railway_name: '神戸線',
        status: 'delay',
        status_label: '遅延',
        severity: 2,
        description: '検証用の遅延です。',
        updated_at: '2026-07-08T10:00:00+09:00',
        source: 'ODPT',
        matched_geojson: false,
    }, overrides || {});
}

async function mockBaseLiveApis(page, items) {
    await page.route('**/data/municipality_coords.json', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('**/api/live/sun-moon', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('**/api/earthquakes**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/tsunami/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_RESPONSE) }));
    await page.route('**/api/live/storm_surge/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STORM_SURGE_NONE) }));
    await page.route('**/api/live/road-traffic/summary**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', items: [] }) }));
    await page.route('**/api/weather/rain/tile/times', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('**/api/live/rain/timeline', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('**/api/live/summary', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIVE_SUMMARY) }));
    await page.route('**/api/live/trains/summary**', route => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
            status: 'ok', stale: false, scope: { mode: 'all' },
            updated_at: '2026-07-08T10:00:00+09:00',
            items: items || [],
        }),
    }));
    await page.route('**/jmatile/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
}

test.describe('/live — 全国ODPT対応 (Phase 7-A.5)', () => {
    test('関東外の障害路線 (GeoJSON未一致・代表点あり) がパネルに表示され、地図もクラッシュしない', async ({ page }) => {
        const items = [
            trainItem({
                railway_id: 'odpt.Railway:JR-West.Kobe', railway_name: '神戸線',
                operator_name: 'JR西日本', lat: 34.69, lng: 135.19, matched_geojson: false,
            }),
        ];
        const errs = [];
        page.on('pageerror', e => { if (!_isBenignTestServerError(e.message)) errs.push(e.message); });
        page.on('console', m => { if (m.type() === 'error' && !_isBenignTestServerError(m.text())) errs.push(m.text()); });

        await mockBaseLiveApis(page, items);
        const response = await page.goto('/live.html');
        expect(response.status()).toBeLessThan(400);

        await expect(page.locator('#lac-train-slot')).toContainText('神戸線');
        await expect(page.locator('#lac-train-slot')).toContainText('遅延');

        await page.locator('#toggle-train').check();
        await page.waitForTimeout(1000);
        await page.locator('#toggle-train').uncheck();

        expect(errs, 'console/page errors').toEqual([]);
    });

    test('座標もGeoJSON一致も無い路線はカードに出るが地図ピンにはならず、クラッシュもしない', async ({ page }) => {
        const items = [
            // 代表点マッピング未登録の事業者を模した項目 (lat/lng を省略)
            trainItem({
                railway_id: 'odpt.Railway:Unknown.Local', railway_name: '検証未知路線',
                operator_name: '検証未知事業者', status: 'suspended', status_label: '運転見合わせ',
                severity: 4, matched_geojson: false,
                // lat/lng なし
            }),
        ];
        delete items[0].lat;
        delete items[0].lng;

        const errs = [];
        page.on('pageerror', e => { if (!_isBenignTestServerError(e.message)) errs.push(e.message); });
        page.on('console', m => { if (m.type() === 'error' && !_isBenignTestServerError(m.text())) errs.push(m.text()); });

        await mockBaseLiveApis(page, items);
        await page.goto('/live.html');

        await expect(page.locator('#lac-train-slot')).toContainText('検証未知路線');

        await page.locator('#toggle-train').check();
        await page.waitForTimeout(1000);
        // 座標が無い路線はマーカーを持たないため、地図上の interactive path は 0 件のまま
        await expect(page.locator('.leaflet-overlay-pane svg path.leaflet-interactive')).toHaveCount(0);

        expect(errs, 'console/page errors').toEqual([]);
    });

    test('/live は関東外+関東混在データでも200 OKで表示できる', async ({ page }) => {
        const items = [
            trainItem({ railway_id: 'odpt.Railway:Keio.Keio', railway_name: '京王線', operator_name: '京王電鉄', lat: 35.69, lng: 139.55, matched_geojson: true }),
            trainItem({ railway_id: 'odpt.Railway:JR-Kyushu.Kagoshima', railway_name: '鹿児島本線', operator_name: 'JR九州', lat: 33.59, lng: 130.40, matched_geojson: false }),
        ];
        const errs = [];
        page.on('pageerror', e => { if (!_isBenignTestServerError(e.message)) errs.push(e.message); });
        page.on('console', m => { if (m.type() === 'error' && !_isBenignTestServerError(m.text())) errs.push(m.text()); });

        await mockBaseLiveApis(page, items);
        const response = await page.goto('/live.html');
        expect(response.status()).toBeLessThan(400);
        await expect(page.locator('#lac-train-slot')).toContainText('京王線');
        await expect(page.locator('#lac-train-slot')).toContainText('鹿児島本線');
        expect(errs, 'console/page errors').toEqual([]);
    });
});
