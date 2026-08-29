/**
 * hazard-state-consistency.spec.js — HAZARD_DETECTED / NO_HAZARD_RECORD / SOURCE_UNAVAILABLE 3 状態一貫性テスト
 *
 * 推奨カード（#recommendedCard）と候補カード（#destinationsPanel）で
 * hazard_coverage_status から算出される aggregate_status の 3 状態が
 * 一貫して表示されることを保証する（Round 12D-B: NEW-ADV-003）。
 *
 * 検証観点:
 *   - NO_HAZARD_RECORD   : safe バッジ が両カードに表示、unknown/unsafe が混在しない
 *   - SOURCE_UNAVAILABLE : unknown バッジが両カードに表示、safe バッジが表示されない
 *   - HAZARD_DETECTED    : unsafe バッジ が両カードに表示、推奨カードのボタン文言が「⚠️ 注意して案内」
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── モックレスポンス生成 ─────────────────────────────────────────────────────

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

function computeAggregate(coverage) {
  const values = Object.values(coverage);
  if (values.includes('HAZARD_DETECTED')) return 'HAZARD_DETECTED';
  if (values.includes('SOURCE_UNAVAILABLE')) return 'SOURCE_UNAVAILABLE';
  return 'NO_HAZARD_RECORD';
}

function makeEvacuationBody(tsunamiStatus, floodStatus = 'outside') {
  const coverage = makeCoverageStatus(tsunamiStatus, floodStatus);
  const aggregate = computeAggregate(coverage);
  const hazardSafe = aggregate === 'HAZARD_DETECTED' ? false : null;
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
    hazard_assessment: { tsunami: tsunamiStatus, flood: floodStatus },
  };
  return {
    current_location: { lat: 35.6415, lon: 139.7905, elevation: 3.5 },
    hazard_status: { is_danger: false, hazards: [] },
    time_to_impact: { supported: false },
    recommended: { ...dest, reason: 'テスト用' },
    recommendation_meta: {
      selected_tier: aggregate,
      safe_candidates_found: aggregate === 'NO_HAZARD_RECORD' ? 1 : 0,
      total_candidates_found: 1,
      exclude_unsafe_candidates: false,
    },
    destinations: [dest],
    search_parameters: { transport_mode: 'walking', max_distance: 2000, min_elevation_gain: 10 },
  };
}

async function setupMocks(page, tsunamiStatus, floodStatus = 'outside') {
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
    body: JSON.stringify(makeEvacuationBody(tsunamiStatus, floodStatus)),
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

  // ── NO_HAZARD_RECORD 状態 ─────────────────────────────────────────────────

  test.describe('NO_HAZARD_RECORD (全ハザード該当記録なし)', () => {

    test('推奨カードに safe バッジが表示される', async ({ page }) => {
      await setupMocks(page, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#recommendedCard .hazard-safe-badge.safe').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('候補カードに safe バッジが表示される', async ({ page }) => {
      await setupMocks(page, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#destinationsPanel .hazard-safe-badge.safe').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('NO_HAZARD_RECORD 状態のとき unknown / unsafe バッジが表示されない', async ({ page }) => {
      await setupMocks(page, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      await expect(page.locator('.hazard-safe-badge.unknown')).toHaveCount(0);
      await expect(page.locator('.hazard-safe-badge.unsafe')).toHaveCount(0);
    });

    test('NO_HAZARD_RECORD 状態のとき hazard-reason-block に該当ハザード記録なしの文言が表示される', async ({ page }) => {
      await setupMocks(page, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      const safePill = page.locator('.hazard-reason-item.is-safe').first();
      await expect(safePill).toBeVisible({ timeout: 5000 });
      await expect(safePill).toContainText('該当ハザード記録なし');
      await expect(safePill).toContainText('危険がないことを示すものではありません');
    });

    test('NO_HAZARD_RECORD 状態のとき recommendation_meta.selected_tier のtierLabelが正しく表示される', async ({ page }) => {
      await setupMocks(page, 'outside');
      await page.goto('/');
      await triggerSearch(page);

      const metaNote = page.locator('.recommendation-meta-note').first();
      await expect(metaNote).toBeVisible({ timeout: 5000 });
      await expect(metaNote).toContainText('該当ハザード記録なし');
      const text = await metaNote.textContent();
      expect(text).not.toContain('安全');
    });

  });

  // ── SOURCE_UNAVAILABLE 状態 ──────────────────────────────────────────────

  test.describe('SOURCE_UNAVAILABLE (tsunami=unknown)', () => {

    test('推奨カードに unknown バッジが表示される', async ({ page }) => {
      await setupMocks(page, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#recommendedCard .hazard-safe-badge.unknown').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('候補カードに unknown バッジが表示される', async ({ page }) => {
      await setupMocks(page, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#destinationsPanel .hazard-safe-badge.unknown').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('SOURCE_UNAVAILABLE 状態のとき safe バッジが表示されない（false safe 防止）', async ({ page }) => {
      await setupMocks(page, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      // safe バッジが 0 件であること
      await expect(page.locator('.hazard-safe-badge.safe')).toHaveCount(0);
    });

    test('SOURCE_UNAVAILABLE 状態のとき禁止文言（安全（全ハザード外））がページに存在しない', async ({ page }) => {
      await setupMocks(page, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      await expect(page.locator('text=安全（全ハザード外）')).toHaveCount(0);
    });

    test('SOURCE_UNAVAILABLE 状態のとき候補自体の安全性claim（バッジ／reasonピル）に該当ハザード記録なし文言が付かない', async ({ page }) => {
      await setupMocks(page, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      // recommendation-meta-note の「該当ハザード記録なし候補数: 0件」のような統計表示は
      // 選定候補自体の安全性claimではないため対象外とし、候補バッジ・reasonピルのみを検査する。
      const badgeTexts = await page.locator('.hazard-safe-badge').allTextContents();
      for (const t of badgeTexts) expect(t).not.toContain('該当ハザード記録なし');
      const reasonTexts = await page.locator('.hazard-reason-item').allTextContents();
      for (const t of reasonTexts) expect(t).not.toContain('該当ハザード記録なし');
      await expect(page.locator('.hazard-reason-item.is-safe')).toHaveCount(0);
    });

    test('SOURCE_UNAVAILABLE 状態のとき hazard-reason-block に「ハザード情報を確認できません」が表示される', async ({ page }) => {
      await setupMocks(page, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      const pill = page.locator('.hazard-reason-item.is-unknown').first();
      await expect(pill).toBeVisible({ timeout: 5000 });
      await expect(pill).toContainText('ハザード情報を確認できません');
    });

    test('SOURCE_UNAVAILABLE 状態のとき recommendation_meta.selected_tier のtierLabelが正しく表示される', async ({ page }) => {
      await setupMocks(page, 'unknown');
      await page.goto('/');
      await triggerSearch(page);

      const metaNote = page.locator('.recommendation-meta-note').first();
      await expect(metaNote).toBeVisible({ timeout: 5000 });
      await expect(metaNote).toContainText('ハザード情報を確認できません候補から選定');
      const text = await metaNote.textContent();
      expect(text).not.toContain('安全');
    });

  });

  // ── HAZARD_DETECTED 状態 ─────────────────────────────────────────────────

  test.describe('HAZARD_DETECTED (tsunami=inside)', () => {

    test('推奨カードに unsafe バッジが表示される', async ({ page }) => {
      await setupMocks(page, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#recommendedCard .hazard-safe-badge.unsafe').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('候補カードに unsafe バッジが表示される', async ({ page }) => {
      await setupMocks(page, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      const badge = page.locator('#destinationsPanel .hazard-safe-badge.unsafe').first();
      await expect(badge).toBeVisible({ timeout: 5000 });
    });

    test('HAZARD_DETECTED 状態のとき推奨カードのボタン文言が「⚠️ 注意して案内」になる', async ({ page }) => {
      await setupMocks(page, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      const btn = page.locator('#recommendedRouteBtn');
      await expect(btn).toBeVisible({ timeout: 5000 });
      await expect(btn).toContainText('注意して案内');
    });

    test('HAZARD_DETECTED 状態のとき safe / unknown バッジが表示されない', async ({ page }) => {
      await setupMocks(page, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
      await expect(page.locator('.hazard-safe-badge.safe')).toHaveCount(0);
      await expect(page.locator('.hazard-safe-badge.unknown')).toHaveCount(0);
    });

    test('HAZARD_DETECTED 状態のとき recommendation_meta.selected_tier のtierLabelが正しく表示される', async ({ page }) => {
      await setupMocks(page, 'inside');
      await page.goto('/');
      await triggerSearch(page);

      const metaNote = page.locator('.recommendation-meta-note').first();
      await expect(metaNote).toBeVisible({ timeout: 5000 });
      await expect(metaNote).toContainText('ハザード検出区域を含む候補から選定');
      const text = await metaNote.textContent();
      expect(text).not.toContain('安全');
    });

  });

});
