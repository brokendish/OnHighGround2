/**
 * evacuation-ui.spec.js — 避難先 UI の false safe 回帰テスト
 *
 * backend を page.route() でモックし、UI が正しく unknown/safe を表示することを確認。
 * 安全性クリティカル: hazard_safe=null + tsunami='unknown' のとき
 *   ✓ 「安全性未判定」が表示される
 *   ✓ 「未判定（安全確認不可）」が表示される
 *   ✗ 「安全（全ハザード外）」が表示されない
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── モックレスポンス定義 ──────────────────────────────────────────────────────

const MOCK_ELEVATION = {
  elevation: 3.5,
  lat: 35.6415,
  lon: 139.7905,
};

const MOCK_HAZARD_CHECK = {
  is_danger: false,
  hazards: [],
  assessment: { tsunami: 'unknown', flood: 'outside' },
};

/** hazard_safe=null, tsunami=unknown の候補を含む避難先レスポンス */
function makeEvacuationResponse(hazardSafe, tsunamiStatus) {
  return {
    current_location: { lat: 35.6415, lon: 139.7905, elevation: 3.5 },
    hazard_status: { is_danger: false, hazards: [] },
    time_to_impact: { supported: false },
    recommended: {
      name: '東雲小学校',
      type: 'emergency_shelter',
      lat: 35.65,
      lon: 139.80,
      elevation: 5.0,
      elevation_gain: 1.5,
      distance: 800,
      estimated_time_minutes: 12,
      safety_score: 45.0,
      hazard_safe: hazardSafe,
      hazard_assessment: {
        tsunami: tsunamiStatus,
        flood: 'outside',
      },
      reason: 'テスト用候補',
    },
    destinations: [
      {
        name: '東雲小学校',
        type: 'emergency_shelter',
        lat: 35.65,
        lon: 139.80,
        elevation: 5.0,
        elevation_gain: 1.5,
        distance: 800,
        estimated_time_minutes: 12,
        safety_score: 45.0,
        hazard_safe: hazardSafe,
        hazard_assessment: {
          tsunami: tsunamiStatus,
          flood: 'outside',
        },
      },
    ],
    search_parameters: {
      transport_mode: 'walking',
      max_distance: 2000,
      min_elevation_gain: 10,
    },
  };
}

// ── テスト共通セットアップ ────────────────────────────────────────────────────

async function setupMocks(page, { hazardSafe, tsunamiStatus }) {
  await page.route('/api/elevation**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(MOCK_ELEVATION),
  }));
  await page.route('/api/hazard-check**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(MOCK_HAZARD_CHECK),
  }));
  await page.route('/api/evacuation', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(makeEvacuationResponse(hazardSafe, tsunamiStatus)),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
}

async function triggerEvacuationSearch(page) {
  // サイドバーは collapsed 状態で起動するため、まず開く
  const sidebarWrapper = page.locator('#sidebarWrapper');
  const isSidebarOpen = await sidebarWrapper.evaluate(el => !el.classList.contains('collapsed'));
  if (!isSidebarOpen) {
    await page.locator('#sidebarToggle').click();
    await expect(sidebarWrapper).not.toHaveClass(/collapsed/, { timeout: 3000 });
  }

  // 現在地を設定（geolocation mock: 35.6415, 139.7905）
  await page.locator('#getCurrentLocation').click();
  await expect(page.locator('#getCurrentLocation')).toHaveText('現在地を取得', { timeout: 8000 });

  // 避難先検索
  const searchBtn = page.locator('#searchDestinations');
  await expect(searchBtn).toBeEnabled({ timeout: 5000 });
  await searchBtn.click();

  // 結果パネルが表示されるまで待つ
  await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
}

// ── テストケース ─────────────────────────────────────────────────────────────

test.describe('Evacuation UI: false safe 回帰テスト', () => {

  /**
   * A. hazard_safe=null + tsunami='unknown' のとき
   *    「安全性未判定」「未判定（安全確認不可）」が表示され
   *    「安全（全ハザード外）」は表示されない
   */
  test('hazard_safe=null のとき「安全性未判定」バッジが表示される', async ({ page }) => {
    await setupMocks(page, { hazardSafe: null, tsunamiStatus: 'unknown' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    // 候補カード内に「安全性未判定」バッジが存在すること
    const unknownBadge = page.locator('.hazard-safe-badge.unknown').first();
    await expect(unknownBadge).toBeVisible({ timeout: 5000 });
    await expect(unknownBadge).toContainText('安全性未判定');
  });

  test('hazard_safe=null のとき「安全（全ハザード外）」が表示されない', async ({ page }) => {
    await setupMocks(page, { hazardSafe: null, tsunamiStatus: 'unknown' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });

    // 「安全（全ハザード外）」テキストが存在しないこと（false safe を防ぐ）
    await expect(page.locator('text=安全（全ハザード外）')).toHaveCount(0);
  });

  test('tsunami=unknown のとき hazard-reason-block が「未判定（安全確認不可）」を表示する', async ({ page }) => {
    await setupMocks(page, { hazardSafe: null, tsunamiStatus: 'unknown' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });

    // hazard-reason-block 内に「未判定（安全確認不可）」が存在すること
    const unknownPill = page.locator('.hazard-reason-item.is-unknown').first();
    await expect(unknownPill).toBeVisible({ timeout: 5000 });
    await expect(unknownPill).toContainText('未判定（安全確認不可）');
  });

  /**
   * B. hazard_safe=true + 全 outside のとき「安全（全ハザード外）」が正しく表示される
   *    （false safe の反対: 本来 safe のものが safe と表示されること）
   */
  test('hazard_safe=true のとき「危険区域外」バッジが表示される', async ({ page }) => {
    await setupMocks(page, { hazardSafe: true, tsunamiStatus: 'outside' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    const safeBadge = page.locator('.hazard-safe-badge.safe').first();
    await expect(safeBadge).toBeVisible({ timeout: 5000 });
  });

  test('hazard_safe=true + 全 outside のとき hazard-reason-block が「安全（全ハザード外）」を表示する', async ({ page }) => {
    await setupMocks(page, { hazardSafe: true, tsunamiStatus: 'outside' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });

    const safePill = page.locator('.hazard-reason-item.is-safe').first();
    await expect(safePill).toBeVisible({ timeout: 5000 });
    await expect(safePill).toContainText('安全（全ハザード外）');
  });

  /**
   * C. hazard_safe=false のとき「危険区域内」バッジが表示される
   */
  test('hazard_safe=false のとき「危険区域内」バッジが表示される', async ({ page }) => {
    await setupMocks(page, { hazardSafe: false, tsunamiStatus: 'inside' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    const unsafeBadge = page.locator('.hazard-safe-badge.unsafe').first();
    await expect(unsafeBadge).toBeVisible({ timeout: 5000 });
    await expect(unsafeBadge).toContainText('危険区域内');
  });
});
