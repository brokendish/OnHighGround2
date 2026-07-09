'use strict';
/**
 * live-eq-history-select.spec.js — Phase 8-A.4
 *
 * 検証項目:
 *   - 同一地震が統合表示され update_count が表示される
 *   - 初期選択が最新重要地震になる（市区町村マーカーが描画される）
 *   - 履歴クリックで市区町村マーカーが切り替わる
 *   - 選択行に lac-eq-selected クラスが付く
 *   - 非選択地震の市区町村マーカーは表示されない
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const TODAY = new Date().toISOString().slice(0, 10);

// ── 座標辞書モック ─────────────────────────────────────────────────────────────

const COORDS_MOCK = {
    '千葉県|木更津市':   { lat: 35.376, lon: 139.916 },
    '千葉県|市原市':     { lat: 35.497, lon: 140.116 },
    '東京都|江東区':     { lat: 35.672, lon: 139.817 },
    '神奈川県|横浜市':   { lat: 35.443, lon: 139.638 },
    '神奈川県|川崎市':   { lat: 35.530, lon: 139.702 },
};

// ── モックデータ: 2 件の重要地震（points の件数が異なる） ─────────────────────

const EQ_TWO_IMPORTANT = {
    days: 3,
    source: 'p2p',
    fallback: false,
    municipalityIntensityAvailable: true,
    updated_at: `${TODAY}T10:00:00+09:00`,
    count: 2,
    items: [
        {
            event_id:       'eq-a',
            occurred_at:    `${TODAY}T09:00:00+09:00`,
            epicenter_name: '千葉県北東部',
            lat:            35.7,
            lng:            140.5,
            magnitude:      5.5,
            max_intensity:  '4',
            depth_km:       30,
            isImportant:    true,
            importantReasons: ['magnitude_ge_5'],
            municipalityIntensityAvailable: true,
            source:         'p2p',
            points: [
                { pref: '千葉県', addr: '木更津市', isArea: false, scale: 40 },
                { pref: '千葉県', addr: '市原市',   isArea: false, scale: 30 },
                { pref: '東京都', addr: '江東区',   isArea: false, scale: 30 },
            ],
        },
        {
            event_id:       'eq-b',
            occurred_at:    `${TODAY}T07:00:00+09:00`,
            epicenter_name: '神奈川県西部',
            lat:            35.4,
            lng:            139.3,
            magnitude:      5.1,
            max_intensity:  '3',
            depth_km:       20,
            isImportant:    true,
            importantReasons: ['magnitude_ge_5'],
            municipalityIntensityAvailable: true,
            source:         'p2p',
            points: [
                { pref: '神奈川県', addr: '横浜市', isArea: false, scale: 30 },
                { pref: '神奈川県', addr: '川崎市', isArea: false, scale: 30 },
            ],
        },
    ],
};

// ── モックデータ: update_count あり ──────────────────────────────────────────

const EQ_WITH_UPDATE_COUNT = {
    days: 3,
    source: 'p2p',
    fallback: false,
    municipalityIntensityAvailable: true,
    updated_at: `${TODAY}T10:00:00+09:00`,
    count: 2,
    items: [
        {
            event_id:       'eq-merged-001',
            occurred_at:    `${TODAY}T09:30:00+09:00`,
            epicenter_name: '山梨県東部・富士五湖',
            lat:            35.5,
            lng:            138.8,
            magnitude:      5.6,
            max_intensity:  '6弱',
            isImportant:    true,
            importantReasons: ['magnitude_ge_5', 'intensity_ge_5weak'],
            municipalityIntensityAvailable: true,
            update_count:   3,
            source:         'p2p',
            points: [],
        },
        {
            event_id:       'eq-small-001',
            occurred_at:    `${TODAY}T08:00:00+09:00`,
            epicenter_name: '千葉県北東部',
            lat:            35.7,
            lng:            140.5,
            magnitude:      2.8,
            max_intensity:  '1',
            isImportant:    false,
            importantReasons: [],
            municipalityIntensityAvailable: true,
            update_count:   2,
            source:         'p2p',
            points: [],
        },
    ],
};

// ── 共通モックデータ ──────────────────────────────────────────────────────────

const TSUNAMI_NONE    = { observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const STORM_SURGE_NONE = { status: 'ok', evaluated: true, summary: { active: false }, areas: [] };
const RAIN_TIMES      = {
    basetime: '20260601000000',
    times: [{ offset_minutes: 0, validtime: '20260601000000',
              tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260601000000/none/20260601000000/surf/hrpns/{z}/{x}/{y}.png' }],
};
const SUN_MOON        = {
    location: '東京', date: TODAY,
    sunrise: '04:30', sunset: '19:00',
    moonrise: '12:00', moonset: '00:00',
    moon_phase: 1.0, moon_phase_name: '新月',
};
const SUMMARY_BASE    = {
    updated_at: `${TODAY}T10:00:00+09:00`,
    status: 'ok',
    rain:       { status: 'ok', evaluated: false, summary: { strong_rain_detected: null }, areas: [] },
    kikikuru:   { status: 'ok', evaluated: false, summary: { danger_detected: null },      areas: [] },
    earthquake: { status: 'ok', evaluated: true,  summary: { count_24h: 2, m5_count: 1, m6_count: 0 }, areas: [] },
    tsunami:    { status: 'cleared', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] },
    storm_surge: { status: 'ok', evaluated: true, summary: { active: false }, areas: [] },
    dangerous_areas: [],
    integrated_dangerous_regions: [],
};

async function mockBase(page, { eqHistory, coords = COORDS_MOCK }) {
    await page.route('/data/municipality_coords.json', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(coords) }));
    await page.route('/api/live/weather/jma/prefectures**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unavailable', source: 'Open-Meteo Forecast', forecast_time: null, fetched_at: null, cache_status: 'unavailable', items: [] }) }));
    await page.route('/api/live/sun-moon', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUN_MOON) }));
    await page.route('/api/live/tide/stations', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/summary', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUMMARY_BASE) }));
    await page.route('/api/live/storm_surge/**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STORM_SURGE_NONE) }));
    await page.route('/api/live/trains/summary**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', items: [], scope: {}, stale: false }) }));
    await page.route('/api/live/road-traffic/summary**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', items: [], scope: {}, stale: false }) }));
    await page.route('/api/live/earthquakes/**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(eqHistory) }));
    await page.route('/api/earthquakes**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, items: [] }) }));
    await page.route('/api/tsunami/**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_NONE) }));
    await page.route('/api/weather/rain/tile/times', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/layers/railways/kanto_railways.geojson', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ type: 'FeatureCollection', features: [] }) }));
    await page.route('/layers/roads/kanto_roads_main.geojson', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ type: 'FeatureCollection', features: [] }) }));
    await page.route('**/jmatile/**', r => {
        if (r.request().url().includes('targetTimes.json')) {
            return r.fulfill({
                status: 200, contentType: 'application/json',
                body: JSON.stringify([{ basetime: '20260601000000', validtime: '20260601000000', member: 'immed0', elements: ['land'] }]),
            });
        }
        return r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG });
    });
    await page.route('**/jma.go.jp/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
}

// ── テスト: update_count 表示 ─────────────────────────────────────────────────

test.describe('/live — 地震履歴 update_count 表示', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, { eqHistory: EQ_WITH_UPDATE_COUNT });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('update_count > 1 の重要地震に「更新N件」が表示される', async ({ page }) => {
        const section = page.locator('.lac-eq-important-section');
        await expect(section).toBeVisible({ timeout: 5000 });
        await expect(section.locator('.lac-eq-update-count').first()).toContainText('更新3件', { timeout: 3000 });
    });

    test('地震履歴トグルを開くと update_count 表示が見える', async ({ page }) => {
        // トグルをクリックして履歴を展開
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 5000 });
        await toggle.click();
        await expect(page.locator('.lac-eq-list-wrap')).toBeVisible({ timeout: 2000 });

        // 小規模地震の update_count も表示される
        const updateCounts = page.locator('.lac-eq-update-count');
        const count = await updateCounts.count();
        expect(count).toBeGreaterThanOrEqual(1);
    });
});

// ── テスト: 初期選択 ──────────────────────────────────────────────────────────

test.describe('/live — 地震履歴 初期選択', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, { eqHistory: EQ_TWO_IMPORTANT });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(800); // 座標辞書ロード + 初期描画を待つ
    });

    test('初期表示で最初の重要地震が自動選択される（市区町村マーカー 3 件）', async ({ page }) => {
        // eq-a（最初・最新の重要地震）の points 3 件が描画される
        const markers = page.locator('.earthquake-intensity-marker');
        await expect(markers).toHaveCount(3, { timeout: 5000 });
    });

    test('初期選択の重要地震アイテムに lac-eq-selected クラスが付く', async ({ page }) => {
        const items = page.locator('.lac-eq-important-item');
        const firstItem = items.first();
        await expect(firstItem).toHaveClass(/lac-eq-selected/, { timeout: 5000 });
    });

    test('非選択の重要地震アイテムには lac-eq-selected クラスが付かない', async ({ page }) => {
        const items = page.locator('.lac-eq-important-item');
        // 2番目のアイテムは選択されていない
        await expect(items.nth(1)).not.toHaveClass(/lac-eq-selected/, { timeout: 5000 });
    });
});

// ── テスト: 履歴クリックで市区町村マーカー切り替え ────────────────────────────

test.describe('/live — 地震履歴クリック切り替え', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, { eqHistory: EQ_TWO_IMPORTANT });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(800); // 座標辞書ロード + 初期描画を待つ
    });

    test('初期: eq-a の市区町村マーカー 3 件が表示される', async ({ page }) => {
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3, { timeout: 5000 });
    });

    test('2番目の重要地震クリックで市区町村マーカーが 2 件に切り替わる', async ({ page }) => {
        // 初期確認
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3, { timeout: 5000 });

        // 2番目の重要地震アイテムをクリック
        const items = page.locator('.lac-eq-important-item.lac-eq-clickable');
        await items.nth(1).click();
        await page.waitForTimeout(600);

        // eq-b の points 2 件に切り替わる
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(2, { timeout: 3000 });
    });

    test('クリック後、選択行に lac-eq-selected が付き、元の選択が外れる', async ({ page }) => {
        const items = page.locator('.lac-eq-important-item.lac-eq-clickable');
        // 初期: 1番目が選択
        await expect(items.first()).toHaveClass(/lac-eq-selected/, { timeout: 5000 });

        // 2番目クリック
        await items.nth(1).click();
        await page.waitForTimeout(300);

        // 選択状態の切り替え
        await expect(items.nth(1)).toHaveClass(/lac-eq-selected/);
        await expect(items.first()).not.toHaveClass(/lac-eq-selected/);
    });

    test('クリック後に console.error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

        await mockBase(page, { eqHistory: EQ_TWO_IMPORTANT });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(800);

        const items = page.locator('.lac-eq-important-item.lac-eq-clickable');
        await items.nth(1).click();
        await page.waitForTimeout(500);

        expect(errors).toHaveLength(0);
    });
});

// ── テスト: モバイルでの操作 ──────────────────────────────────────────────────

test.describe('/live — 地震履歴選択 モバイル', () => {

    test.use({ viewport: { width: 390, height: 844 } });

    test('モバイルで selectById 呼び出し後に市区町村マーカーが切り替わる', async ({ page }) => {
        await mockBase(page, { eqHistory: EQ_TWO_IMPORTANT });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(800);

        // 初期: eq-a の 3 件
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3, { timeout: 5000 });

        // モバイルではパネル外のためJS経由で selectById を直接呼ぶ
        await page.evaluate(() => {
            window.liveLayers.earthquake.selectById('eq-b');
        });
        await page.waitForTimeout(600);

        // eq-b の 2 件に切り替わる
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(2, { timeout: 3000 });
    });

    test('モバイルで横スクロールが発生しない', async ({ page }) => {
        await mockBase(page, { eqHistory: EQ_TWO_IMPORTANT });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        const scrollWidth  = await page.evaluate(() => document.documentElement.scrollWidth);
        const clientWidth  = await page.evaluate(() => document.documentElement.clientWidth);
        expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 5);
    });
});

// ── テスト: 多件数地震でも選択した1件のマーカーのみ表示 ─────────────────────────

// 座標辞書を拡張（5地震分の地点を全てカバー）
const COORDS_MULTI = Object.assign({}, COORDS_MOCK, {
    '埼玉県|さいたま市': { lat: 35.862, lon: 139.645 },
    '埼玉県|川越市':     { lat: 35.925, lon: 139.485 },
    '埼玉県|越谷市':     { lat: 35.888, lon: 139.790 },
    '静岡県|浜松市':     { lat: 34.710, lon: 137.726 },
    '静岡県|静岡市':     { lat: 34.977, lon: 138.383 },
});

// 5件の地震: 各 points 件数が異なる（eq-p1=3, eq-p2=2, eq-p3=2, eq-p4=2, eq-p5=0）
function makeMultiHistory() {
    return {
        days: 3,
        source: 'p2p',
        fallback: false,
        municipalityIntensityAvailable: true,
        updated_at: `${TODAY}T10:00:00+09:00`,
        count: 5,
        items: [
            {
                event_id: 'multi-a',
                occurred_at: `${TODAY}T09:00:00+09:00`,
                epicenter_name: '千葉県北東部',
                lat: 35.7, lng: 140.5,
                magnitude: 5.5, max_intensity: '4',
                isImportant: true, importantReasons: ['magnitude_ge_5'],
                municipalityIntensityAvailable: true, source: 'p2p',
                points: [
                    { pref: '千葉県', addr: '木更津市', isArea: false, scale: 40 },
                    { pref: '千葉県', addr: '市原市',   isArea: false, scale: 30 },
                    { pref: '東京都', addr: '江東区',   isArea: false, scale: 30 },
                ],
            },
            {
                event_id: 'multi-b',
                occurred_at: `${TODAY}T08:00:00+09:00`,
                epicenter_name: '神奈川県西部',
                lat: 35.4, lng: 139.3,
                magnitude: 5.1, max_intensity: '3',
                isImportant: true, importantReasons: ['magnitude_ge_5'],
                municipalityIntensityAvailable: true, source: 'p2p',
                points: [
                    { pref: '神奈川県', addr: '横浜市', isArea: false, scale: 30 },
                    { pref: '神奈川県', addr: '川崎市', isArea: false, scale: 30 },
                ],
            },
            {
                event_id: 'multi-c',
                occurred_at: `${TODAY}T07:00:00+09:00`,
                epicenter_name: '埼玉県南部',
                lat: 35.9, lng: 139.6,
                magnitude: 3.2, max_intensity: '2',
                isImportant: false, importantReasons: [],
                municipalityIntensityAvailable: true, source: 'p2p',
                points: [
                    { pref: '埼玉県', addr: 'さいたま市', isArea: false, scale: 20 },
                    { pref: '埼玉県', addr: '川越市',     isArea: false, scale: 20 },
                ],
            },
            {
                event_id: 'multi-d',
                occurred_at: `${TODAY}T06:00:00+09:00`,
                epicenter_name: '静岡県西部',
                lat: 34.8, lng: 137.8,
                magnitude: 4.0, max_intensity: '2',
                isImportant: false, importantReasons: [],
                municipalityIntensityAvailable: true, source: 'p2p',
                points: [
                    { pref: '静岡県', addr: '浜松市', isArea: false, scale: 20 },
                    { pref: '静岡県', addr: '静岡市', isArea: false, scale: 20 },
                ],
            },
            {
                event_id: 'multi-e',
                occurred_at: `${TODAY}T05:00:00+09:00`,
                epicenter_name: '東京湾',
                lat: 35.5, lng: 139.8,
                magnitude: 2.5, max_intensity: '1',
                isImportant: false, importantReasons: [],
                municipalityIntensityAvailable: true, source: 'p2p',
                points: [],
            },
        ],
    };
}

test.describe('/live — 多件数地震: 選択地震のマーカーのみ表示', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, { eqHistory: makeMultiHistory(), coords: COORDS_MULTI });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(800);
    });

    test('初期表示: 最初の重要地震のマーカー 3 件のみ（全件描画しない）', async ({ page }) => {
        // multi-a (3 points) が選択される。他の地震の points は描画されない
        // もし全件描画なら 3+2+2+2+0=9 件になる
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3, { timeout: 5000 });
    });

    test('2番目の重要地震クリック: 前の地震のマーカーが消え、2 件に切り替わる', async ({ page }) => {
        // 初期: multi-a の 3 件
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3, { timeout: 5000 });

        // 2番目の重要地震 (multi-b) をクリック
        const items = page.locator('.lac-eq-important-item.lac-eq-clickable');
        await items.nth(1).click();
        await page.waitForTimeout(600);

        // multi-b の 2 件のみ表示（3+2=5 件にならない）
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(2, { timeout: 3000 });
    });

    test('JS経由で非重要地震を選択: そのマーカーに切り替わる', async ({ page }) => {
        // 初期: multi-a の 3 件
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3, { timeout: 5000 });

        // multi-c を選択（2 points: さいたま市・川越市）
        await page.evaluate(() => { window.liveLayers.earthquake.selectById('multi-c'); });
        await page.waitForTimeout(500);

        // multi-c の 2 件のみ（前の 3 件は消える）
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(2, { timeout: 3000 });
    });

    test('points なし地震を選択: マーカーがすべて消える（前の地震のマーカーも残らない）', async ({ page }) => {
        // 初期: multi-a の 3 件
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3, { timeout: 5000 });

        // multi-e を選択（points なし）
        await page.evaluate(() => { window.liveLayers.earthquake.selectById('multi-e'); });
        await page.waitForTimeout(500);

        // 市区町村マーカーはすべて消える
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0, { timeout: 3000 });
    });

    test('存在しない event_id で selectById: 前の地震のマーカーもクリアされる', async ({ page }) => {
        // 初期: multi-a の 3 件
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3, { timeout: 5000 });

        // 存在しない event_id で呼ぶ
        await page.evaluate(() => { window.liveLayers.earthquake.selectById('nonexistent-id'); });
        await page.waitForTimeout(500);

        // マーカーがすべて消える（前のマーカーが残らない）
        await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0, { timeout: 3000 });
    });
});
