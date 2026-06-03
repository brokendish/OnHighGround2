'use strict';
/**
 * live-rain-timeline.spec.js — 雨雲予測タイムライン確認 (Phase 5-B)
 *
 * backend 不要。API はすべてモックで受ける。
 * 完了条件:
 *   - タイムライン表示
 *   - スライダー動作
 *   - 再生/停止動作
 *   - 危険地域集計への影響なし（false-safe）
 *   - 既存雨雲機能維持
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

const EQ_RESPONSE  = { count: 0, items: [] };
const TSUNAMI_NONE = { status: 'none', observed_at: null, updated_at: null, ttl_seconds: 60, areas: [], message: '' };
const SS_NONE      = { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] };

// 現在 + 予測 13ステップ（0, 5, 10, ... 60分）
const BASETIME = '20260603120000';
const RAIN_TIMES = {
    basetime: BASETIME,
    times: Array.from({ length: 13 }, (_, i) => {
        const off = i * 5;
        const vt  = `20260603${String(12 + Math.floor(off / 60)).padStart(2, '0')}${String((off % 60)).padStart(2, '0')}00`;
        return {
            offset_minutes:    off,
            validtime:         vt,
            tile_url_template: `https://www.jma.go.jp/bosai/jmatile/data/nowc/${BASETIME}/none/${vt}/surf/hrpns/{z}/{x}/{y}.png`,
        };
    }),
};

// /api/live/rain/timeline は offset_minutes >= 0 のみ返す（同じデータ）
const TIMELINE_RESPONSE = { ...RAIN_TIMES };

const SUMMARY_EMPTY = {
    status:   'ok',
    rain:     { status: 'ok', evaluated: false, summary: {}, areas: [] },
    kikikuru: { status: 'ok', evaluated: false, summary: {}, areas: [] },
    earthquake: { status: 'ok', evaluated: true, summary: { count_24h: 0, m5_count: 0 }, areas: [] },
    tsunami:    { status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] },
    storm_surge:{ status: 'ok', evaluated: true, summary: { active: false, warning_area_count: 0 }, areas: [] },
    dangerous_areas:              [],
    integrated_dangerous_regions: [],
};

async function mockBase(page) {
    await page.route('/api/live/summary',             r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUMMARY_EMPTY) }));
    await page.route('/api/live/storm_surge/**',      r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SS_NONE) }));
    await page.route('/api/earthquakes**',            r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EQ_RESPONSE) }));
    await page.route('/api/tsunami/**',               r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TSUNAMI_NONE) }));
    await page.route('/api/weather/rain/tile/times',  r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAIN_TIMES) }));
    await page.route('/api/live/rain/timeline',       r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TIMELINE_RESPONSE) }));
    await page.route('/api/live/tide/**',             r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, stations: [] }) }));
    await page.route('/api/live/astro**',             r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('/api/live/sun_moon**',          r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.route('**/jmatile/**',                 r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/jma.go.jp/**',               r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
    await page.route('**/basemaps.cartocdn.com/**',   r => r.fulfill({ status: 200, contentType: 'image/png',        body: TRANSPARENT_PNG }));
}

// ── タイムライン表示 ──────────────────────────────────────────────────────────

test.describe('/live — 雨雲タイムライン: 表示確認', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-rain-timeline').waitFor({ state: 'visible', timeout: 8000 });
    });

    test('タイムラインコンテナが表示される', async ({ page }) => {
        await expect(page.locator('#live-rain-timeline')).toBeVisible();
    });

    test('スライダーが存在する', async ({ page }) => {
        await expect(page.locator('#rain-tl-slider')).toBeVisible();
    });

    test('再生ボタンが存在する', async ({ page }) => {
        await expect(page.locator('#rain-tl-play')).toBeVisible();
    });

    test('初期オフセットラベルが "現在" になっている', async ({ page }) => {
        await expect(page.locator('#rain-tl-offset')).toHaveText('現在');
    });

    test('スライダーの max が 12（13ステップ - 1）', async ({ page }) => {
        const slider = page.locator('#rain-tl-slider');
        await expect(slider).toHaveAttribute('max', '12');
    });

    test('スライダーの初期値が 0', async ({ page }) => {
        const slider = page.locator('#rain-tl-slider');
        await expect(slider).toHaveAttribute('value', '0');
    });
});

// ── スライダー操作 ────────────────────────────────────────────────────────────

test.describe('/live — 雨雲タイムライン: スライダー操作', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-rain-timeline').waitFor({ state: 'visible', timeout: 8000 });
    });

    test('スライダーを動かすとオフセットラベルが更新される', async ({ page }) => {
        const slider = page.locator('#rain-tl-slider');
        await slider.evaluate(el => {
            el.value = '6';
            el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await expect(page.locator('#rain-tl-offset')).toHaveText('+30分');
    });

    test('スライダーを最大にすると +60分 になる', async ({ page }) => {
        const slider = page.locator('#rain-tl-slider');
        await slider.evaluate(el => {
            el.value = '12';
            el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await expect(page.locator('#rain-tl-offset')).toHaveText('+60分');
    });

    test('スライダーを 0 に戻すと "現在" になる', async ({ page }) => {
        const slider = page.locator('#rain-tl-slider');
        await slider.evaluate(el => {
            el.value = '6';
            el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await slider.evaluate(el => {
            el.value = '0';
            el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await expect(page.locator('#rain-tl-offset')).toHaveText('現在');
    });
});

// ── 再生 / 停止 ───────────────────────────────────────────────────────────────

test.describe('/live — 雨雲タイムライン: 再生/停止', () => {
    test.beforeEach(async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-rain-timeline').waitFor({ state: 'visible', timeout: 8000 });
    });

    test('再生ボタン初期テキストは ▶', async ({ page }) => {
        await expect(page.locator('#rain-tl-play')).toHaveText('▶');
    });

    test('再生ボタンを押すと ⏸ になる', async ({ page }) => {
        await page.locator('#rain-tl-play').click();
        await expect(page.locator('#rain-tl-play')).toHaveText('⏸');
    });

    test('⏸ を押すと ▶ に戻る', async ({ page }) => {
        await page.locator('#rain-tl-play').click();
        await expect(page.locator('#rain-tl-play')).toHaveText('⏸');
        await page.locator('#rain-tl-play').click();
        await expect(page.locator('#rain-tl-play')).toHaveText('▶');
    });

    test('再生中にスライダー操作すると一時停止する', async ({ page }) => {
        await page.locator('#rain-tl-play').click();
        await expect(page.locator('#rain-tl-play')).toHaveText('⏸');
        const slider = page.locator('#rain-tl-slider');
        await slider.evaluate(el => {
            el.value = '3';
            el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await expect(page.locator('#rain-tl-play')).toHaveText('▶');
    });
});

// ── false-safe: 危険地域への影響なし ─────────────────────────────────────────

test.describe('/live — 雨雲タイムライン: false-safe 確認', () => {
    test('タイムライン表示中も dangerous_areas は空のまま', async ({ page }) => {
        await mockBase(page);
        await page.goto('/live.html');
        await page.locator('#live-rain-timeline').waitFor({ state: 'visible', timeout: 8000 });

        // アラートカードに危険地域が表示されないことを確認
        const card = page.locator('#live-alert-card');
        await card.waitFor({ timeout: 5000 });
        const text = await card.textContent();
        expect(text).not.toMatch(/danger|warning/i.test(text) && /危険地域/.test(text) ? /[^$]/ : /危険地域/);
    });

    test('予測フレームを表示しても summary の集計が変わらない', async ({ page }) => {
        let summaryCallCount = 0;
        let timelineCallCount = 0;
        await mockBase(page);
        await page.route('/api/live/summary', r => {
            summaryCallCount++;
            r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SUMMARY_EMPTY) });
        });
        await page.route('/api/live/rain/timeline', r => {
            timelineCallCount++;
            r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TIMELINE_RESPONSE) });
        });
        await page.goto('/live.html');
        await page.locator('#live-rain-timeline').waitFor({ state: 'visible', timeout: 8000 });

        // スライダーを動かしても summary への追加 API 呼び出しは発生しない
        const slider = page.locator('#rain-tl-slider');
        await slider.evaluate(el => {
            el.value = '6';
            el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await page.waitForTimeout(300);

        expect(summaryCallCount).toBe(1);    // 初回のみ
        expect(timelineCallCount).toBe(1);   // timeline も初回のみ
    });
});

// ── API エラー時のフォールバック ──────────────────────────────────────────────

test.describe('/live — 雨雲タイムライン: API エラー時', () => {
    test('timeline API が 503 の場合タイムラインは表示されない', async ({ page }) => {
        await mockBase(page);
        await page.route('/api/live/rain/timeline', r => r.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'unavailable' }) }));
        await page.goto('/live.html');
        // ステータスバーが描画されたらページ読み込み完了
        await page.locator('#live-status-bar').waitFor({ state: 'visible', timeout: 8000 });
        await page.waitForTimeout(500);
        await expect(page.locator('#live-rain-timeline')).toHaveClass(/hidden/);
    });

    test('timeline API エラー時も既存の雨雲レイヤーは表示される', async ({ page }) => {
        await mockBase(page);
        await page.route('/api/live/rain/timeline', r => r.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'unavailable' }) }));
        await page.goto('/live.html');
        // ステータスバーが雨雲 OK を示す
        await expect(page.locator('#live-status-bar')).toContainText('雨雲', { timeout: 8000 });
    });
});
