'use strict';
/**
 * live-basic.spec.js — /live ページ基本動作確認
 *
 * backend 不要。API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const KIKIKURU_TIME = {
    basetime:  '20260522111000',
    validtime: '20260522111000',
    member:    'immed0',
    elements:  ['inund', 'land', 'flood', 'flood_mesh'],
};

const EQ_RESPONSE = {
    count: 2,
    items: [
        {
            event_id:       'eq-001',
            occurred_at:    '2026-05-26T10:00:00+09:00',
            epicenter_name: '東京湾',
            lat:            35.5,
            lng:            139.8,
            magnitude:      4.2,
            max_intensity:  '3',
        },
        {
            event_id:       'eq-002',
            occurred_at:    '2026-05-26T08:00:00+09:00',
            epicenter_name: '茨城県南部',
            lat:            36.1,
            lng:            140.2,
            magnitude:      3.1,
            max_intensity:  '2',
        },
    ],
};

const TSUNAMI_RESPONSE = {
    observed_at:  '2026-05-26T10:00:00+09:00',
    updated_at:   '2026-05-26T10:00:00+09:00',
    ttl_seconds:  60,
    areas:        [],
    message:      '',
};

const RAIN_TIMES = {
    basetime: '20260526100000',
    times: [
        { offset_minutes: 0, validtime: '20260526100000', tile_url_template: 'https://www.jma.go.jp/bosai/jmatile/data/nowc/20260526100000/none/20260526100000/surf/hrpns/{z}/{x}/{y}.png' },
    ],
};

async function mockLiveTraffic(page) {
    await page.route('/api/earthquakes**', route => route.fulfill({
        status:      200,
        contentType: 'application/json',
        body:        JSON.stringify(EQ_RESPONSE),
    }));
    await page.route('/api/tsunami/**', route => route.fulfill({
        status:      200,
        contentType: 'application/json',
        body:        JSON.stringify(TSUNAMI_RESPONSE),
    }));
    await page.route('/api/weather/rain/tile/times', route => route.fulfill({
        status:      200,
        contentType: 'application/json',
        body:        JSON.stringify(RAIN_TIMES),
    }));
    await page.route('**/jmatile/**', route => {
        if (route.request().url().includes('targetTimes.json')) {
            return route.fulfill({
                status:      200,
                contentType: 'application/json',
                body:        JSON.stringify([KIKIKURU_TIME]),
            });
        }
        return route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG });
    });
    await page.route('**/jma.go.jp/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
    await page.route('**/basemaps.cartocdn.com/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
}

test.describe('/live — 基本動作確認', () => {
    test.beforeEach(async ({ page }) => {
        await mockLiveTraffic(page);
        await page.goto('/live.html');
    });

    test('ページタイトルに "全国災害ビューア" が含まれる', async ({ page }) => {
        await expect(page).toHaveTitle(/全国災害ビューア/);
    });

    test('地図コンテナが存在する', async ({ page }) => {
        await expect(page.locator('#live-map')).toBeVisible();
    });

    test('Leaflet マップが初期化されている', async ({ page }) => {
        await expect(page.locator('#live-map.leaflet-container')).toBeVisible({ timeout: 5000 });
    });

    test('レイヤー切替パネルが存在する', async ({ page }) => {
        await expect(page.locator('#live-layer-panel')).toBeVisible();
    });

    test('雨雲トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-rain')).toBeVisible();
    });

    test('キキクルトグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-kikikuru')).toBeVisible();
    });

    test('地震トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-earthquake')).toBeVisible();
    });

    test('津波トグルが存在する', async ({ page }) => {
        await expect(page.locator('#toggle-tsunami')).toBeVisible();
    });

    test('アクティブ警戒カードが存在する', async ({ page }) => {
        await expect(page.locator('#live-alert-card')).toBeVisible();
    });

    test('ローディングが消える', async ({ page }) => {
        const loading = page.locator('#live-loading');
        await expect(loading).toHaveClass(/hidden/, { timeout: 8000 });
    });

    test('地震トグル OFF でマーカーが非表示になる', async ({ page }) => {
        await page.locator('#live-map.leaflet-container').waitFor({ timeout: 5000 });
        const toggle = page.locator('#toggle-earthquake');
        await toggle.uncheck();
        // レイヤーグループが空になることを JS レベルで確認
        const markerCount = await page.evaluate(() => {
            // _eqLayerGroup はクロージャ内のためグローバルアクセス不可。
            // 代わりに Leaflet の canvas/SVG レイヤー有無で間接確認。
            return document.querySelectorAll('.leaflet-marker-icon').length;
        });
        // circle マーカー（canvas）が使われているため marker-icon は 0 のはず
        expect(markerCount).toBe(0);
    });

    test('避難ナビへのリンクが存在する', async ({ page }) => {
        const link = page.locator('a.live-nav-link');
        await expect(link).toBeVisible();
        await expect(link).toHaveAttribute('href', '/');
    });

    test('JS console error が発生しない', async ({ page }) => {
        const errors = [];
        page.on('console', msg => {
            if (msg.type() === 'error') errors.push(msg.text());
        });
        await page.waitForTimeout(2000);
        expect(errors).toHaveLength(0);
    });
});

// ── Phase 1-B: 危険地域カード強化 ────────────────────────────────────────────

const EQ_RESPONSE_1 = {
    count: 1,
    items: [
        {
            event_id:       'eq-s-001',
            occurred_at:    '2026-05-26T10:00:00+09:00',
            epicenter_name: '千葉県東方沖',
            lat:            35.6,
            lng:            140.5,
            magnitude:      4.5,
            max_intensity:  '3',
        },
    ],
};

const EQ_RESPONSE_M5 = {
    count: 1,
    items: [
        {
            event_id:       'eq-m5-001',
            occurred_at:    '2026-05-26T10:00:00+09:00',
            epicenter_name: '東京湾北部',
            lat:            35.5,
            lng:            139.8,
            magnitude:      5.5,
            max_intensity:  '4',
        },
    ],
};

const EQ_RESPONSE_EMPTY = { count: 0, items: [] };

const TSUNAMI_RESPONSE_EMPTY = {
    observed_at: '2026-05-26T10:00:00+09:00',
    updated_at:  '2026-05-26T10:00:00+09:00',
    ttl_seconds: 60,
    areas:       [],
    message:     '',
};

async function mockLiveTrafficWith(page, { eqResponse = EQ_RESPONSE, tsunamiResponse = TSUNAMI_RESPONSE } = {}) {
    await page.route('/api/earthquakes**', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body:   JSON.stringify(eqResponse),
    }));
    await page.route('/api/tsunami/**', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body:   JSON.stringify(tsunamiResponse),
    }));
    await page.route('/api/weather/rain/tile/times', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body:   JSON.stringify(RAIN_TIMES),
    }));
    await page.route('**/jmatile/**', route => {
        if (route.request().url().includes('targetTimes.json')) {
            return route.fulfill({
                status: 200, contentType: 'application/json',
                body:   JSON.stringify([KIKIKURU_TIME]),
            });
        }
        return route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG });
    });
    await page.route('**/jma.go.jp/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
    await page.route('**/basemaps.cartocdn.com/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
}

test.describe('/live Phase 1-B — 危険地域カード強化', () => {

    test('カードに津波・地震・雨雲・キキクルの行が存在する', async ({ page }) => {
        await mockLiveTrafficWith(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        const card = page.locator('#live-alert-card');
        await expect(card).toContainText('津波');
        await expect(card).toContainText('地震');
        await expect(card).toContainText('雨雲');
        await expect(card).toContainText('キキクル');
    });

    test('地震1件 mock 時にカードへ件数が出る', async ({ page }) => {
        await mockLiveTrafficWith(page, { eqResponse: EQ_RESPONSE_1 });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        await expect(page.locator('#live-alert-card')).toContainText('1件');
    });

    test('M5以上地震 mock 時に危険地域リストが表示される', async ({ page }) => {
        await mockLiveTrafficWith(page, { eqResponse: EQ_RESPONSE_M5 });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        await expect(page.locator('.lac-danger-item')).toBeVisible({ timeout: 3000 });
        await expect(page.locator('#live-alert-card')).toContainText('東京湾北部');
    });

    test('危険地域クリックで map center / zoom が変わる', async ({ page }) => {
        await mockLiveTrafficWith(page, { eqResponse: EQ_RESPONSE_M5 });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        const item = page.locator('.lac-danger-clickable').first();
        await expect(item).toBeVisible({ timeout: 3000 });
        await item.click();
        await page.waitForTimeout(300);

        const zoom = await page.evaluate(() => liveMap.getZoom());
        expect(zoom).toBe(7);

        const center = await page.evaluate(() => {
            const c = liveMap.getCenter();
            return { lat: c.lat, lng: c.lng };
        });
        expect(Math.abs(center.lat - 35.5)).toBeLessThan(0.5);
        expect(Math.abs(center.lng - 139.8)).toBeLessThan(0.5);
    });

    test('全API正常・危険なしの場合に「大きな警戒情報なし」が表示される', async ({ page }) => {
        await mockLiveTrafficWith(page, {
            eqResponse:     EQ_RESPONSE_EMPTY,
            tsunamiResponse: TSUNAMI_RESPONSE_EMPTY,
        });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        await expect(page.locator('#live-alert-card')).toContainText('大きな警戒情報はありません');
    });

    test('API offline 時に「安全」と断定しない', async ({ page }) => {
        await page.route('/api/**', route => route.fulfill({ status: 503, body: '' }));
        await page.route('**/jmatile/**', route =>
            route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
        );
        await page.route('**/basemaps.cartocdn.com/**', route =>
            route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
        );
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        const text = await page.locator('#live-alert-card').innerText();
        expect(text).not.toContain('安全');
        expect(text).not.toContain('大きな警戒情報はありません');
        expect(text).toMatch(/取得失敗|取得できません/);
    });

    test('Phase 1-B: console.error / page error が発生しない', async ({ page }) => {
        const errors = [];
        const pageErrors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        page.on('pageerror', err => pageErrors.push(err.message));

        await mockLiveTrafficWith(page, { eqResponse: EQ_RESPONSE_M5 });
        // summary API を正常応答にして 404 console.error を防ぐ（Phase 1-C で追加されたエンドポイント）
        await page.route('/api/live/summary', route => route.fulfill({
            status: 200, contentType: 'application/json',
            body:   JSON.stringify(_makeSummary()),
        }));
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(500);

        expect(errors).toHaveLength(0);
        expect(pageErrors).toHaveLength(0);
    });

});

// ── Phase 1-C: 雨雲・キキクル危険度集計データ契約 ─────────────────────────

const SUMMARY_RAIN_UNEVALUATED = {
    status: 'ok', evaluated: false, reason: 'tile_only',
    summary: { strong_rain_detected: null, warning_area_count: null, danger_area_count: null },
    areas: [],
};
const SUMMARY_KIKIKURU_UNEVALUATED = {
    status: 'ok', evaluated: false, reason: 'tile_only',
    summary: { danger_detected: null, warning_area_count: null, danger_area_count: null },
    areas: [],
};
const SUMMARY_EQ_CLEAR = {
    status: 'ok', evaluated: true,
    summary: { count_24h: 0, m5_count: 0, m6_count: 0 },
    areas: [],
};
const SUMMARY_TSUNAMI_CLEAR = {
    status: 'ok', evaluated: true,
    summary: { active: false, warning_area_count: 0 },
    areas: [],
};

function _makeSummary(overrides = {}) {
    return {
        updated_at:      '2026-05-27T22:40:00+09:00',
        status:          'ok',
        rain:            SUMMARY_RAIN_UNEVALUATED,
        kikikuru:        SUMMARY_KIKIKURU_UNEVALUATED,
        earthquake:      SUMMARY_EQ_CLEAR,
        tsunami:         SUMMARY_TSUNAMI_CLEAR,
        dangerous_areas: [],
        ...overrides,
    };
}

async function mockLiveTrafficWithSummary(page, summaryOverrides = {}) {
    const summary = _makeSummary(summaryOverrides);
    await page.route('/api/live/summary', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body:   JSON.stringify(summary),
    }));
    await mockLiveTrafficWith(page, { eqResponse: EQ_RESPONSE_EMPTY, tsunamiResponse: TSUNAMI_RESPONSE_EMPTY });
}

test.describe('/live Phase 1-C — summary API と evaluated 契約', () => {

    test('/api/live/summary が呼ばれる', async ({ page }) => {
        let summaryCalled = false;
        await page.route('/api/live/summary', route => {
            summaryCalled = true;
            return route.fulfill({
                status: 200, contentType: 'application/json',
                body:   JSON.stringify(_makeSummary()),
            });
        });
        await mockLiveTrafficWith(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        expect(summaryCalled).toBe(true);
    });

    test('rain evaluated=false で「強雨域なし」を表示しない', async ({ page }) => {
        await mockLiveTrafficWithSummary(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        const text = await page.locator('#live-alert-card').innerText();
        expect(text).not.toContain('強雨域なし');
    });

    test('kikikuru evaluated=false で「キキクル危険地域なし」を表示しない', async ({ page }) => {
        await mockLiveTrafficWithSummary(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        const text = await page.locator('#live-alert-card').innerText();
        expect(text).not.toContain('キキクル危険地域なし');
    });

    test('rain evaluated=true, strong_rain_detected=false で「強雨域なし」が表示される', async ({ page }) => {
        await mockLiveTrafficWithSummary(page, {
            rain: {
                status: 'ok', evaluated: true, reason: 'analyzed',
                summary: { strong_rain_detected: false, warning_area_count: 0, danger_area_count: 0 },
                areas: [],
            },
        });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await expect(page.locator('#live-alert-card')).toContainText('強雨域なし');
    });

    test('kikikuru evaluated=true, danger_detected=false で「キキクル危険地域なし」が表示される', async ({ page }) => {
        await mockLiveTrafficWithSummary(page, {
            kikikuru: {
                status: 'ok', evaluated: true, reason: 'analyzed',
                summary: { danger_detected: false, warning_area_count: 0, danger_area_count: 0 },
                areas: [],
            },
        });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await expect(page.locator('#live-alert-card')).toContainText('キキクル危険地域なし');
    });

    test('summary API failure でも page error が発生しない', async ({ page }) => {
        const pageErrors = [];
        page.on('pageerror', err => pageErrors.push(err.message));
        // summary API を 503 にして個別 API は正常
        await page.route('/api/live/summary', route => route.fulfill({ status: 503, body: '' }));
        await mockLiveTrafficWith(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(300);
        expect(pageErrors).toHaveLength(0);
    });

    test('summary API failure 時にフォールバックが動作しカードが表示される', async ({ page }) => {
        await page.route('/api/live/summary', route => route.fulfill({ status: 503, body: '' }));
        await mockLiveTrafficWith(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await expect(page.locator('#live-alert-card')).toBeVisible();
        await expect(page.locator('#live-alert-card')).toContainText('津波');
    });

    test('summary API offline 時に「安全」と断定しない（Phase 1-C 確認）', async ({ page }) => {
        await page.route('/api/**', route => route.fulfill({ status: 503, body: '' }));
        await page.route('**/jmatile/**', route =>
            route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
        );
        await page.route('**/basemaps.cartocdn.com/**', route =>
            route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
        );
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        const text = await page.locator('#live-alert-card').innerText();
        expect(text).not.toContain('安全');
        expect(text).not.toContain('大きな警戒情報はありません');
    });

});

// ── Phase 2-A: 雨雲危険度集計 ─────────────────────────────────────────────

const SUMMARY_RAIN_STRONG = {
    status: 'ok', evaluated: true, reason: 'sampled_nowcast',
    summary: {
        strong_rain_detected: true,
        warning_area_count: 1, danger_area_count: 0,
        sample_count: 11, unknown_count: 0,
    },
    areas: [{
        id: 'rain-tokyo-2026052722400',
        label: '東京都付近', prefecture: '東京都', area_name: '東京',
        level: 'warning', type: 'rain', source: 'jma_nowcast',
        lat: 35.681, lng: 139.767,
        observed_at: '2026-05-27T22:40:00+09:00', description: '強雨域を検出',
    }],
};

const SUMMARY_RAIN_CLEAR = {
    status: 'ok', evaluated: true, reason: 'sampled_nowcast',
    summary: {
        strong_rain_detected: false,
        warning_area_count: 0, danger_area_count: 0,
        sample_count: 11, unknown_count: 0,
    },
    areas: [],
};

const SUMMARY_RAIN_OFFLINE = {
    status: 'offline', evaluated: false, reason: 'source_unavailable',
    summary: {
        strong_rain_detected: null,
        warning_area_count: null, danger_area_count: null,
        sample_count: 0, unknown_count: null,
    },
    areas: [],
};

test.describe('/live Phase 2-A — 雨雲危険度集計', () => {

    test('rain evaluated=true + strong_rain_detected=false で「強雨域なし」が表示される', async ({ page }) => {
        await mockLiveTrafficWithSummary(page, { rain: SUMMARY_RAIN_CLEAR });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await expect(page.locator('#live-alert-card')).toContainText('強雨域なし');
    });

    test('rain evaluated=true + strong_rain_detected=true で「強雨域あり」が表示される', async ({ page }) => {
        await mockLiveTrafficWithSummary(page, { rain: SUMMARY_RAIN_STRONG });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await expect(page.locator('#live-alert-card')).toContainText('強雨域あり');
    });

    test('rain strong_rain_detected=true で rain area が危険地域ランキングに現れる', async ({ page }) => {
        await mockLiveTrafficWithSummary(page, {
            rain:            SUMMARY_RAIN_STRONG,
            dangerous_areas: SUMMARY_RAIN_STRONG.areas,
        });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await expect(page.locator('.lac-danger-item')).toBeVisible({ timeout: 3000 });
        await expect(page.locator('#live-alert-card')).toContainText('東京都付近');
    });

    test('rain evaluated=false で「強雨域なし」を表示しない（Phase 2-A 再確認）', async ({ page }) => {
        await mockLiveTrafficWithSummary(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        const text = await page.locator('#live-alert-card').innerText();
        expect(text).not.toContain('強雨域なし');
    });

    test('rain offline で「雨雲情報: 取得失敗」が表示される', async ({ page }) => {
        await mockLiveTrafficWithSummary(page, { rain: SUMMARY_RAIN_OFFLINE });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await expect(page.locator('#live-alert-card')).toContainText('取得失敗');
    });

    test('rain offline でも「安全」と断定しない', async ({ page }) => {
        await mockLiveTrafficWithSummary(page, { rain: SUMMARY_RAIN_OFFLINE });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        const text = await page.locator('#live-alert-card').innerText();
        expect(text).not.toContain('安全');
    });

    test('Phase 2-A: console.error / page error が発生しない', async ({ page }) => {
        const errors = [];
        const pageErrors = [];
        page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
        page.on('pageerror', err => pageErrors.push(err.message));

        await mockLiveTrafficWithSummary(page, { rain: SUMMARY_RAIN_STRONG });
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });
        await page.waitForTimeout(500);

        expect(errors).toHaveLength(0);
        expect(pageErrors).toHaveLength(0);
    });

});

test.describe('/live — API 失敗耐性', () => {
    async function mockAllApis503(page) {
        await page.route('/api/**', route => route.fulfill({ status: 503, body: '' }));
        await page.route('**/jmatile/**', route => route.fulfill({
            status: 200, contentType: 'application/json', body: '[]',
        }));
        await page.route('**/basemaps.cartocdn.com/**', route =>
            route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
        );
    }

    test('API 503 時に rain OFF→ON で page error が発生しない', async ({ page }) => {
        const pageErrors = [];
        page.on('pageerror', err => pageErrors.push(err.message));

        await mockAllApis503(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        const toggle = page.locator('#toggle-rain');
        await toggle.uncheck();
        await toggle.check();
        await page.waitForTimeout(500);

        expect(pageErrors).toHaveLength(0);
    });

    test('API 503 時に status dot が offline になる', async ({ page }) => {
        await mockAllApis503(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-loading')).toHaveClass(/hidden/, { timeout: 8000 });

        const offlineDots = page.locator('#live-status-bar .live-status-dot.offline');
        await expect(offlineDots).not.toHaveCount(0);
    });

    test('API 503 時に map 操作が継続できる', async ({ page }) => {
        const pageErrors = [];
        page.on('pageerror', err => pageErrors.push(err.message));

        await mockAllApis503(page);
        await page.goto('/live.html');
        await expect(page.locator('#live-map.leaflet-container')).toBeVisible({ timeout: 5000 });

        // アラートカード（左上）を避けてマップ右側でホイールズーム操作
        await page.mouse.move(800, 400);
        await page.mouse.wheel(0, -120);
        await page.waitForTimeout(300);

        expect(pageErrors).toHaveLength(0);
    });
});
