'use strict';

const { test, expect } = require('@playwright/test');

async function setupBasicMocks(page) {
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
}

test.describe('Navigation Debug Layer', () => {
  test.beforeEach(async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await page.waitForFunction(() =>
      typeof window.addNavigationDebugEvent === 'function' &&
      typeof window.setNavigationDebugLayerVisible === 'function' &&
      typeof window.__getNavigationDebugState === 'function'
    );
  });

  test('レイヤーパネルから表示ONしてイベントマーカーを表示・クリアできる', async ({ page }) => {
    await page.locator('#layer-toggle-btn').click();
    await expect(page.locator('#nav-debug-layer-toggle')).toBeVisible();
    await page.locator('#nav-debug-layer-toggle').check();

    await page.evaluate(() => {
      window.addNavigationDebugEvent({
        type: 'offroute_detected',
        lat: 35.6762,
        lon: 139.6503,
        message: 'offroute detected distance=25.2m',
        level: 'INFO',
        context: {
          off_route_distance: 25.2,
          threshold: 18,
          near_goal: true
        }
      });
    });

    await expect(page.locator('.nav-debug-marker')).toHaveCount(1);
    await page.locator('.nav-debug-marker').click();
    await expect(page.locator('.leaflet-popup-content')).toContainText('offroute_detected');
    await expect(page.locator('#nav-debug-layer-status')).toContainText('1 / 100 events');

    await page.evaluate(() => window.setNavigationDebugLayerVisible(false));
    await expect(page.locator('.nav-debug-marker')).toHaveCount(0);

    await page.evaluate(() => window.setNavigationDebugLayerVisible(true));
    await expect(page.locator('.nav-debug-marker')).toHaveCount(1);

    await page.evaluate(() => window.clearNavigationDebugEvents());
    await expect(page.locator('.nav-debug-marker')).toHaveCount(0);
    await expect(page.locator('#nav-debug-layer-status')).toContainText('0 / 100 events');
  });

  test('100件を超えたイベントは古いものから削除される', async ({ page }) => {
    await page.evaluate(() => {
      window.setNavigationDebugLayerVisible(true);
      for (let index = 0; index < 105; index += 1) {
        window.addNavigationDebugEvent({
          type: 'reroute_success',
          lat: 35.6762 + (index * 0.00001),
          lon: 139.6503 + (index * 0.00001),
          message: `reroute success ${index}`,
          level: 'INFO',
          context: { duration_ms: index }
        });
      }
    });

    const state = await page.evaluate(() => window.__getNavigationDebugState());
    expect(state.count).toBe(100);
    expect(state.events[0].message).toBe('reroute success 5');
    expect(state.events[state.events.length - 1].message).toBe('reroute success 104');
  });
});
