'use strict';

const { test, expect } = require('@playwright/test');

const POLL_MS = 300;

function quake(id, name, minute, lat, lng, intensity, magnitude = 4) {
  return {
    event_id: id,
    occurred_at: `2026-04-29T10:${String(minute).padStart(2, '0')}:00+09:00`,
    epicenter_name: name,
    lat,
    lng,
    max_intensity: intensity,
    magnitude,
    source: 'mock',
  };
}

function baseItems() {
  return [
    quake('eq-low-near', '近い震度1', 10, 35.682, 139.768, '1', 2.1),
    quake('eq-high-far', '遠い震度4', 9, 40.0, 141.0, '4', 4.1),
  ];
}

function withNewItems() {
  return [
    quake('eq-new-high-near', '新着近距離4', 12, 35.6815, 139.7675, '4', 4.2),
    quake('eq-new-low-near', '新着対象外1', 11, 35.6817, 139.7677, '1', 2.2),
    ...baseItems(),
  ];
}

async function setupPage(page, routeHandler) {
  await page.addInitScript(interval => {
    window.__MAGNITUDE_POLL_INTERVAL_MS = interval;
  }, POLL_MS);
  await page.route('/favicon.ico', route => route.fulfill({ status: 204, body: '' }));
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('/api/admin/config/stream', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'retry: 10000\n\n',
  }));
  await page.route('/api/admin/config**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ config: [] }),
  }));
  await page.route('/api/earthquakes**', routeHandler);
  await page.route('/api/earthquakes/stream', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'retry: 10000\n\n',
  }));
  await page.route('/api/elevation**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ elevation: 3.5, lat: 35.681236, lon: 139.767125 }),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));

  await page.goto('/');
  await page.waitForFunction(() => typeof window.toggleMagnitudeMode === 'function' && typeof window.map !== 'undefined');
  await page.evaluate(() => {
    currentLocation = { lat: 35.681236, lon: 139.767125, accuracyMeters: 5 };
  });
}

async function openMagnitude(page) {
  await page.locator('#mbc-tab-btn-earthquake').click();
  await expect(page.locator('#magnitude-list .mq-item').first()).toBeVisible({ timeout: 8000 });
}

async function listNames(page) {
  return page.locator('#magnitude-list .mq-name').evaluateAll(els => els.map(el => el.textContent));
}

test.describe('Magnitude Phase3-1: polling', () => {
  test('ON中だけ一定間隔で自動更新し、ステータスに最終更新と間隔を表示する', async ({ page }) => {
    let calls = 0;
    await setupPage(page, route => {
      calls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: baseItems(), count: baseItems().length }),
      });
    });

    await openMagnitude(page);
    await expect(page.locator('#magnitude-status-bar')).toContainText('秒ごとに自動更新');
    await expect.poll(() => calls).toBeGreaterThanOrEqual(2);
    await expect(page.locator('#magnitude-list .mq-item')).toHaveCount(2);
  });

  test('Magnitude OFF後はポーリングが停止し、ピンとリストを消す', async ({ page }) => {
    let calls = 0;
    await setupPage(page, route => {
      calls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: baseItems(), count: baseItems().length }),
      });
    });

    await openMagnitude(page);
    await expect.poll(() => calls).toBeGreaterThanOrEqual(2);
    await page.locator('#magnitude-btn').click();
    await expect(page.locator('#magnitude-list')).toBeEmpty();
    const callsAfterOff = calls;
    await page.waitForTimeout(POLL_MS * 2.5);
    expect(calls).toBe(callsAfterOff);
  });

  test('ON/OFF連続操作後もポーリングが多重化しない', async ({ page }) => {
    let calls = 0;
    await setupPage(page, route => {
      calls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: baseItems(), count: baseItems().length }),
      });
    });

    for (let i = 0; i < 5; i += 1) {
      await page.locator('#mbc-tab-btn-earthquake').click();
      await expect(page.locator('#magnitude-list .mq-item').first()).toBeVisible({ timeout: 8000 });
      await page.locator('#magnitude-btn').click();
      await page.waitForTimeout(50);
    }

    await page.locator('#mbc-tab-btn-earthquake').click();
    await expect(page.locator('#magnitude-list .mq-item').first()).toBeVisible({ timeout: 8000 });
    calls = 0;
    await page.waitForTimeout(POLL_MS * 2.4);
    expect(calls).toBeGreaterThanOrEqual(1);
    expect(calls).toBeLessThanOrEqual(3);
    await expect(page.locator('#mbc-tab-panel-earthquake')).toHaveCount(1);
    await expect(page.locator('#magnitude-list')).toHaveCount(1);
  });

  test('手動更新とポーリングが重なっても同時リクエストを増やし続けない', async ({ page }) => {
    let active = 0;
    let maxActive = 0;
    let calls = 0;
    await setupPage(page, async route => {
      calls += 1;
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise(resolve => setTimeout(resolve, 220));
      active -= 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: baseItems(), count: baseItems().length }),
      });
    });

    await openMagnitude(page);
    await page.waitForTimeout(POLL_MS - 40);
    await page.locator('#magnitude-refresh-btn').click({ force: true });
    await page.waitForTimeout(POLL_MS * 2);
    expect(calls).toBeGreaterThanOrEqual(2);
    expect(maxActive).toBe(1);
  });

  test('ポーリングで新着差分・震度フィルタ・近い順ソートが維持される', async ({ page }) => {
    let calls = 0;
    await setupPage(page, route => {
      calls += 1;
      const items = calls >= 2 ? withNewItems() : baseItems();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items, count: items.length }),
      });
    });

    await openMagnitude(page);
    await page.locator('.mq-filter-button', { hasText: '震度4以上' }).click();
    await page.locator('.mq-sort-button', { hasText: '近い順' }).click();
    await expect.poll(() => calls).toBeGreaterThanOrEqual(2);

    await expect.poll(() => listNames(page)).toEqual(['新着近距離4', '遠い震度4']);
    await expect(page.locator('.mq-new-badge')).toHaveCount(1);
    await expect(page.locator('#magnitude-new-count')).toHaveText('新着地震 1件');
    await expect(page.locator('.mq-filter-button', { hasText: '震度4以上' })).toHaveClass(/active/);
    await expect(page.locator('.mq-sort-button', { hasText: '近い順' })).toHaveClass(/active/);
  });

  test('API失敗後も表示を保ち、次回ポーリングで復帰する', async ({ page }) => {
    let calls = 0;
    await setupPage(page, route => {
      calls += 1;
      if (calls === 2) {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'busy' }) });
      }
      const items = calls >= 3 ? withNewItems() : baseItems();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items, count: items.length }),
      });
    });

    await openMagnitude(page);
    await expect.poll(() => calls).toBeGreaterThanOrEqual(2);
    await expect(page.locator('#magnitude-status-bar')).toContainText('更新に失敗');
    await expect(page.locator('#magnitude-list .mq-item')).toHaveCount(2);

    await expect.poll(() => calls).toBeGreaterThanOrEqual(3);
    await expect(page.locator('#magnitude-status-bar')).toContainText('最終更新');
    await expect(page.locator('#magnitude-list .mq-item')).toHaveCount(4);
  });

  test('hidden中は取得を抑制し、visible復帰時に更新する', async ({ page }) => {
    let calls = 0;
    await setupPage(page, route => {
      calls += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: calls >= 2 ? withNewItems() : baseItems(), count: 2 }),
      });
    });

    await openMagnitude(page);
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    const callsBeforeHiddenWait = calls;
    await page.waitForTimeout(POLL_MS * 1.5);
    expect(calls).toBe(callsBeforeHiddenWait);

    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await expect.poll(() => calls).toBeGreaterThan(callsBeforeHiddenWait);
  });
});
