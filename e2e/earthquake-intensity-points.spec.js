'use strict';

const { test, expect } = require('@playwright/test');

const pointsEvent = {
  event_id: 'test-quake-001',
  occurred_at: '2026-04-29T10:30:00+09:00',
  epicenter_name: '東京湾',
  lat: 35.55,
  lng: 139.78,
  max_intensity: '3',
  magnitude: 4.2,
  points: [
    { pref: '東京都', addr: '大田区', isArea: false, scale: 30 },
    { pref: '東京都', addr: '品川区', isArea: false, scale: 30 },
    { pref: '神奈川県', addr: '横浜市中区', isArea: false, scale: 20 },
  ],
};

const mixedAreaEvent = {
  event_id: 'test-quake-002',
  occurred_at: '2026-04-29T10:40:00+09:00',
  epicenter_name: '東京23区',
  lat: 35.68,
  lng: 139.76,
  max_intensity: '3',
  magnitude: 3.8,
  points: [
    { pref: '東京都', addr: '東京23区', isArea: true, scale: 30 },
    { pref: '東京都', addr: '大田区', isArea: false, scale: 30 },
    { pref: '東京都', addr: '品川区', isArea: false, scale: 30 },
  ],
};

const unmappedEvent = {
  event_id: 'test-quake-003',
  occurred_at: '2026-04-29T10:50:00+09:00',
  epicenter_name: '未登録地点テスト',
  lat: 35.68,
  lng: 139.76,
  max_intensity: '2',
  magnitude: 3.1,
  points: [
    { pref: '東京都', addr: '大田区', isArea: false, scale: 30 },
    { pref: '東京都', addr: '未登録地点', isArea: false, scale: 20 },
  ],
};

const fallbackAreaEvent = {
  event_id: 'test-quake-004',
  occurred_at: '2026-04-29T11:00:00+09:00',
  epicenter_name: '相模湾',
  lat: 35.25,
  lng: 139.35,
  max_intensity: '3',
  magnitude: 4.0,
  areas: [
    { name: '東京都', scale: 30 },
    { name: '神奈川県東部', scale: 20 },
  ],
};

async function setupMocks(page, items) {
  await page.route('/favicon.ico', route => route.fulfill({ status: 204, body: '' }));
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: route.request().url().includes('/stream') ? 'text/event-stream' : 'application/json',
    body: route.request().url().includes('/stream') ? 'retry: 10000\n\n' : JSON.stringify({}),
  }));
  await page.route('/api/earthquakes**', route => route.fulfill({
    status: 200,
    contentType: route.request().url().includes('/stream') ? 'text/event-stream' : 'application/json',
    body: route.request().url().includes('/stream') ? 'retry: 10000\n\n' : JSON.stringify({ count: items.length, items }),
  }));
  await page.route('/api/admin/config**', route => route.fulfill({
    status: 200,
    contentType: route.request().url().includes('/stream') ? 'text/event-stream' : 'application/json',
    body: route.request().url().includes('/stream') ? 'retry: 10000\n\n' : JSON.stringify({ config: [] }),
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
}

async function openEarthquakeTab(page) {
  await page.goto('/');
  await page.waitForFunction(() => typeof window.toggleMagnitudeMode === 'function' && typeof window.map !== 'undefined');
  await page.evaluate(() => {
    currentLocation = { lat: 35.681236, lon: 139.767125, accuracyMeters: 5 };
  });
  await page.locator('#mbc-tab-btn-earthquake').click();
  await expect(page.locator('#magnitude-list .mq-item').first()).toBeVisible({ timeout: 8000 });
}

test.describe('earthquake intensity point mapping', () => {
  test('converts point intensity, suppresses area duplicates, renders markers, popup, and clears on switch/off', async ({ page }) => {
    const errors = [];
    page.on('pageerror', err => errors.push(err.message));
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await setupMocks(page, [pointsEvent, mixedAreaEvent, unmappedEvent]);
    await openEarthquakeTab(page);

    await expect(page.locator('#magnitude-list .mq-item', { hasText: '東京湾' }).locator('.mq-intensity-summary')).toContainText('震度3（2） / 震度2（1）');
    await page.locator('#magnitude-list .mq-item', { hasText: '東京湾' }).locator('.mq-detail-toggle-btn').click();
    await expect(page.locator('#magnitude-list .mq-item', { hasText: '東京湾' }).locator('.mq-detail-item')).toHaveCount(3);
    await expect(page.locator('#magnitude-list .mq-item', { hasText: '東京湾' }).locator('.mq-intensity-map-status')).toContainText('観測点: 3件 / 地図表示: 3件 / 座標未登録: 0件');
    await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(3);

    await page.evaluate(() => {
      const marker = Object.values(map._layers).find(layer =>
        layer?.options?.icon?.options?.html?.includes('earthquake-intensity-marker')
      );
      marker.openPopup();
    });
    await expect(page.locator('.leaflet-popup-content')).toContainText(/東京都|神奈川県/);
    await expect(page.locator('.leaflet-popup-content')).toContainText(/震度:/);
    await expect(page.locator('.leaflet-popup-content')).toContainText('発表時刻:');

    await page.locator('#magnitude-list .mq-item', { hasText: '東京23区' }).locator('.mq-detail-toggle-btn').click();
    const mixedItem = page.locator('#magnitude-list .mq-item', { hasText: '東京23区' });
    await expect(mixedItem.locator('.mq-detail-item')).toHaveText(['東京都 大田区', '東京都 品川区']);
    await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(2);

    await page.locator('#magnitude-list .mq-item', { hasText: '未登録地点テスト' }).locator('.mq-detail-toggle-btn').click();
    const unmappedItem = page.locator('#magnitude-list .mq-item', { hasText: '未登録地点テスト' });
    await expect(unmappedItem.locator('.mq-detail-item')).toHaveText(['東京都 大田区', '東京都 未登録地点']);
    await expect(unmappedItem.locator('.mq-intensity-map-status')).toContainText('観測点: 2件 / 地図表示: 1件 / 座標未登録: 1件');
    await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(1);

    await page.evaluate(() => toggleMagnitudeMode());
    await expect(page.locator('.earthquake-intensity-marker')).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test('falls back to area summary when points are absent', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setupMocks(page, [fallbackAreaEvent]);
    await openEarthquakeTab(page);

    const item = page.locator('#magnitude-list .mq-item', { hasText: '相模湾' });
    await expect(item.locator('.mq-intensity-summary')).toContainText('震度3（1） / 震度2（1）');
    await item.locator('.mq-detail-toggle-btn').click();
    await expect(item.locator('.mq-detail-item')).toHaveText(['東京都', '神奈川県東部']);
    await expect(item.locator('.mq-detail-list')).toBeVisible();
  });
});
