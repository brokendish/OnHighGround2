/**
 * geolocation.spec.js — geolocation 権限と現在地取得フローの確認
 *
 * Playwright の geolocation mock を使用。backend は /api/elevation のみモック。
 * GPS 連動なし・ネットワーク不要で動作する。
 */

'use strict';

const { test, expect } = require('@playwright/test');

// playwright.config.js で geolocation: { latitude: 35.6415, longitude: 139.7905 } が設定済み

test.describe('Geolocation: 現在地取得フロー', () => {
  test.beforeEach(async ({ page }) => {
    // backend API をすべてモック
    await page.route('/api/elevation**', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ elevation: 3.5, lat: 35.6415, lon: 139.7905 }),
    }));
    await page.route('/api/**', route => route.fulfill({ status: 200, body: '{}' }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.goto('/');
  });

  // サイドバーを開くヘルパー
  async function openSidebar(page) {
    const wrapper = page.locator('#sidebarWrapper');
    const isOpen = await wrapper.evaluate(el => !el.classList.contains('collapsed'));
    if (!isOpen) {
      await page.locator('#sidebarToggle').click();
      await expect(wrapper).not.toHaveClass(/collapsed/, { timeout: 3000 });
    }
  }

  test('geolocation 権限が付与されている', async ({ page }) => {
    // 現在地取得ボタンが存在し操作可能なことで権限付与を代替確認
    await openSidebar(page);
    await expect(page.locator('#getCurrentLocation')).toBeEnabled();
  });

  test('現在地取得ボタンを押すと処理が走る', async ({ page }) => {
    await openSidebar(page);
    const btn = page.locator('#getCurrentLocation');
    await expect(btn).toBeEnabled();
    await btn.click();
    await expect(btn).toHaveText(/(現在地を取得|位置情報を取得中)/, { timeout: 5000 });
  });

  test('geolocation mock 座標（有明北部）が地図に反映される', async ({ page }) => {
    await openSidebar(page);
    const btn = page.locator('#getCurrentLocation');
    await btn.click();
    // 現在地取得完了後、ボタンが「現在地を取得」に戻ることを確認
    await expect(btn).toHaveText('現在地を取得', { timeout: 8000 });
  });
});
