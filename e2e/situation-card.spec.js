/**
 * situation-card.spec.js — Phase 4-B 状況理解カード E2E
 *
 * situationCardOnRouteUpdate / situationCardOnWeatherUpdate / situationCardClear
 * を page.evaluate で直接呼び出し、#sit-card-section の表示内容を検証する。
 * backend 不要。
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── 共通モックデータ ─────────────────────────────────────────────────────────

const KKK_RISK_OFF     = { status: 'off',         inund: null,       flood: null,      land: null };
const KKK_RISK_OK_NONE = { status: 'ok',           inund: 'none',     flood: 'none',    land: 'none' };
const KKK_RISK_OK_CAUTION = { status: 'ok',        inund: 'caution',  flood: 'none',    land: 'none' };
const KKK_RISK_OK_DANGER  = { status: 'ok',        inund: 'danger',   flood: 'danger',  land: 'none' };
const KKK_RISK_UNAVAIL    = { status: 'unavailable', inund: null, flood: null, land: null };
const KKK_RISK_UNKNOWN    = { status: 'unknown', inund: null, flood: null, land: null };

const ADJ_OFF  = { enabled: false, status: 'off', penalty: 0, max_level: null, matched_hazards: [], summary: [] };
const ADJ_UVAL = { enabled: true, status: 'unavailable', penalty: 0, max_level: null, matched_hazards: [], summary: [] };

// ルートリスク（route-risk レスポンス相当）
function routeRisk(riskLevel, adj = ADJ_OFF) {
    return { safety_score: 50, risk_level: riskLevel, risk_summary: { notes: [], hazards: [] }, kikikuru_adjustment: adj };
}

// 降水情報
const PRECIP_NONE = { current: { intensity: 'none', label: '雨なし' }, forecastStrongest: null };
const PRECIP_STRONG = { current: { intensity: 'strong', label: '強い雨' }, forecastStrongest: { intensity: 'weak', label: '弱い雨', minutes: 20 } };
const PRECIP_STRONG_NO_IMPROVE = { current: { intensity: 'strong', label: '強い雨' }, forecastStrongest: { intensity: 'strong', label: '強い雨', minutes: 20 } };

// ── 共通ページ準備 ────────────────────────────────────────────────────────────

async function setupPage(page) {
    await page.route('/api/**', route => route.fulfill({
        status: 200, contentType: 'application/json', body: '{}',
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.goto('/');
    // situation-card.js がロードされるまで待つ
    await page.waitForFunction(() => typeof situationCardOnRouteUpdate === 'function');
}

// kikikuruGetRiskSnapshot をモックして任意のリスク状態を注入
async function setKkkSnapshot(page, current, dest) {
    await page.evaluate(({ c, d }) => {
        window.kikikuruGetRiskSnapshot = () => ({ current: c, dest: d, route: { status: 'off' } });
    }, { c: current, d: dest });
}

// route_preview モードに切り替えて loc-info-route を表示状態にする
async function activateRoutePreview(page) {
    await page.evaluate(() => {
        // 親パネル（mbc-tab-panel-info）を表示してから loc-info-route を表示
        const tabPanel = document.getElementById('mbc-tab-panel-info');
        if (tabPanel) tabPanel.style.display = '';
        const routeEl = document.getElementById('loc-info-route');
        if (routeEl) routeEl.style.display = '';
        const nonNavEl = document.getElementById('loc-info-nonnav');
        if (nonNavEl) nonNavEl.style.display = 'none';
    });
}

// ── テスト ────────────────────────────────────────────────────────────────────

test.describe('Phase 4-B: 状況理解カード', () => {

    test('ルート未設定では状況理解カードが非表示', async ({ page }) => {
        await setupPage(page);
        await expect(page.locator('#sit-card-section')).toBeHidden();
    });

    test('routeRisk が設定されるとカードが表示される', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('safe'));
        await activateRoutePreview(page);
        await expect(page.locator('#sit-card-section')).toBeVisible();
    });

    test('destination danger + current caution で「待機検討」バッジが表示される', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_OK_CAUTION, KKK_RISK_OK_DANGER);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('caution'));
        await activateRoutePreview(page);
        await page.evaluate(() => situationCardOnKkkUpdate());
        await expect(page.locator('#sit-action-badge')).toContainText('待機検討');
    });

    test('current danger + dest caution + route caution で「早めの移動検討」バッジが表示される', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_OK_DANGER, KKK_RISK_OK_CAUTION);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('caution'));
        await activateRoutePreview(page);
        await page.evaluate(() => situationCardOnKkkUpdate());
        await expect(page.locator('#sit-action-badge')).toContainText('早めの移動検討');
    });

    test('強雨 + 20分後に改善予測で「待機検討」が表示される', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_OK_NONE, KKK_RISK_OK_NONE);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('caution'));
        await activateRoutePreview(page);
        await page.evaluate(p => situationCardOnWeatherUpdate(p), PRECIP_STRONG);
        await expect(page.locator('#sit-card-body')).toContainText('待機');
        await expect(page.locator('#sit-card-body')).toContainText('弱まる予測');
    });

    test('強雨でも改善なしなら「待機」が出ない（ルートが安全なら）', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_OK_NONE, KKK_RISK_OK_NONE);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('safe'));
        await activateRoutePreview(page);
        await page.evaluate(p => situationCardOnWeatherUpdate(p), PRECIP_STRONG_NO_IMPROVE);
        await expect(page.locator('#sit-action-badge')).toBeHidden();
    });

    test('キキクル取得不可を safe 扱いしない（取得不可表示）', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_UNAVAIL, KKK_RISK_UNAVAIL);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('safe'));
        await activateRoutePreview(page);
        await page.evaluate(() => situationCardOnKkkUpdate());
        const text = await page.locator('#sit-card-body').textContent();
        expect(text).toMatch(/取得不可/);
        expect(text).not.toMatch(/リスク検出なし/);
    });

    test('キキクル判定不可を safe 扱いしない（判定不可表示）', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_UNKNOWN, KKK_RISK_UNKNOWN);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('safe'));
        await activateRoutePreview(page);
        await page.evaluate(() => situationCardOnKkkUpdate());
        const text = await page.locator('#sit-card-body').textContent();
        expect(text).toMatch(/判定不可/);
        expect(text).toMatch(/安全を意味しません/);
        expect(text).not.toMatch(/リスク検出なし/);
    });

    test('route danger で理由説明が表示される（ブラックボックス禁止）', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_OK_NONE, KKK_RISK_OK_NONE);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('danger'));
        await activateRoutePreview(page);
        await page.evaluate(() => situationCardOnKkkUpdate());
        const text = await page.locator('#sit-card-body').textContent();
        expect(text).toMatch(/危険度が高い区間|危険度が上昇|危険度が高まっています/);
    });

    test('命令口調ではなく「検討してください」表現', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_OK_DANGER, KKK_RISK_OK_NONE);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('caution'));
        await activateRoutePreview(page);
        await page.evaluate(() => situationCardOnKkkUpdate());
        const text = await page.locator('#sit-card-body').textContent();
        expect(text).toContain('検討してください');
        expect(text).not.toMatch(/避難してください|必ず移動|絶対に/);
    });

    test('situationCardClear でカードが非表示になる', async ({ page }) => {
        await setupPage(page);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('caution'));
        await activateRoutePreview(page);
        await expect(page.locator('#sit-card-section')).toBeVisible();
        await page.evaluate(() => situationCardClear());
        await expect(page.locator('#sit-card-section')).toBeHidden();
    });

    test('現在地/目的地/ルート/降水の行が含まれる', async ({ page }) => {
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_OK_CAUTION, KKK_RISK_OK_CAUTION);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('caution'));
        await activateRoutePreview(page);
        await page.evaluate(p => situationCardOnWeatherUpdate(p), PRECIP_STRONG);
        await page.evaluate(() => situationCardOnKkkUpdate());
        const text = await page.locator('#sit-card-body').textContent();
        expect(text).toMatch(/現在地/);
        expect(text).toMatch(/目的地/);
        expect(text).toMatch(/ルート/);
        expect(text).toMatch(/降水/);
    });

    test('モバイル幅で横はみ出しがない', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await setupPage(page);
        await setKkkSnapshot(page, KKK_RISK_OK_DANGER, KKK_RISK_OK_CAUTION);
        await page.evaluate(r => situationCardOnRouteUpdate(r), routeRisk('caution'));
        await activateRoutePreview(page);
        await page.evaluate(() => situationCardOnKkkUpdate());
        // スマホ幅では下部パネルは初期 collapsed（MOBILE-BOTTOM-PANEL-COMPACT）。ハンドルで展開する
        if (await page.locator('#map-bottom-controls.mbc-collapsed').count()) {
            await page.locator('#map-bottom-handle').click();
        }
        // アコーディオン本文を開く（カードが表示状態になってからクリック）
        await expect(page.locator('#sit-card-section')).toBeVisible();
        await page.locator('#sit-card-section .lip-accordion-header').click();
        const overflow = await page.evaluate(() =>
            document.documentElement.scrollWidth - document.documentElement.clientWidth
        );
        expect(overflow).toBeLessThanOrEqual(1);
    });

});
