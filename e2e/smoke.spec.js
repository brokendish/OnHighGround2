/**
 * smoke.spec.js — トップ画面の基本 UI 要素確認
 *
 * backend 不要。静的 HTML の要素存在チェックのみ。
 */

'use strict';

const { test, expect } = require('@playwright/test');

test.describe('Smoke: トップ画面の基本要素', () => {
  test.beforeEach(async ({ page }) => {
    // API リクエストはすべてモックで受ける（backend 不要）
    await page.route('/api/**', route => route.fulfill({ status: 200, body: '{}' }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.goto('/');
  });

  test('ページタイトルに "OnHighGround" が含まれる', async ({ page }) => {
    await expect(page).toHaveTitle(/OnHighGround/);
  });

  test('地図コンテナが存在する', async ({ page }) => {
    await expect(page.locator('#map')).toBeVisible();
  });

  test('現在地取得ボタンが存在する', async ({ page }) => {
    await expect(page.locator('#getCurrentLocation')).toBeVisible();
  });

  test('避難先検索ボタンが存在する', async ({ page }) => {
    await expect(page.locator('#searchDestinations')).toBeVisible();
  });

  test('地図クリアボタンが存在する', async ({ page }) => {
    await expect(page.locator('#clearMap')).toBeVisible();
  });

  test('下部パネルの「操作」タブが存在する', async ({ page }) => {
    await expect(page.locator('#mbc-tab-btn-action')).toBeVisible();
  });

  test('下部パネルの「情報」タブが存在する', async ({ page }) => {
    await expect(page.locator('#mbc-tab-btn-info')).toBeVisible();
  });
});
