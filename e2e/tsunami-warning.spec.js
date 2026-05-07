'use strict';

const { test, expect } = require('@playwright/test');

function tsunamiBody(level) {
  if (level === 'none') {
    return {
      source: 'mock',
      status: 'none',
      observed_at: null,
      updated_at: new Date().toISOString(),
      ttl_seconds: 60,
      areas: [],
      message: '',
    };
  }
  const labels = {
    major_warning: '大津波警報',
    warning: '津波警報',
    advisory: '津波注意報',
  };
  return {
    source: 'mock',
    status: 'active',
    observed_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ttl_seconds: 60,
    areas: [{
      code: null,
      name: '東京湾内湾',
      level,
      level_label: labels[level],
      expected_height: null,
      arrival_time: null,
      is_target: true,
    }],
    message: `${labels[level]}が発表されています。`,
  };
}

async function setupCommonMocks(page, level) {
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('/api/tsunami/warnings/current', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(tsunamiBody(level)),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
}

test.describe('Tsunami warning banner', () => {
  test('通常時は控えめに非表示で、地図表示を壊さない', async ({ page }) => {
    await setupCommonMocks(page, 'none');
    await page.goto('/');

    await expect(page.locator('#map')).toBeVisible();
    await expect(page.locator('#tsunami-warning-banner')).toBeHidden();
  });

  test('津波注意報は橙系バナーで対象エリアを表示する', async ({ page }) => {
    await setupCommonMocks(page, 'advisory');
    await page.goto('/');

    const banner = page.locator('#tsunami-warning-banner');
    await expect(banner).toBeVisible({ timeout: 5000 });
    await expect(banner).toHaveClass(/tw-advisory/);
    await expect(banner).toContainText('東京湾内湾');
  });

  test('津波警報は赤系バナーを出し津波レイヤーを自動ONにする', async ({ page }) => {
    await setupCommonMocks(page, 'warning');
    await page.goto('/');

    const banner = page.locator('#tsunami-warning-banner');
    await expect(banner).toBeVisible({ timeout: 5000 });
    await expect(banner).toHaveClass(/tw-danger/);
    await expect(page.locator('#showTsunamiHazardTokyo')).toBeChecked();
  });

  test('津波警報中はナビ中UIにも警告を表示する', async ({ page }) => {
    await setupCommonMocks(page, 'warning');
    await page.goto('/');

    await page.evaluate(async () => {
      navigationMode = 'navigation_active';
      await _tsunamiWarningUpdate();
    });

    const navBanner = page.locator('#navBanner');
    await expect(navBanner).toBeVisible({ timeout: 5000 });
    await expect(navBanner).toContainText('津波警報');
    await expect(navBanner).toHaveClass(/nav-banner-danger/);
  });

  test('大津波警報は最重要警告文言として表示する', async ({ page }) => {
    await setupCommonMocks(page, 'major_warning');
    await page.goto('/');

    const banner = page.locator('#tsunami-warning-banner');
    await expect(banner).toBeVisible({ timeout: 5000 });
    await expect(banner).toHaveClass(/tw-danger/);
    await expect(banner).toContainText('大津波警報');
  });
});
