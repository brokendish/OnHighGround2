/**
 * nav-forward-warning.spec.js — Phase 4-A 前方危険警告パネル E2E
 *
 * navForwardWarningUpdate() / navForwardWarningClear() を page.evaluate で
 * 直接呼び出し、#nav-forward-warning の表示内容を検証する。
 * backend 不要。
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── 共通モックデータ ─────────────────────────────────────────────────────────

const BASE_ADJ = { enabled: false, status: 'off', penalty: 0, max_level: null, matched_hazards: [], summary: [] };

const RISK_SAFE = {
    safety_score: 90, risk_level: 'safe',
    risk_summary: { notes: [], hazards: [] },
    kikikuru_adjustment: BASE_ADJ,
    sampled_points: [],
};

const RISK_FLOOD_DANGER = {
    safety_score: 28, risk_level: 'danger',
    risk_summary: { notes: ['洪水浸水区域を通過'], hazards: ['flood'] },
    kikikuru_adjustment: {
        enabled: true, status: 'ok', penalty: 8, max_level: 'danger',
        matched_hazards: ['flood'], summary: ['洪水キキクル: 危険'],
    },
    sampled_points: [
        { lat: 35.681, lon: 139.767, hazards: { flood: 'inside', inund: 'outside' } },
        { lat: 35.682, lon: 139.768, hazards: { flood: 'inside' } },
    ],
};

const RISK_LAND_CAUTION = {
    safety_score: 65, risk_level: 'caution',
    risk_summary: { notes: ['土砂災害警戒区域'], hazards: ['landslide'] },
    kikikuru_adjustment: {
        enabled: true, status: 'ok', penalty: 4, max_level: 'caution',
        matched_hazards: [], summary: ['土砂キキクル: 注意'],
    },
    sampled_points: [
        { lat: 35.690, lon: 139.780, hazards: { landslide: 'inside' } },
    ],
};

const RISK_KKK_UNAVAILABLE = {
    safety_score: 80, risk_level: 'safe',
    risk_summary: { notes: [], hazards: [] },
    kikikuru_adjustment: {
        enabled: true, status: 'unavailable', penalty: 0, max_level: null,
        matched_hazards: [], summary: [],
    },
    sampled_points: [],
};

const RISK_KKK_UNKNOWN = {
    safety_score: 80, risk_level: 'safe',
    risk_summary: { notes: [], hazards: [] },
    kikikuru_adjustment: {
        enabled: true, status: 'unknown', penalty: 0, max_level: null,
        matched_hazards: [], summary: [],
    },
    sampled_points: [],
};

const RISK_KKK_OVERLAP = {
    safety_score: 35, risk_level: 'danger',
    risk_summary: { notes: ['固定ハザード区域'], hazards: ['flood', 'inundation'] },
    kikikuru_adjustment: {
        enabled: true, status: 'ok', penalty: 8, max_level: 'danger',
        matched_hazards: ['flood'], summary: ['洪水キキクル: 危険'],
    },
    sampled_points: [
        { lat: 35.681, lon: 139.767, hazards: { flood: 'inside' } },
    ],
};

// ── 共通ページ準備 ────────────────────────────────────────────────────────────

async function setupPage(page) {
    await page.route('/api/**', route => route.fulfill({
        status: 200, contentType: 'application/json', body: '{}',
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    // JMA タイル・外部リソースはブロック不要（ネットワーク到達不可の場合は graceful degradation）
    await page.goto('/');
    // nav-forward-warning.js がロードされるまで待つ
    await page.waitForFunction(() => typeof navForwardWarningUpdate === 'function');
    await page.evaluate(() => setNavMode('navigation_active'));
}

// ── テスト ────────────────────────────────────────────────────────────────────

test.describe('Phase 4-A: 前方危険警告パネル', () => {

    test('safe シナリオでは警告パネルが表示されない', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_SAFE);
        await expect(page.locator('#nav-forward-warning')).toBeHidden();
    });

    test('ルート選択プレビューでは前方警告を表示しない', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(() => setNavMode('route_preview'));
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        await expect(page.locator('#nav-forward-warning')).toBeHidden();
        await page.evaluate(() => setNavMode('navigation_active'));
        await page.evaluate(() => navForwardWarningRefresh());
        await expect(page.locator('#nav-forward-warning')).toBeVisible();
    });

    test('danger シナリオで警告パネルが表示される', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        await expect(page.locator('#nav-forward-warning')).toBeVisible();
        await expect(page.locator('#nav-forward-warning')).toContainText('前方で危険度が高まっています');
    });

    test('caution シナリオで注意パネルが表示される', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_LAND_CAUTION);
        await expect(page.locator('#nav-forward-warning')).toBeVisible();
        await expect(page.locator('#nav-forward-warning')).toContainText('前方に注意が必要です');
    });

    test('前方距離または位置テキストが含まれる', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        // currentLocation の有無で「この先 Xm先」か「前方ルート上」のどちらかが出る
        const text = await page.locator('.nfw-dist').textContent();
        expect(text).toMatch(/この先|前方ルート上/);
    });

    test('unavailable シナリオで判定不可メッセージが表示される', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_KKK_UNAVAILABLE);
        await expect(page.locator('#nav-forward-warning')).toBeVisible();
        await expect(page.locator('#nav-forward-warning')).toContainText('キキクル判定不可');
        await expect(page.locator('#nav-forward-warning')).toContainText('安全を意味するものではありません');
    });

    test('unavailable を danger 扱いしない（danger クラスが付かない）', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_KKK_UNAVAILABLE);
        const cls = await page.locator('#nav-forward-warning').getAttribute('class');
        expect(cls).not.toContain('nav-fwd-warning--danger');
        expect(cls).toContain('nav-fwd-warning--unavailable');
    });

    test('unknown を danger/safe 扱いせず判定不可で表示する', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_KKK_UNKNOWN);
        const panel = page.locator('#nav-forward-warning');
        await expect(panel).toContainText('判定不可');
        await expect(panel).toContainText('安全を意味するものではありません');
        await expect(panel).toHaveClass(/nav-fwd-warning--unknown/);
        await expect(panel).not.toHaveClass(/nav-fwd-warning--danger/);
    });

    test('固定ハザードとキキクル重複説明が表示される', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_KKK_OVERLAP);
        await expect(page.locator('#nav-forward-warning')).toContainText('固定ハザード');
        await expect(page.locator('#nav-forward-warning')).toContainText('キキクルが重なっています');
    });

    test('自動 reroute ボタンがない（禁止確認）', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        await expect(page.locator('#nav-forward-warning button:not(.nfw-close)')).toHaveCount(0);
    });

    test('断定的な「避難してください」「絶対安全」表現がない', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        const text = await page.locator('#nav-forward-warning').textContent();
        expect(text).not.toMatch(/避難してください/);
        expect(text).not.toMatch(/絶対安全/);
        expect(text).not.toMatch(/絶対危険/);
    });

    test('閉じるボタンでパネルが非表示になる', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        await expect(page.locator('#nav-forward-warning')).toBeVisible();
        await page.locator('.nfw-close').click();
        await expect(page.locator('#nav-forward-warning')).toBeHidden();
    });

    test('navForwardWarningClear でパネルが非表示になる', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        await expect(page.locator('#nav-forward-warning')).toBeVisible();
        await page.evaluate(() => navForwardWarningClear());
        await expect(page.locator('#nav-forward-warning')).toBeHidden();
    });

    test('safe → danger 遷移で警告が表示される', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_SAFE);
        await expect(page.locator('#nav-forward-warning')).toBeHidden();
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        await expect(page.locator('#nav-forward-warning')).toBeVisible();
    });

    test('モバイル幅で横はみ出しがない', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await setupPage(page);
        await page.evaluate(d => navForwardWarningUpdate(d, d.sampled_points), RISK_FLOOD_DANGER);
        await expect(page.locator('#nav-forward-warning')).toBeVisible();
        const overflow = await page.evaluate(() =>
            document.documentElement.scrollWidth - document.documentElement.clientWidth
        );
        expect(overflow).toBeLessThanOrEqual(1);
    });

});
