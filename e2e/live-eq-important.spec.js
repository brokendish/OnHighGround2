'use strict';
/**
 * live-eq-important.spec.js — Phase 8-A.1 重要地震固定表示・JMA fallback明示 確認
 *
 * /api/live/earthquakes/history をモックして以下を検証する:
 *   - M5以上 / 震度5弱以上の地震が「重要地震」セクションに固定表示される
 *   - 小規模地震が増えても重要地震が埋もれない
 *   - JMA fallback 時に「JMA fallback / 市区町村震度なし」が表示される
 *   - P2P 成功時に fallback 表示が出ない
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

// ── モックデータ ──────────────────────────────────────────────────────────────

const TODAY = new Date().toISOString().slice(0, 10);

// 重要地震 1 件 + 小規模地震 4 件（P2P）
const EQ_HISTORY_WITH_IMPORTANT_P2P = {
    days: 3,
    source: 'p2p',
    fallback: false,
    municipalityIntensityAvailable: true,
    updated_at: `${TODAY}T10:00:00+09:00`,
    count: 5,
    items: [
        {
            event_id:       'eq-important-001',
            occurred_at:    `${TODAY}T07:30:00+09:00`,
            epicenter_name: '岩手県沖',
            lat:            39.5,
            lng:            142.0,
            magnitude:      7.2,
            max_intensity:  '不明',
            isImportant:    true,
            importantReasons: ['magnitude_ge_5'],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
        {
            event_id:       'eq-small-001',
            occurred_at:    `${TODAY}T08:22:00+09:00`,
            epicenter_name: '岩手県沖',
            lat:            39.4,
            lng:            141.9,
            magnitude:      3.1,
            max_intensity:  '2',
            isImportant:    false,
            importantReasons: [],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
        {
            event_id:       'eq-small-002',
            occurred_at:    `${TODAY}T09:01:00+09:00`,
            epicenter_name: '岩手県沖',
            lat:            39.3,
            lng:            142.1,
            magnitude:      2.9,
            max_intensity:  '1',
            isImportant:    false,
            importantReasons: [],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
        {
            event_id:       'eq-small-003',
            occurred_at:    `${TODAY}T09:08:00+09:00`,
            epicenter_name: '岩手県沖',
            lat:            39.5,
            lng:            142.0,
            magnitude:      3.9,
            max_intensity:  '3',
            isImportant:    false,
            importantReasons: [],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
        {
            event_id:       'eq-small-004',
            occurred_at:    `${TODAY}T10:10:00+09:00`,
            epicenter_name: '岩手県沖',
            lat:            39.6,
            lng:            141.8,
            magnitude:      4.0,
            max_intensity:  '3',
            isImportant:    false,
            importantReasons: [],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
        {
            event_id:       'eq-intensity-important-001',
            occurred_at:    `${TODAY}T10:30:00+09:00`,
            epicenter_name: '能登地方',
            lat:            37.2,
            lng:            136.8,
            magnitude:      4.4,
            max_intensity:  '5弱',
            isImportant:    true,
            importantReasons: ['intensity_ge_5weak'],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
    ],
};

// JMA fallback 応答（市区町村震度なし）
const EQ_HISTORY_JMA_FALLBACK = {
    days: 3,
    source: 'jma',
    fallback: true,
    municipalityIntensityAvailable: false,
    updated_at: `${TODAY}T10:00:00+09:00`,
    count: 3,
    items: [
        {
            event_id:       'jma-001',
            occurred_at:    `${TODAY}T07:30:00+09:00`,
            epicenter_name: '岩手県沖',
            lat:            39.5,
            lng:            142.0,
            magnitude:      7.2,
            max_intensity:  'unknown',
            isImportant:    true,
            importantReasons: ['magnitude_ge_5'],
            municipalityIntensityAvailable: false,
            source: 'jma',
        },
        {
            event_id:       'jma-002',
            occurred_at:    `${TODAY}T08:00:00+09:00`,
            epicenter_name: '青森県東方沖',
            lat:            40.8,
            lng:            142.5,
            magnitude:      5.3,
            max_intensity:  '4',
            isImportant:    true,
            importantReasons: ['magnitude_ge_5'],
            municipalityIntensityAvailable: false,
            source: 'jma',
        },
    ],
};

// 小規模地震のみ（重要地震なし）
const EQ_HISTORY_NO_IMPORTANT = {
    days: 3,
    source: 'p2p',
    fallback: false,
    municipalityIntensityAvailable: true,
    updated_at: `${TODAY}T10:00:00+09:00`,
    count: 2,
    items: [
        {
            event_id:       'eq-tiny-001',
            occurred_at:    `${TODAY}T08:00:00+09:00`,
            epicenter_name: '千葉県北東部',
            lat:            35.7,
            lng:            140.5,
            magnitude:      2.5,
            max_intensity:  '1',
            isImportant:    false,
            importantReasons: [],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
        {
            event_id:       'eq-tiny-002',
            occurred_at:    `${TODAY}T09:00:00+09:00`,
            epicenter_name: '東京湾',
            lat:            35.5,
            lng:            139.8,
            magnitude:      3.4,
            max_intensity:  '3',
            isImportant:    false,
            importantReasons: [],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
        {
            event_id:       'eq-yesterday-001',
            occurred_at:    new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(),
            epicenter_name: '茨城県沖',
            lat:            36.5,
            lng:            141.1,
            magnitude:      3.0,
            max_intensity:  '2',
            isImportant:    false,
            importantReasons: [],
            municipalityIntensityAvailable: true,
            source: 'p2p',
        },
    ],
};

const TSUNAMI_NONE = {
    observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '',
};
const STORM_SURGE_NONE = {
    status: 'ok', evaluated: true, summary: { active: false }, areas: [],
};
const SUMMARY_NO_BIG_EQ = {
    updated_at: `${TODAY}T10:00:00+09:00`,
    status: 'ok',
    rain:       { status: 'ok', evaluated: false, summary: { strong_rain_detected: null }, areas: [] },
    kikikuru:   { status: 'ok', evaluated: false, summary: { danger_detected: null },      areas: [] },
    earthquake: { status: 'ok', evaluated: true,  summary: { count_24h: 1, m5_count: 0, m6_count: 0 }, areas: [] },
    tsunami:    { status: 'cleared', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] },
    storm_surge: { status: 'ok', evaluated: true, summary: { active: false }, areas: [] },
    dangerous_areas: [],
    integrated_dangerous_regions: [],
};
const SUMMARY_WITH_M5 = {
    ...SUMMARY_NO_BIG_EQ,
    earthquake: { status: 'ok', evaluated: true, summary: { count_24h: 6, m5_count: 1, m6_count: 1 }, areas: [] },
};
const RAIN_TIMES = {
    basetime: '20260601000000',
    times: [{ offset_minutes: 0, validtime: '20260601000000',
              tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260601000000/none/20260601000000/surf/hrpns/{z}/{x}/{y}.png' }],
};
const SUN_MOON = {
    location: '東京', date: TODAY,
    sunrise: '04:30', sunset: '19:00',
    moonrise: '12:00', moonset: '00:00',
    moon_phase: 1.0, moon_phase_name: '新月',
};

async function mockBase(page, { eqHistory, summary = SUMMARY_WITH_M5 }) {
    await page.route('/data/municipality_coords.json', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/api/live/sun-moon', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUN_MOON) }));
    await page.route('/api/live/tide/stations', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/summary', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(summary) }));
    await page.route('/api/live/storm_surge/**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STORM_SURGE_NONE) }));
    await page.route('/api/live/trains/summary**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', items: [], scope: {}, stale: false }) }));
    await page.route('/api/live/road-traffic/summary**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', items: [], scope: {}, stale: false }) }));
    await page.route('/api/live/earthquakes/**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(eqHistory) }));
    // 旧エンドポイントフォールバック（念のため）
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

// ── テスト: 重要地震固定表示 ──────────────────────────────────────────────────

test.describe('/live — 重要地震固定表示（P2P）', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, { eqHistory: EQ_HISTORY_WITH_IMPORTANT_P2P });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('重要地震セクションが表示される', async ({ page }) => {
        const section = page.locator('.lac-eq-important-section');
        await expect(section).toBeVisible({ timeout: 5000 });
    });

    test('重要地震セクションに「重要地震」ヘッダーが表示される', async ({ page }) => {
        await expect(page.locator('.lac-eq-section-header')).toContainText('重要地震', { timeout: 5000 });
    });

    test('重要地震（M7.2）が固定表示される', async ({ page }) => {
        const section = page.locator('.lac-eq-important-section');
        await expect(section).toContainText('岩手県沖', { timeout: 5000 });
        await expect(section).toContainText('M7.2');
    });

    test('震度5弱以上の地震も重要地震に含まれる', async ({ page }) => {
        const section = page.locator('.lac-eq-important-section');
        await expect(section).toContainText('能登地方', { timeout: 5000 });
        await expect(section).toContainText('震度5弱');
    });

    test('重要地震に「最大震度不明」が表示される（unknownのまま露出しない）', async ({ page }) => {
        const section = page.locator('.lac-eq-important-section');
        await expect(section).not.toContainText('unknown', { timeout: 5000 });
        await expect(section).toContainText('最大震度不明');
    });

    test('小規模地震4件があっても重要地震が先頭に固定される', async ({ page }) => {
        const section = page.locator('.lac-eq-important-section');
        await expect(section).toBeVisible({ timeout: 5000 });
        // 重要地震セクションが存在し、歴史トグルより前にある
        const card = page.locator('#live-alert-card');
        const html = await card.innerHTML();
        const importantIdx = html.indexOf('lac-eq-important-section');
        const toggleIdx    = html.indexOf('lac-eq-toggle');
        expect(importantIdx).toBeGreaterThan(-1);
        expect(importantIdx).toBeLessThan(toggleIdx);
    });

    test('P2P成功時にJMA fallbackノートが表示されない', async ({ page }) => {
        await page.waitForTimeout(500);
        await expect(page.locator('.lac-eq-fallback-note')).toHaveCount(0);
    });

    test('重要地震アイテムをクリックすると地図ポップアップが表示される', async ({ page }) => {
        const item = page.locator('.lac-eq-important-item.lac-eq-clickable').first();
        await expect(item).toBeVisible({ timeout: 5000 });
        await item.click();
        await expect(page.locator('.leaflet-popup')).toBeVisible({ timeout: 3000 });
        const popupText = await page.locator('.leaflet-popup-content').textContent();
        expect(popupText).toContain('岩手県沖');
    });

    test('地震履歴トグルも引き続き表示される', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 5000 });
    });

});

// ── テスト: JMA fallback 表示 ────────────────────────────────────────────────

test.describe('/live — JMA fallback 表示', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, {
            eqHistory: EQ_HISTORY_JMA_FALLBACK,
            summary: SUMMARY_WITH_M5,
        });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('重要地震セクションが表示される', async ({ page }) => {
        await expect(page.locator('.lac-eq-important-section')).toBeVisible({ timeout: 5000 });
    });

    test('JMA fallback 時に「JMA fallback / 市区町村震度なし」が表示される', async ({ page }) => {
        await expect(page.locator('.lac-eq-fallback-note').first()).toBeVisible({ timeout: 5000 });
        await expect(page.locator('.lac-eq-fallback-note').first()).toContainText('JMA fallback');
        await expect(page.locator('.lac-eq-fallback-note').first()).toContainText('市区町村震度なし');
    });

    test('JMA fallback 時に「unknown」がそのままユーザーに見えない', async ({ page }) => {
        const card = page.locator('#live-alert-card');
        await expect(card).toBeVisible({ timeout: 5000 });
        const text = await card.textContent();
        expect(text).not.toContain('unknown');
    });

    test('JMA fallback でも地震履歴が表示される', async ({ page }) => {
        const section = page.locator('.lac-eq-important-section');
        await expect(section).toContainText('岩手県沖', { timeout: 5000 });
    });

});

// ── テスト: 重要地震なし ─────────────────────────────────────────────────────

test.describe('/live — 重要地震なし（小規模地震のみ）', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, {
            eqHistory: EQ_HISTORY_NO_IMPORTANT,
            summary: SUMMARY_NO_BIG_EQ,
        });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('重要地震セクションが表示されない', async ({ page }) => {
        await page.waitForTimeout(500);
        await expect(page.locator('.lac-eq-important-section')).toHaveCount(0);
    });

    test('地震履歴トグルが表示される', async ({ page }) => {
        const toggle = page.locator('[data-action="eq-toggle"]');
        await expect(toggle).toBeVisible({ timeout: 5000 });
    });

});

// ── テスト: 重要地震マーカー ─────────────────────────────────────────────────

test.describe('/live — 重要地震マーカー', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, { eqHistory: EQ_HISTORY_WITH_IMPORTANT_P2P });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(500);
    });

    test('地震データが liveLayers に読み込まれる', async ({ page }) => {
        const count = await page.evaluate(() =>
            window.liveLayers?.earthquake?.getData?.()?.length ?? 0);
        expect(count).toBe(6);
    });

    test('isImportant フラグが正しく設定される', async ({ page }) => {
        const importantCount = await page.evaluate(() =>
            (window.liveLayers?.earthquake?.getData?.() ?? [])
                .filter(e => e.isImportant === true).length);
        expect(importantCount).toBe(2);
    });

    test('getFallback() が false を返す（P2P成功時）', async ({ page }) => {
        const isFallback = await page.evaluate(() =>
            window.liveLayers?.earthquake?.getFallback?.() ?? null);
        expect(isFallback).toBe(false);
    });

    test('getMuniAvailable() が true を返す（P2P成功時）', async ({ page }) => {
        const isAvail = await page.evaluate(() =>
            window.liveLayers?.earthquake?.getMuniAvailable?.() ?? null);
        expect(isAvail).toBe(true);
    });

    test('重要地震マーカークリックでポップアップに「重要地震」が表示される', async ({ page }) => {
        const opened = await page.evaluate(() => {
            let target = null;
            window.liveMap.eachLayer(layer => {
                const popup = layer.getPopup?.();
                const content = popup?.getContent?.();
                if (!target && typeof content === 'string' && content.includes('重要地震')) {
                    target = layer;
                }
            });
            if (!target) return false;
            target.openPopup();
            return true;
        });
        expect(opened).toBe(true);
        await expect(page.locator('.leaflet-popup')).toContainText('重要地震', { timeout: 3000 });
    });

});

// ── テスト: JMA fallback マーカー ────────────────────────────────────────────

test.describe('/live — JMA fallback マーカー', () => {

    test.beforeEach(async ({ page }) => {
        await mockBase(page, {
            eqHistory: EQ_HISTORY_JMA_FALLBACK,
            summary:   SUMMARY_WITH_M5,
        });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(500);
    });

    test('getFallback() が true を返す（JMA fallback時）', async ({ page }) => {
        const isFallback = await page.evaluate(() =>
            window.liveLayers?.earthquake?.getFallback?.() ?? null);
        expect(isFallback).toBe(true);
    });

    test('getMuniAvailable() が false を返す（JMA fallback時）', async ({ page }) => {
        const isAvail = await page.evaluate(() =>
            window.liveLayers?.earthquake?.getMuniAvailable?.() ?? null);
        expect(isAvail).toBe(false);
    });

    test('JMA fallback 重要地震マーカーのポップアップに市区町村震度なしが表示される', async ({ page }) => {
        const opened = await page.evaluate(() => {
            let target = null;
            window.liveMap.eachLayer(layer => {
                const popup = layer.getPopup?.();
                const content = popup?.getContent?.();
                if (!target && typeof content === 'string' && content.includes('市区町村震度なし')) {
                    target = layer;
                }
            });
            if (!target) return false;
            target.openPopup();
            return true;
        });
        expect(opened).toBe(true);
        await expect(page.locator('.leaflet-popup-content')).toContainText('市区町村震度なし');
    });

});

// ── テスト: モバイル表示 ─────────────────────────────────────────────────────

test.describe('/live — モバイル幅での重要地震表示', () => {

    test.beforeEach(async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await mockBase(page, { eqHistory: EQ_HISTORY_WITH_IMPORTANT_P2P });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('モバイルでボトムシートを開いて重要地震セクションが見える', async ({ page }) => {
        await page.locator('.sheet-handle').click();
        await expect(page.locator('#live-alert-card')).toHaveClass(/is-expanded/, { timeout: 3000 });
        await expect(page.locator('.lac-eq-important-section')).toBeVisible({ timeout: 5000 });
    });

    test('モバイルで横スクロールが発生しない', async ({ page }) => {
        await page.locator('.sheet-handle').click();
        await expect(page.locator('#live-alert-card')).toHaveClass(/is-expanded/, { timeout: 3000 });
        const overflows = await page.evaluate(() => {
            const body = document.body;
            const card = document.getElementById('live-alert-card');
            return {
                bodyScrollWidth:   body.scrollWidth,
                bodyClientWidth:   body.clientWidth,
                cardScrollWidth:   card ? card.scrollWidth : 0,
                cardClientWidth:   card ? card.clientWidth : 0,
            };
        });
        expect(overflows.bodyScrollWidth).toBeLessThanOrEqual(overflows.bodyClientWidth + 1);
        expect(overflows.cardScrollWidth).toBeLessThanOrEqual(overflows.cardClientWidth + 1);
    });

    test('console.error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        const pageErrors = [];
        page.on('pageerror', err => pageErrors.push(err.message));
        await page.reload();
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(500);
        expect(pageErrors).toHaveLength(0);
        expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
    });

});
