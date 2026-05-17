'use strict';

const path = require('path');
const { test, expect } = require('@playwright/test');

// ── モックデータ ───────────────────────────────────────────────────────────────

const MOCK_SCENARIOS = {
    status: 'ok',
    scenarios: [
        { scenario_id: '001', title: '平常時',           origin: [139.767125, 35.681236], destination: [139.780000, 35.690000], weather: {}, hazards: {}, expected: { risk_level: 'none' } },
        { scenario_id: '003', title: '強雨 + 洪水想定区域', origin: [139.767125, 35.681236], destination: [139.780000, 35.690000], weather: { forecast_max_intensity: 'strong' }, hazards: { flood: true }, expected: { min_risk_level: 'warning' } },
        { scenario_id: '006', title: '気象リスク判定不能',  origin: [139.767125, 35.681236], destination: [139.780000, 35.690000], weather: { unknown: true }, hazards: {}, expected: { risk_level: 'unknown' } },
        { scenario_id: '007', title: 'ハザード情報確認不可', origin: [139.767125, 35.681236], destination: [139.780000, 35.690000], weather: {}, hazards: { unavailable: true }, expected: { risk_level: 'unknown' } },
    ],
};

function makeRunResponse(riskLevel, penaltyReason = '強雨域接近', isShortest = false) {
    return {
        status: 'ok',
        scenario_id: 'manual',
        recommended_route_index: 1,
        routes: [
            {
                index: 0, label: 'A', distance_m: 900, duration_s: 720,
                risk_level: riskLevel, safety_score: 42,
                risk_summary: ['強雨域接近', '洪水想定区域'],
                penalties: [
                    { type: 'strong_rain', points: 15, reason: '強雨域接近' },
                    { type: 'flood', points: 40, reason: '洪水想定区域' },
                    { type: 'combined_strong_flood', points: 15, reason: '強雨 + 洪水想定区域' },
                ],
                recommendation_reason: '最短ですが、洪水想定区域のリスクがあります',
                is_recommended: false, is_shortest: true,
            },
            {
                index: 1, label: 'B', distance_m: 1100, duration_s: 880,
                risk_level: 'none', safety_score: 100,
                risk_summary: [],
                penalties: [],
                recommendation_reason: 'リスクが低いルートです',
                is_recommended: true, is_shortest: false,
            },
        ],
        summary: { headline: '安全寄りルートがあります', message: '最短ルートより200m長いですが、浸水リスクが低いルートを推奨します' },
        layer_stack: [
            { key: 'weather_strong', label: '降水: 強雨域接近', active: true },
            { key: 'flood', label: '洪水想定区域', active: true },
            { key: 'lowland', label: '低地・排水困難エリア', active: false },
        ],
    };
}

const MOCK_AUTO_RUN = {
    run_at: '2026-05-17T20:00:00+00:00',
    total: 4,
    passed: 3,
    failed: 1,
    skipped: 0,
    results: [
        { scenario_id: '001', title: '平常時',          status: 'pass', risk_level: 'none',    recommended_route_index: 0, fail_reason: null },
        { scenario_id: '003', title: '強雨 + 洪水',     status: 'pass', risk_level: 'warning', recommended_route_index: 1, fail_reason: null },
        { scenario_id: '006', title: '気象判定不能',    status: 'pass', risk_level: 'unknown', recommended_route_index: 0, fail_reason: null },
        { scenario_id: '007', title: 'ハザード確認不可', status: 'fail', risk_level: 'warning', recommended_route_index: 0, fail_reason: 'risk_level: expected "unknown", got "warning"' },
    ],
    report_path: '/data_runtime/simulation/simulation_report_20260517_200000.json',
};

// ── ページセットアップ ─────────────────────────────────────────────────────────

async function openSimulation(page) {
    await page.route('/api/simulation/scenarios', route => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SCENARIOS),
    }));
    await page.goto('/admin/simulation.html');
    await page.waitForLoadState('domcontentloaded');
}

// ── テスト ────────────────────────────────────────────────────────────────────

test.describe('Simulation Mode — ページ表示', () => {
    test('ページタイトルが表示される', async ({ page }) => {
        await openSimulation(page);
        await expect(page).toHaveTitle(/シミュレーション/);
    });

    test('定義済みシナリオボタンが表示される', async ({ page }) => {
        await openSimulation(page);
        const btns = page.locator('.sim-scenario-btn');
        await expect(btns).toHaveCount(MOCK_SCENARIOS.scenarios.length);
        await expect(btns.first()).toContainText('[001]');
    });

    test('パラメータフォームが存在する', async ({ page }) => {
        await openSimulation(page);
        await expect(page.locator('#p-origin-lon')).toBeVisible();
        await expect(page.locator('#p-dest-lon')).toBeVisible();
        await expect(page.locator('#p-forecast-intensity')).toBeVisible();
        await expect(page.locator('#p-h-flood')).toBeVisible();
        await expect(page.locator('#run-btn')).toBeVisible();
    });
});

test.describe('Simulation Mode — シナリオ読み込み', () => {
    test('シナリオボタンクリックでフォームに値が設定される', async ({ page }) => {
        await openSimulation(page);
        const btn = page.locator('.sim-scenario-btn[data-scenario-id="003"]');
        await btn.click();

        await expect(page.locator('#p-forecast-intensity')).toHaveValue('strong');
        await expect(page.locator('#p-h-flood')).toBeChecked();
        await expect(btn).toHaveClass(/active/);
    });

    test('unknown シナリオのチェックボックスが設定される', async ({ page }) => {
        await openSimulation(page);
        await page.locator('.sim-scenario-btn[data-scenario-id="006"]').click();
        await expect(page.locator('#p-weather-unknown')).toBeChecked();
    });

    test('hazard unavailable シナリオのチェックボックスが設定される', async ({ page }) => {
        await openSimulation(page);
        await page.locator('.sim-scenario-btn[data-scenario-id="007"]').click();
        await expect(page.locator('#p-hazard-unavailable')).toBeChecked();
    });
});

test.describe('Simulation Mode — 手動実行', () => {
    test('実行ボタンで route comparison が表示される', async ({ page }) => {
        await openSimulation(page);

        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(makeRunResponse('warning')),
        }));

        await page.locator('#run-btn').click();
        await expect(page.locator('.sim-route-card')).toHaveCount(2, { timeout: 5000 });
        await expect(page.locator('.sim-summary-banner')).toBeVisible();
    });

    test('penalty breakdown が表示される', async ({ page }) => {
        await openSimulation(page);
        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(makeRunResponse('warning')),
        }));

        await page.locator('#run-btn').click();
        await page.locator('.sim-penalty-breakdown').first().waitFor({ timeout: 5000 });
        await expect(page.locator('.sim-penalty-item').first()).toBeVisible();
    });

    test('layer stack が表示される', async ({ page }) => {
        await openSimulation(page);
        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(makeRunResponse('warning')),
        }));

        await page.locator('#run-btn').click();
        await expect(page.locator('.sim-layer-stack'), { timeout: 5000 }).toBeVisible();
        await expect(page.locator('.sim-layer-row')).toHaveCount(3);
    });

    test('推奨ルートに rec badge が表示される', async ({ page }) => {
        await openSimulation(page);
        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(makeRunResponse('none')),
        }));

        await page.locator('#run-btn').click();
        await expect(page.locator('.sim-rec-badge')).toBeVisible({ timeout: 5000 });
    });

    test('unavailable response で旧結果が残らない', async ({ page }) => {
        await openSimulation(page);

        // 1回目: ok
        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(makeRunResponse('warning')),
        }));
        await page.locator('#run-btn').click();
        await expect(page.locator('.sim-route-card')).toHaveCount(2, { timeout: 5000 });

        // 2回目: unavailable
        await page.unroute('/api/simulation/run');
        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ status: 'unavailable', scenario_id: 'manual', recommended_route_index: 0, routes: [], summary: { headline: 'ルートを取得できません', message: '' }, layer_stack: [] }),
        }));
        await page.locator('#run-btn').click();
        await expect(page.locator('.sim-route-card')).toHaveCount(0, { timeout: 5000 });
        await expect(page.locator('.sim-unavailable')).toBeVisible();
    });

    test('unknown weather が表示される', async ({ page }) => {
        await openSimulation(page);
        const unknownResp = makeRunResponse('unknown');
        unknownResp.routes[0].risk_level = 'unknown';
        unknownResp.routes[0].risk_summary = ['気象リスク判定不能'];
        unknownResp.routes[1].risk_level = 'unknown';

        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(unknownResp),
        }));

        await page.locator('#run-btn').click();
        await expect(page.locator('.sim-route-card')).toHaveCount(2, { timeout: 5000 });
        // 「判定不能」が画面に出ている
        await expect(page.locator('.sim-route-risk', { hasText: '判定不能' }).first()).toBeVisible();
    });

    test('screenshot: 警戒シナリオの結果', async ({ page }, testInfo) => {
        await openSimulation(page);
        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(makeRunResponse('warning')),
        }));

        await page.locator('#run-btn').click();
        await page.locator('.sim-route-card').first().waitFor({ timeout: 5000 });

        const screenshotDir = path.join(__dirname, '..', 'data_runtime', 'simulation', 'screenshots');
        await page.screenshot({ path: path.join(screenshotDir, '003_rain_flood.png'), fullPage: false });
    });
});

test.describe('Simulation Mode — Auto-Run', () => {
    test('一括実行モーダルが開き結果が表示される', async ({ page }) => {
        await openSimulation(page);
        await page.route('/api/simulation/auto-run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(MOCK_AUTO_RUN),
        }));

        await page.locator('#auto-run-btn').click();
        await expect(page.locator('#auto-run-modal')).toBeVisible({ timeout: 5000 });
        await expect(page.locator('.sim-autorun-table')).toBeVisible();
        await expect(page.locator('.sim-autorun-table tbody tr')).toHaveCount(4);
    });

    test('PASS 行と FAIL 行が区別される', async ({ page }) => {
        await openSimulation(page);
        await page.route('/api/simulation/auto-run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(MOCK_AUTO_RUN),
        }));

        await page.locator('#auto-run-btn').click();
        await expect(page.locator('.sim-autorun-row--pass')).toHaveCount(3, { timeout: 5000 });
        await expect(page.locator('.sim-autorun-row--fail')).toHaveCount(1);
    });

    test('モーダルを閉じられる', async ({ page }) => {
        await openSimulation(page);
        await page.route('/api/simulation/auto-run', route => route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(MOCK_AUTO_RUN),
        }));

        await page.locator('#auto-run-btn').click();
        await expect(page.locator('#auto-run-modal')).toBeVisible({ timeout: 5000 });
        await page.locator('#auto-run-modal-close').click();
        await expect(page.locator('#auto-run-modal')).toBeHidden();
    });
});

test.describe('Simulation Mode — 本番API非混入確認', () => {
    test('/api/navigation/route/compare は呼ばれない', async ({ page }) => {
        let compareCallCount = 0;
        await openSimulation(page);
        await page.route('/api/navigation/route/compare', route => {
            compareCallCount++;
            return route.continue();
        });
        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify(makeRunResponse('warning')),
        }));

        await page.locator('#run-btn').click();
        await page.locator('.sim-route-card').first().waitFor({ timeout: 5000 });
        expect(compareCallCount).toBe(0);
    });

    test('/api/weather/risk/route は呼ばれない', async ({ page }) => {
        let weatherCallCount = 0;
        await openSimulation(page);
        await page.route('/api/weather/risk/route', route => {
            weatherCallCount++;
            return route.continue();
        });
        await page.route('/api/simulation/run', route => route.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify(makeRunResponse('warning')),
        }));

        await page.locator('#run-btn').click();
        await page.locator('.sim-route-card').first().waitFor({ timeout: 5000 });
        expect(weatherCallCount).toBe(0);
    });
});
