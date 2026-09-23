'use strict';
/**
 * live-storm-surge.spec.js — /live 高潮・津波レイヤー確認
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const EQ_RESPONSE      = { count: 0, items: [] };
const TSUNAMI_NONE     = { source: 'mock', status: 'none', observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const TSUNAMI_WARNING  = {
    source: 'mock', status: 'active', observed_at: null, updated_at: null, ttl_seconds: 60,
    areas: [
        { code: null, name: '東京湾内湾', level: 'warning', level_label: '津波警報', expected_height: '1m', arrival_time: null, is_target: true },
    ],
    message: '津波警報が発表されています。',
};
const STORM_SURGE_NONE = {
    status: 'ok', evaluated: true,
    summary: { active: false, warning_area_count: 0 },
    areas: [],
    updated_at: null,
};
// Phase A/B: pref_code と affected_areas を含むモックデータ
const STORM_SURGE_WARNING = {
    status: 'ok', evaluated: true,
    summary: { active: true, warning_area_count: 1 },
    areas: [
        {
            id: 'storm_surge-0', label: '東京都', detail: '高潮警報',
            level: 'danger', type: 'storm_surge', source: 'mock',
            lat: 35.6762, lng: 139.6503,
            pref_code: '130000',
            affected_areas: [
                { area_name: '江東区', area_code: '1314200', kind: '高潮警報', level: 'warning' },
                { area_name: '江戸川区', area_code: '1312300', kind: '高潮警報', level: 'warning' },
            ],
        },
    ],
    updated_at: null,
};
// Phase A: 注意報のみ（level=warning、沿岸部ハイライトは注意報色）
const STORM_SURGE_ADVISORY = {
    status: 'ok', evaluated: true,
    summary: { active: true, warning_area_count: 0 },
    areas: [
        {
            id: 'storm_surge-0', label: '大阪府', detail: '高潮注意報',
            level: 'warning', type: 'storm_surge', source: 'mock',
            lat: 34.6937, lng: 135.5023,
            pref_code: '270000',
            affected_areas: [
                { area_name: '大阪市', area_code: '2710000', kind: '高潮注意報', level: 'advisory' },
            ],
        },
    ],
    updated_at: null,
};
const RAIN_TIMES = { basetime: '20260601000000', times: [
    { offset_minutes: 0, validtime: '20260601000000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260601000000/none/20260601000000/surf/hrpns/{z}/{x}/{y}.png' },
] };

// /live 初期化時に取得されるが本 spec の検証対象外の API（未 mock だと 404 → console.error）。
// 各 frontend consumer / backend の正常応答と同じ schema の「影響なし」正常データを返す。
// live-layers.js _eqRefresh: items / source / fallback / municipalityIntensityAvailable
const EQ_HISTORY_NONE = {
    days: 3, source: 'p2p', fallback: false, municipalityIntensityAvailable: true,
    updated_at: '2026-06-01T09:00:00+09:00', count: 0, items: [],
};
// live-train-panel.js _render: status / stale / scope / items（normal 以外を障害表示）
const TRAINS_NO_ISSUE = {
    status: 'ok', stale: false, scope: { mode: 'location', prefecture: '東京都' },
    updated_at: '2026-06-01T09:00:00+09:00', items: [],
};
// live-weather-ticker.js: status / source / forecast_time / fetched_at / cache_status / items
const WEATHER_PREFS_OK = {
    status: 'ok', source: 'Open-Meteo Forecast',
    forecast_time: '2026-06-01T09:00:00+09:00', fetched_at: '2026-06-01T09:00:00+09:00',
    cache_status: 'fresh',
    items: [{
        id: 'tokyo', pref_code: '130000', pref_name: '東京都', point_name: '東京', display_order: 13,
        weather_code: 1, weather_category: 'clear', weather_label: '晴れ',
        temperature_c: 25, humidity_percent: 60, precipitation_probability_percent: 10,
        flags: { precipitation_high: false, temperature_hot: false, temperature_cold: false, humidity_high: false },
    }],
};
// live-road-traffic-panel.js _render: status / stale / scope / items（normal は影響なし扱い）
const ROAD_TRAFFIC_NO_ISSUE = {
    status: 'ok', stale: false, scope: { mode: 'location', prefecture: '東京都' },
    updated_at: '2026-06-01T09:00:00+09:00',
    items: [{
        station_id: 'mock-001', road_name: '国道15号', direction: '上り', lat: 35.65, lng: 139.75,
        volume_5min: 120, volume_1h: 1400, baseline_volume_1h: null,
        status: 'normal', status_label: '通常', severity: 0,
        observed_at: '2026-06-01T09:00:00+09:00', source: '国土交通省 交通量API（JARTIC提供）',
    }],
};

function _liveSummary(tsunamiAreas, stormSurgeAreas) {
    return {
        status: 'ok',
        rain:        { status: 'ok', evaluated: false, summary: {}, areas: [] },
        kikikuru:    { status: 'ok', evaluated: false, summary: {}, areas: [] },
        earthquake:  { status: 'ok', evaluated: true, summary: { count_24h: 0, m5_count: 0 }, areas: [] },
        tsunami:     { status: 'ok', evaluated: true, summary: { active: tsunamiAreas.length > 0, warning_area_count: tsunamiAreas.length }, areas: tsunamiAreas },
        storm_surge: { status: 'ok', evaluated: true, summary: { active: stormSurgeAreas.length > 0, warning_area_count: stormSurgeAreas.length }, areas: stormSurgeAreas },
        dangerous_areas: [],
    };
}

async function mockBase(page, { tsunamiResp = TSUNAMI_NONE, stormSurgeResp = STORM_SURGE_NONE } = {}) {
    await page.route('/api/earthquakes**',              route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**',                 route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tsunamiResp) }));
    await page.route('/api/live/storm_surge/**',        route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(stormSurgeResp) }));
    await page.route('/api/live/tide/stations',         route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/tide/**',               route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/astro**',               route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/live/sun-moon**',            route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/live/sun_moon**',            route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/weather/rain/tile/times',    route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline',         route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/earthquakes/history**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_HISTORY_NONE) }));
    await page.route('/api/live/trains/summary**',      route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TRAINS_NO_ISSUE) }));
    await page.route('/api/live/weather/jma/prefectures**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(WEATHER_PREFS_OK) }));
    await page.route('/api/live/road-traffic/summary**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ROAD_TRAFFIC_NO_ISSUE) }));
    await page.route('/api/live/summary',               route => {
        const tsAreas = tsunamiResp.areas || [];
        const ssAreas = stormSurgeResp.areas || [];
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(_liveSummary(tsAreas, ssAreas)) });
    });
    await page.route('**/jmatile/**',                   route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',                 route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',     route => route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
}

// ── レイヤーパネル ────────────────────────────────────────────────────────────

test.describe('/live — レイヤーパネル（津波・高潮）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
    });

    test('津波トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-tsunami')).toBeVisible();
    });

    test('高潮トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-storm-surge')).toBeVisible();
    });

    test('津波トグルの初期状態が ON', async ({ page }) => {
        await expect(page.locator('#toggle-tsunami')).toBeChecked();
    });

    test('高潮トグルの初期状態が ON', async ({ page }) => {
        await expect(page.locator('#toggle-storm-surge')).toBeChecked();
    });
});

// ── 津波なし時のアラートパネル ────────────────────────────────────────────────

test.describe('/live — アラートパネル（高潮なし）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_NONE });
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });
    });

    test('高潮警報なしが表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('高潮警報なし', { timeout: 6000 });
    });
});

// ── 高潮警報あり時のアラートパネル ─────────────────────────────────────────────

test.describe('/live — アラートパネル（高潮警報あり）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await page.goto('/live.html');
        await page.locator('#live-alert-card').waitFor({ timeout: 8000 });
    });

    test('高潮警報バッジが表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('高潮警報', { timeout: 6000 });
    });

    test('発令都道府県名が表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('東京都', { timeout: 6000 });
    });
});

// ── 高潮レイヤーAPI呼び出し ───────────────────────────────────────────────────

test.describe('/live — 高潮API呼び出し', () => {
    test('起動時に /api/live/storm_surge/warnings が呼ばれる', async ({ page }) => {
        await mockBase(page);
        const [req] = await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        expect(req.url()).toContain('/api/live/storm_surge/warnings');
    });
});

// ── 高潮警報マーカー ─────────────────────────────────────────────────────────

test.describe('/live — 高潮警報マーカー表示', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(300);
    });

    test('高潮警報マーカーが地図上に表示される', async ({ page }) => {
        const markers = page.locator('.leaflet-marker-icon[title="東京都"]');
        await expect(markers).toHaveCount(1, { timeout: 5000 });
    });

    test('高潮トグル OFF でマーカーが消える', async ({ page }) => {
        await expect(page.locator('.leaflet-marker-icon[title="東京都"]')).toHaveCount(1, { timeout: 5000 });
        await page.locator('#toggle-storm-surge').uncheck();
        await expect(page.locator('.leaflet-marker-icon[title="東京都"]')).toHaveCount(0, { timeout: 3000 });
    });
});

// ── Phase A: 沿岸部ハイライト（L.circle）────────────────────────────────────

test.describe('/live — Phase A: 沿岸部ハイライト', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
    });

    test('高潮警報がある場合、沿岸部ハイライト円が表示される', async ({ page }) => {
        const rings = page.locator('.storm-surge-coast-ring');
        await expect(rings).toHaveCount(1, { timeout: 5000 });
    });

    test('高潮トグル OFF で沿岸部ハイライトも消える', async ({ page }) => {
        await expect(page.locator('.storm-surge-coast-ring')).toHaveCount(1, { timeout: 5000 });
        await page.locator('#toggle-storm-surge').uncheck();
        await expect(page.locator('.storm-surge-coast-ring')).toHaveCount(0, { timeout: 3000 });
    });
});

test.describe('/live — Phase A: 高潮なし時のハイライト非表示', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_NONE });
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
    });

    test('高潮警報なしの場合、沿岸部ハイライト円は表示されない', async ({ page }) => {
        await expect(page.locator('.storm-surge-coast-ring')).toHaveCount(0, { timeout: 3000 });
    });
});

test.describe('/live — Phase A: 注意報でも沿岸部ハイライトが表示される', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_ADVISORY });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
    });

    test('注意報（level=warning）でも沿岸部ハイライトが表示される', async ({ page }) => {
        const rings = page.locator('.storm-surge-coast-ring');
        await expect(rings).toHaveCount(1, { timeout: 5000 });
    });
});

// ── Phase B: 市区町村単位の情報がポップアップに含まれる ─────────────────────

/** Leaflet の全レイヤーを再帰的に走査してポップアップ内容を返す */
async function getCoastPopupContents(page) {
    return page.evaluate(() => {
        function collectPopups(layer) {
            const results = [];
            if (layer.eachLayer) {
                layer.eachLayer(l => results.push(...collectPopups(l)));
            }
            const popup = layer.getPopup?.();
            if (popup) {
                const content = popup.getContent?.();
                if (typeof content === 'string') results.push(content);
            }
            return results;
        }
        return collectPopups(window.liveMap);
    });
}

test.describe('/live — Phase B: 市区町村情報のポップアップ', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
    });

    test('沿岸部ハイライト円をクリックするとポップアップが表示される', async ({ page }) => {
        const ring = page.locator('.storm-surge-coast-ring').first();
        const box = await ring.boundingBox();
        // 円の上端付近をクリック（中央のマーカーとの重複を回避）
        await page.mouse.click(box.x + box.width / 2, box.y + 3);
        await expect(page.locator('.leaflet-popup')).toBeVisible({ timeout: 3000 });
    });

    test('ポップアップに「高潮警報対象の沿岸部」と表示される', async ({ page }) => {
        // クリックではなく Leaflet レイヤーのポップアップ内容を直接検証
        const contents = await getCoastPopupContents(page);
        expect(contents.some(c => c.includes('高潮警報対象の沿岸部'))).toBe(true);
    });

    test('ポップアップに市区町村名が含まれる（Phase B）', async ({ page }) => {
        // affected_areas に江東区・江戸川区が含まれているはず
        const contents = await getCoastPopupContents(page);
        expect(contents.some(c => c.includes('江東区'))).toBe(true);
    });

    test('ポップアップに浸水範囲でない旨の注記が含まれる', async ({ page }) => {
        const contents = await getCoastPopupContents(page);
        expect(contents.some(c => c.includes('浸水範囲'))).toBe(true);
    });
});

// ── Phase B: class20 なし（affected_areas なし）の場合はフォールバック ────────

test.describe('/live — Phase B: affected_areas なし時のフォールバック', () => {
    const STORM_SURGE_NO_AREAS = {
        status: 'ok', evaluated: true,
        summary: { active: true, warning_area_count: 1 },
        areas: [
            {
                id: 'storm_surge-0', label: '茨城県', detail: '高潮警報',
                level: 'danger', type: 'storm_surge', source: 'mock',
                lat: 36.3418, lng: 140.4468,
                pref_code: '080000',
                // affected_areas なし → 市区町村リストを表示しない
            },
        ],
        updated_at: null,
    };

    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_NO_AREAS });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
    });

    test('affected_areas がない場合も沿岸部ハイライト円が表示される（Phase A フォールバック）', async ({ page }) => {
        await expect(page.locator('.storm-surge-coast-ring')).toHaveCount(1, { timeout: 5000 });
    });

    test('affected_areas がない場合でもポップアップは表示される', async ({ page }) => {
        // クリックではなく Leaflet レイヤーのポップアップ内容を直接検証
        const contents = await getCoastPopupContents(page);
        expect(contents.some(c => c.includes('高潮警報対象の沿岸部'))).toBe(true);
    });
});

// ── Phase C: 浸水想定区域案内ヒント ─────────────────────────────────────────

test.describe('/live — Phase C: 高潮浸水想定区域ヒント', () => {
    test('高潮警報がある場合、浸水想定区域ヒントが表示される', async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
        await expect(page.locator('#storm-surge-coast-hint')).toBeVisible({ timeout: 5000 });
    });

    test('高潮警報がない場合、ヒントは非表示', async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_NONE });
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
        await expect(page.locator('#storm-surge-coast-hint')).toBeHidden({ timeout: 3000 });
    });

    test('ヒントに「避難ナビ」リンクが含まれる', async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
        await expect(page.locator('#storm-surge-coast-hint .live-surge-hint-link')).toBeVisible({ timeout: 3000 });
    });

    test('高潮トグル OFF でヒントも非表示になる', async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(400);
        await expect(page.locator('#storm-surge-coast-hint')).toBeVisible({ timeout: 5000 });
        await page.locator('#toggle-storm-surge').uncheck();
        await expect(page.locator('#storm-surge-coast-hint')).toBeHidden({ timeout: 3000 });
    });
});

// ── 凡例パネル（高潮タブ） ───────────────────────────────────────────────────

test.describe('/live — 凡例パネル（高潮タブ）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        // 凡例ボタンをクリック
        await page.locator('#live-legend-toggle').click();
    });

    test('凡例パネルに高潮タブが存在する', async ({ page }) => {
        await expect(page.locator('.llp-tab[data-tab="storm-surge"]')).toBeVisible({ timeout: 3000 });
    });

    test('高潮タブをクリックすると高潮凡例が表示される', async ({ page }) => {
        await page.locator('.llp-tab[data-tab="storm-surge"]').click();
        await expect(page.locator('.llp-body[data-body="storm-surge"]')).toBeVisible({ timeout: 3000 });
    });

    test('高潮凡例に「高潮警報対象の沿岸部」が含まれる', async ({ page }) => {
        await page.locator('.llp-tab[data-tab="storm-surge"]').click();
        await expect(page.locator('.llp-body[data-body="storm-surge"]')).toContainText('高潮警報対象の沿岸部', { timeout: 3000 });
    });

    test('高潮凡例に浸水範囲でない旨の注記がある', async ({ page }) => {
        await page.locator('.llp-tab[data-tab="storm-surge"]').click();
        await expect(page.locator('.llp-body[data-body="storm-surge"]')).toContainText('浸水範囲', { timeout: 3000 });
    });
});

// ── 津波警報マーカー ─────────────────────────────────────────────────────────

test.describe('/live — 津波警報マーカー表示', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page, { tsunamiResp: TSUNAMI_WARNING, stormSurgeResp: STORM_SURGE_NONE });
        await page.goto('/live.html');
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(500);
    });

    test('津波警報がアラートカードに表示される', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toContainText('津波警報', { timeout: 6000 });
    });

    test('津波トグル OFF でマーカーが消える（あれば）', async ({ page }) => {
        // 「東京湾内湾」は座標テーブルに含まれるのでマーカーが出る
        await page.locator('#toggle-tsunami').uncheck();
        // OFF 後マーカーが 0件になることを確認（高潮なしなので）
        await expect(page.locator('.leaflet-marker-icon[title="東京湾内湾"]')).toHaveCount(0, { timeout: 3000 });
    });
});

// ── ステータスバー ────────────────────────────────────────────────────────────

test.describe('/live — ステータスバー（高潮）', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-status-bar').waitFor({ timeout: 8000 });
    });

    test('ステータスバーに高潮項目が存在する', async ({ page }) => {
        await expect(page.locator('#live-status-bar')).toContainText('高潮', { timeout: 6000 });
    });
});

// ── console.error 検査 ────────────────────────────────────────────────────────

test.describe('/live — コンソールエラーなし（高潮警報あり）', () => {
    test('高潮警報あり時に console.error が出ない', async ({ page }) => {
        const errors = [];
        const httpErrors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        page.on('response', res => { if (res.status() >= 400) httpErrors.push(`${res.status()} ${res.url()}`); });
        await mockBase(page, { tsunamiResp: TSUNAMI_NONE, stormSurgeResp: STORM_SURGE_WARNING });
        await Promise.all([
            page.waitForRequest('/api/live/storm_surge/warnings'),
            page.goto('/live.html'),
        ]);
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 8000 });
        await page.waitForTimeout(500);
        const serious = errors.filter(e =>
            !e.includes('favicon') && !e.includes('net::ERR') && !e.includes('CORS')
        );
        expect(serious).toHaveLength(0);
        expect(httpErrors).toEqual([]);  // 未 mock API の 404 等が残っていないこと
    });
});
