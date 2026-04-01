/**
 * geolocation-update.spec.js — 位置情報変更によるハザード表示更新テスト
 *
 * context.setGeolocation() で座標を切り替え、現在地ハザード情報が
 * 正しく更新されることを確認する。
 *
 * シナリオ:
 *   A: 35.6415, 139.7905 → is_danger=false  → 現在地が安全（✅ 安全 が表示）
 *   B: 35.6500, 139.8000 → is_danger=true, tsunami=inside → ⚠️ 津波 が表示
 *
 *   A → B に切り替え後:
 *     - A の「安全」表示が残らない
 *     - B の「津波」警告が表示される
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── モック定義 ────────────────────────────────────────────────────────────────

const COORDS_A = { latitude: 35.6415, longitude: 139.7905 };
const COORDS_B = { latitude: 35.6500, longitude: 139.8000 };

const HAZARD_SAFE = {
  is_danger: false,
  hazards: [],
  hazard_assessment: {},
};

const HAZARD_DANGER = {
  is_danger: true,
  hazards: ['tsunami'],
  hazard_assessment: { tsunami: 'inside', flood: 'outside' },
};

// ── ヘルパー ─────────────────────────────────────────────────────────────────

async function setupBaseMocks(page) {
  await page.route('/api/elevation**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ elevation: 3.5, lat: 35.6415, lon: 139.7905 }),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
}

async function setHazardCheckMock(page, hazardBody) {
  // 同一パターンへの再登録は最後に登録したハンドラが優先される
  await page.route('/api/hazard-check**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify(hazardBody),
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

async function getLocation(page) {
  await openSidebar(page);
  const btn = page.locator('#getCurrentLocation');
  await expect(btn).toBeEnabled({ timeout: 3000 });
  await btn.click();
  await expect(btn).toHaveText('現在地を取得', { timeout: 8000 });
}

// ── テストケース ─────────────────────────────────────────────────────────────

test.describe('Geolocation Update: 位置変更によるハザード更新テスト', () => {

  /**
   * 1. 座標 A（安全）で現在地取得 → ✅ 安全 が表示される
   */
  test('座標 A（is_danger=false）のとき「✅ 安全」が表示される', async ({ page, context }) => {
    await context.setGeolocation(COORDS_A);
    await setupBaseMocks(page);
    await setHazardCheckMock(page, HAZARD_SAFE);
    await page.goto('/');
    await getLocation(page);

    // 操作タブに切り替えて現在地ハザード行を確認
    await page.evaluate(() => {
      if (typeof switchMbcTab === 'function') switchMbcTab('action');
    });

    const hazardEl = page.locator('#mbc-current-hazard');
    await expect(hazardEl).toBeVisible({ timeout: 5000 });
    await expect(hazardEl.locator('.mbc-hazard-safe')).toBeVisible({ timeout: 3000 });
  });

  /**
   * 2. 座標 B（津波危険）で現在地取得 → ⚠️ 津波 が表示される
   */
  test('座標 B（is_danger=true, tsunami=inside）のとき「⚠️ 津波」が表示される', async ({ page, context }) => {
    await context.setGeolocation(COORDS_B);
    await setupBaseMocks(page);
    await setHazardCheckMock(page, HAZARD_DANGER);
    await page.goto('/');
    await getLocation(page);

    await page.evaluate(() => {
      if (typeof switchMbcTab === 'function') switchMbcTab('action');
    });

    const hazardEl = page.locator('#mbc-current-hazard');
    await expect(hazardEl).toBeVisible({ timeout: 5000 });
    const dangerSpan = hazardEl.locator('.mbc-hazard-danger');
    await expect(dangerSpan).toBeVisible({ timeout: 3000 });
    await expect(dangerSpan).toContainText('津波');
  });

  /**
   * 3. A（安全）→ B（津波危険）に切り替えた後:
   *    - A の「安全」表示が残らない
   *    - B の「⚠️ 津波」が表示される
   */
  test('座標 A → B に更新すると危険表示に切り替わり安全表示が残らない', async ({ page, context }) => {
    // ── 座標 A で初回取得 ────────────────────────────────────────────────
    await context.setGeolocation(COORDS_A);
    await setupBaseMocks(page);
    await setHazardCheckMock(page, HAZARD_SAFE);
    await page.goto('/');
    await getLocation(page);

    await page.evaluate(() => {
      if (typeof switchMbcTab === 'function') switchMbcTab('action');
    });

    const hazardEl = page.locator('#mbc-current-hazard');
    await expect(hazardEl.locator('.mbc-hazard-safe')).toBeVisible({ timeout: 5000 });

    // ── 座標 B に切り替えてハザードモックも差し替え ───────────────────────
    await context.setGeolocation(COORDS_B);
    await setHazardCheckMock(page, HAZARD_DANGER);

    // 再度現在地取得
    const btn = page.locator('#getCurrentLocation');
    await btn.click();
    await expect(btn).toHaveText('現在地を取得', { timeout: 8000 });

    // B の危険表示が出ること
    const dangerSpan = hazardEl.locator('.mbc-hazard-danger');
    await expect(dangerSpan).toBeVisible({ timeout: 5000 });
    await expect(dangerSpan).toContainText('津波');

    // A の安全表示が残っていないこと
    await expect(hazardEl.locator('.mbc-hazard-safe')).toHaveCount(0);
  });

  /**
   * 4. A（安全）→ B（津波危険）切り替え後に位置マーカー更新が行われている
   *    （getCurrentLocation ボタンが正常完了テキストに戻ることで確認）
   */
  test('座標切り替え後に getCurrentLocation が正常完了する', async ({ page, context }) => {
    await context.setGeolocation(COORDS_A);
    await setupBaseMocks(page);
    await setHazardCheckMock(page, HAZARD_SAFE);
    await page.goto('/');
    await getLocation(page);

    // 座標 B に切り替え
    await context.setGeolocation(COORDS_B);
    await setHazardCheckMock(page, HAZARD_DANGER);

    const btn = page.locator('#getCurrentLocation');
    await btn.click();
    // エラーなく「現在地を取得」に戻ること
    await expect(btn).toHaveText('現在地を取得', { timeout: 8000 });
  });

});
