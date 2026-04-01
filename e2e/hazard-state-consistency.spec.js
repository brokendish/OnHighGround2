/**
 * hazard-state-consistency.spec.js — safe / unknown / unsafe 3 状態一貫性テスト
 *
 * 推奨カード（#recommendedCard）と候補カード（#destinationsPanel）で
 * hazard_safe の 3 状態が一貫して表示されることを保証する。
 *
 * 検証観点:
 *   - safe    : 危険区域外バッジ が両カードに表示、false safe（unknown/unsafe が混在しない）
 *   - unknown : 安全性未判定バッジが両カードに表示、safe バッジが表示されない
 *   - unsafe  : 危険区域内バッジ が両カードに表示、推奨カードのボタン文言が「⚠️ 注意して案内」
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── モックレスポンス生成 ─────────────────────────────────────────────────────

function makeEvacuationBody(hazardSafe, tsunamiStatus) {
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
    hazard_assessment: { tsunami: tsunamiStatus, flood: 'outside' },
  };
  return {
    current_location: { lat: 35.6415, lon: 139.7905, elevation: 3.5 },
    hazard_status: { is_danger: false, hazards: [] },
    time_to_impact: { supported: false },
    recommended: { ...dest, reason: 'テスト用' },
    destinations: [dest],
    search_parameters: { transport_mode: 'walking', max_distance: 2000, min_elevation_gain: 10 },
  };
}

async function setupMocks(page, hazardSafe, tsunamiStatus) {
  await page.route('/api/elevation**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ elevation: 3.5, lat: 35.6415, lon: 139.7905 }),
  }));
  await page.route('/api/hazard-check**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ is_danger: false, hazards: [], hazard_assessment: {} }),
  }));
  await page.route('/api/evacuation', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify(makeEvacuationBody(hazardSafe, tsunamiStatus)),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
}

async function openSidebar(page) {
  const wrapper = page.locator('#sidebarWrapper');
  const isOpen = await wrapper.evaluate(el => !el.classList.contains('collapsed'));
  if (!isOpen) {
    await page.locator('#sidebarToggle').click();
    await expect(wrapper).not.toHaveClass(/collapsed/, { timeout: 3000 });
  }
}

async function triggerSearch(page) {
  await openSidebar(page);
  await page.locator('#getCurrentLocation').click();
  await expect(page.locator('#getCurrentLocation')).toHaveText('現在地を取得', { timeout: 8000 });
  const searchBtn = page.locator('#searchDestinations');
  await expect(searchBtn).toBeEnabled({ timeout: 5000 });
  await searchBtn.click();
  await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
}

// ── テストケース ─────────────────────────────────────────────────────────────

test.describe('Hazard State Consistency: 3 状態一貫性テスト', () => {

  // ── safe 状態 ──────────────────────────────────────────────────────────────

  test.describe('safe (hazard_safe=true, all outside)', () => {

    test('推奨カードに「危険区域外」バッジが表示される', async ({ page }) => {
      await setupMocks(page, true, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#recommendedCard .hazard-safe-badge.safe').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('候補カードに「危険区域外」バッジが表示される', async ({ page }) => {
      await setupMocks(page, true, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#destinationsPanel .hazard-safe-badge.safe').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('safe 状態のとき unknown / unsafe バッジが表示されない', async ({ page }) => {
      await setupMocks(page, true, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      await expect(page.locator('.hazard-safe-badge.unknown')).toHaveCount(0);
      await expect(page.locator('.hazard-safe-badge.unsafe')).toHaveCount(0);
    });

    test('safe 状態のとき hazard-reason-block に「安全（全ハザード外）」が表示される', async ({ page }) => {
      await setupMocks(page, true, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      const safePill = page.locator('.hazard-reason-item.is-safe').first();
      await expect(safePill).toBeVisible({ timeout: 5000 });
    });

  });

  // ── unknown 状態 ───────────────────────────────────────────────────────────

  test.describe('unknown (hazard_safe=null, tsunami=unknown)', () => {

    test('推奨カードに「安全性未判定」バッジが表示される', async ({ page }) => {
      await setupMocks(page, null, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#recommendedCard .hazard-safe-badge.unknown').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('候補カードに「安全性未判定」バッジが表示される', async ({ page }) => {
      await setupMocks(page, null, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#destinationsPanel .hazard-safe-badge.unknown').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('unknown 状態のとき safe バッジが表示されない（false safe 防止）', async ({ page }) => {
      await setupMocks(page, null, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      // safe バッジが 0 件であること
      await expect(page.locator('.hazard-safe-badge.safe')).toHaveCount(0);
    });

    test('unknown 状態のとき「安全（全ハザード外）」文言がページに存在しない', async ({ page }) => {
      await setupMocks(page, null, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      await expect(page.locator('text=安全（全ハザード外）')).toHaveCount(0);
    });

    test('unknown 状態のとき hazard-reason-block に「未判定（安全確認不可）」が表示される', async ({ page }) => {
      await setupMocks(page, null, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      const pill = page.locator('.hazard-reason-item.is-unknown').first();
      await expect(pill).toBeVisible({ timeout: 5000 });
      await expect(pill).toContainText('未判定（安全確認不可）');
    });

  });

  // ── unsafe 状態 ────────────────────────────────────────────────────────────

  test.describe('unsafe (hazard_safe=false, tsunami=inside)', () => {

    test('推奨カードに「危険区域内」バッジが表示される', async ({ page }) => {
      await setupMocks(page, false, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#recommendedCard .hazard-safe-badge.unsafe').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('候補カードに「危険区域内」バッジが表示される', async ({ page }) => {
      await setupMocks(page, false, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#destinationsPanel .hazard-safe-badge.unsafe').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('unsafe 状態のとき推奨カードのボタン文言が「⚠️ 注意して案内」になる', async ({ page }) => {
      await setupMocks(page, false, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      const btn = page.locator('#recommendedRouteBtn');
      await expect(btn).toBeVisible({ timeout: 5000 });
      await expect(btn).toContainText('注意して案内');
    });

    test('unsafe 状態のとき safe / unknown バッジが表示されない', async ({ page }) => {
      await setupMocks(page, false, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      await expect(page.locator('.hazard-safe-badge.safe')).toHaveCount(0);
      await expect(page.locator('.hazard-safe-badge.unknown')).toHaveCount(0);
    });

  });

});
