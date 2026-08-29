/**
 * evacuation-ui.spec.js — 避難先 UI の false safe 回帰テスト
 *
 * backend を page.route() でモックし、UI が hazard_coverage_status から算出される
 * aggregate_status（HAZARD_DETECTED / NO_HAZARD_RECORD / SOURCE_UNAVAILABLE）を
 * 正しく表示することを確認する（Round 12D-B: NEW-ADV-003）。
 *
 * 安全性クリティカル: tsunami='unknown'（SOURCE_UNAVAILABLE）のとき
 *   ✓ 「安全性未判定」相当の unknown バッジが表示される
 *   ✓ 「ハザード情報を確認できません」が表示される
 *   ✗ 「該当ハザード記録なし」「安全（全ハザード外）」が表示されない
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

const STATUS_MAP = { outside: 'NO_HAZARD_RECORD', unknown: 'SOURCE_UNAVAILABLE', inside: 'HAZARD_DETECTED' };

function makeCoverageStatus(tsunamiStatus, floodStatus = 'outside') {
  return {
    flood: STATUS_MAP[floodStatus] || 'NO_HAZARD_RECORD',
    storm_surge: 'NO_HAZARD_RECORD',
    tsunami: STATUS_MAP[tsunamiStatus] || 'NO_HAZARD_RECORD',
    inland_flood: 'NO_HAZARD_RECORD',
    landslide: 'NO_HAZARD_RECORD',
    lowland_poor_drainage: 'NO_HAZARD_RECORD',
  };
}

/** tsunami=unknown/outside/inside の候補を含む避難先レスポンス */
function makeEvacuationResponse(tsunamiStatus, floodStatus = 'outside') {
  const coverage = makeCoverageStatus(tsunamiStatus, floodStatus);
  const hazardSafe = Object.values(coverage).includes('HAZARD_DETECTED') ? false : null;
  const dest = {
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
    hazard_coverage_status: coverage,
    hazard_assessment: {
      tsunami: tsunamiStatus,
      flood: floodStatus,
    },
  };
  return {
    current_location: { lat: 35.6415, lon: 139.7905, elevation: 3.5 },
    hazard_status: { is_danger: false, hazards: [] },
    time_to_impact: { supported: false },
    recommended: { ...dest, reason: 'テスト用候補' },
    destinations: [dest],
    search_parameters: {
      transport_mode: 'walking',
      max_distance: 2000,
      min_elevation_gain: 10,
    },
  };
}

// ── テスト共通セットアップ ────────────────────────────────────────────────────

async function setupMocks(page, { tsunamiStatus, floodStatus = 'outside' }) {
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
    body: JSON.stringify(makeEvacuationResponse(tsunamiStatus, floodStatus)),
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
   * A. tsunami='unknown'（SOURCE_UNAVAILABLE）のとき
   *    unknown バッジ・「ハザード情報を確認できません」が表示され
   *    「該当ハザード記録なし」「安全（全ハザード外）」は表示されない
   */
  test('SOURCE_UNAVAILABLE のとき unknown バッジが表示される', async ({ page }) => {
    await setupMocks(page, { tsunamiStatus: 'unknown' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    // 候補カード内に unknown バッジが存在すること
    const unknownBadge = page.locator('.hazard-safe-badge.unknown').first();
    await expect(unknownBadge).toBeVisible({ timeout: 5000 });
    await expect(unknownBadge).toContainText('ハザード情報を確認できません');
  });

  test('SOURCE_UNAVAILABLE のとき禁止文言（該当ハザード記録なし／安全（全ハザード外））が表示されない', async ({ page }) => {
    await setupMocks(page, { tsunamiStatus: 'unknown' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });

    // false safe を防ぐ: 該当ハザード記録なし／安全（全ハザード外）は存在しないこと
    await expect(page.locator('text=該当ハザード記録なし')).toHaveCount(0);
    await expect(page.locator('text=安全（全ハザード外）')).toHaveCount(0);
  });

  test('tsunami=unknown のとき hazard-reason-block が「ハザード情報を確認できません」を表示する', async ({ page }) => {
    await setupMocks(page, { tsunamiStatus: 'unknown' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });

    // hazard-reason-block 内に「ハザード情報を確認できません」が存在すること
    const unknownPill = page.locator('.hazard-reason-item.is-unknown').first();
    await expect(unknownPill).toBeVisible({ timeout: 5000 });
    await expect(unknownPill).toContainText('ハザード情報を確認できません');
  });

  /**
   * B. 全 outside（NO_HAZARD_RECORD）のとき該当ハザード記録なしの文言が正しく表示される
   *    （false safe の反対: 本来 NO_HAZARD_RECORD のものが正しく表示されること）
   */
  test('NO_HAZARD_RECORD のとき safe バッジが表示される', async ({ page }) => {
    await setupMocks(page, { tsunamiStatus: 'outside' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    const safeBadge = page.locator('.hazard-safe-badge.safe').first();
    await expect(safeBadge).toBeVisible({ timeout: 5000 });
  });

  test('NO_HAZARD_RECORD のとき hazard-reason-block が該当ハザード記録なしの文言を表示する', async ({ page }) => {
    await setupMocks(page, { tsunamiStatus: 'outside' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });

    const safePill = page.locator('.hazard-reason-item.is-safe').first();
    await expect(safePill).toBeVisible({ timeout: 5000 });
    await expect(safePill).toContainText('該当ハザード記録なし');
    await expect(safePill).toContainText('危険がないことを示すものではありません');
  });

  /**
   * C. tsunami=inside（HAZARD_DETECTED）のとき unsafe バッジが表示される
   */
  test('HAZARD_DETECTED のとき unsafe バッジが表示される', async ({ page }) => {
    await setupMocks(page, { tsunamiStatus: 'inside' });
    await page.goto('/');
    await triggerEvacuationSearch(page);

    const unsafeBadge = page.locator('.hazard-safe-badge.unsafe').first();
    await expect(unsafeBadge).toBeVisible({ timeout: 5000 });
    await expect(unsafeBadge).toContainText('ハザード検出');
  });
});
