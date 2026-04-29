'use strict';

const { test, expect } = require('@playwright/test');

function earthquakeItems(count = 36) {
  const base = [
    ['eq-near-5w', '近い震度5弱', 35.682, 139.768, '5弱', 5.1],
    ['eq-mid-4', '中距離震度4', 35.9, 139.9, '4', 4.1],
    ['eq-far-3', '遠い震度3', 40.0, 141.0, '3', 3.1],
    ['eq-low-1', '対象外震度1', 35.7, 139.8, '1', 2.1],
  ].map(([event_id, epicenter_name, lat, lng, max_intensity, magnitude], index) => ({
    event_id,
    occurred_at: `2026-04-29T10:${String(50 - index).padStart(2, '0')}:00+09:00`,
    epicenter_name,
    lat,
    lng,
    max_intensity,
    magnitude,
    source: 'mock',
  }));

  const extra = Array.from({ length: Math.max(0, count - base.length) }, (_, index) => ({
    event_id: `eq-extra-${index}`,
    occurred_at: `2026-04-29T09:${String(59 - index).padStart(2, '0')}:00+09:00`,
    epicenter_name: `スクロール確認 ${index + 1}`,
    lat: 35.1 + index * 0.01,
    lng: 139.1 + index * 0.01,
    max_intensity: String((index % 4) + 1),
    magnitude: 2.5 + (index % 3),
    source: 'mock',
  }));

  return [...base, ...extra];
}

async function setupMocks(page) {
  const items = earthquakeItems();
  await page.route('/favicon.ico', route => route.fulfill({ status: 204, body: '' }));
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('/api/earthquakes**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ count: items.length, items }),
  }));
  await page.route('/api/admin/config**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ config: [] }),
  }));
  await page.route('/api/admin/config/stream', route => route.fulfill({
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
}

async function openEarthquakeTab(page) {
  await page.goto('/');
  await page.waitForFunction(() => typeof window.toggleMagnitudeMode === 'function' && typeof window.map !== 'undefined');
  await page.evaluate(() => {
    currentLocation = { lat: 35.681236, lon: 139.767125, accuracyMeters: 5 };
  });
  await page.locator('#mbc-tab-btn-earthquake').click();
  await expect(page.locator('#mbc-tab-panel-earthquake')).toBeVisible();
  await expect(page.locator('#magnitude-list .mq-item').first()).toBeVisible({ timeout: 8000 });
}

async function visibleNames(page) {
  return page.locator('#magnitude-list .mq-name').evaluateAll(els => els.map(el => el.textContent));
}

test.describe('Magnitude UI redesign: earthquake bottom tab', () => {
  test('地震タブが表示され、地図を見せたままリストを開ける', async ({ page }) => {
    const errors = [];
    page.on('pageerror', err => errors.push(err.message));
    page.on('console', msg => {
      if (msg.type() !== 'error') return;
      const text = msg.text();
      if (text.includes('Failed to load resource')) return;
      errors.push(text);
    });
    await setupMocks(page);
    await openEarthquakeTab(page);

    await expect(page.locator('#mbc-tab-btn-earthquake')).toContainText('地震');
    await expect(page.locator('#map')).toBeVisible();
    await expect(page.locator('#mbc-tab-btn-earthquake')).toHaveClass(/mbc-tab-btn--active/);
    await expect(page.locator('#map-bottom-controls')).toHaveClass(/mbc-earthquake-active/);
    await expect(page.locator('#magnitude-panel')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('地震リストのスクロールは内部で完結し、地図中心を動かさない', async ({ page }) => {
    await setupMocks(page);
    await openEarthquakeTab(page);
    await page.waitForTimeout(500);

    const before = await page.evaluate(() => {
      const center = map.getCenter();
      return { lat: center.lat, lng: center.lng };
    });

    const list = page.locator('#magnitude-list');
    await page.locator('#magnitude-list .mq-item').last().scrollIntoViewIfNeeded();

    await expect.poll(() => list.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    const after = await page.evaluate(() => {
      const center = map.getCenter();
      return { lat: center.lat, lng: center.lng };
    });
    expect(Math.abs(after.lat - before.lat)).toBeLessThan(0.00001);
    expect(Math.abs(after.lng - before.lng)).toBeLessThan(0.00001);
  });

  test('スマホ幅でも地図が見え、地震パネルが画面全体を覆わない', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setupMocks(page);
    await openEarthquakeTab(page);

    const mapBox = await page.locator('#map').boundingBox();
    const controlsBox = await page.locator('#map-bottom-controls').boundingBox();
    expect(mapBox.width).toBeGreaterThan(300);
    expect(mapBox.height).toBeGreaterThan(600);
    expect(controlsBox.height).toBeLessThan(844 * 0.6);
    expect(controlsBox.y).toBeGreaterThan(844 * 0.35);
  });

  test('リストクリックで該当ピンへ移動し、選択状態は1件だけになる', async ({ page }) => {
    await setupMocks(page);
    await openEarthquakeTab(page);

    await page.locator('#magnitude-list .mq-item', { hasText: '近い震度5弱' }).click();

    await expect(page.locator('#magnitude-list .mq-item--selected')).toHaveCount(1);
    await expect(page.locator('#magnitude-list .mq-item--selected .mq-name')).toHaveText('近い震度5弱');
    await expect.poll(() => page.evaluate(() => {
      const center = map.getCenter();
      return {
        lat: center.lat,
        lng: center.lng,
        popupOpen: !!map._popup,
      };
    })).toMatchObject({
      lat: expect.closeTo(35.682, 0.01),
      lng: expect.closeTo(139.768, 0.01),
      popupOpen: true,
    });
  });

  test('ソート・震度フィルタ・NEWバッジがタブUI内で動作する', async ({ page }) => {
    await setupMocks(page);
    await openEarthquakeTab(page);

    await page.evaluate(() => {
      renderEarthquakeList([
        {
          event_id: 'eq-new-near-5w',
          occurred_at: '2026-04-29T10:59:00+09:00',
          epicenter_name: '新着近距離5弱',
          lat: 35.6815,
          lng: 139.7675,
          max_intensity: '5弱',
          magnitude: 5.2,
        },
        {
          event_id: 'eq-old-far-4',
          occurred_at: '2026-04-29T09:00:00+09:00',
          epicenter_name: '古い遠距離4',
          lat: 40.0,
          lng: 141.0,
          max_intensity: '4',
          magnitude: 4.2,
        },
        {
          event_id: 'eq-new-low',
          occurred_at: '2026-04-29T11:00:00+09:00',
          epicenter_name: '対象外震度1',
          lat: 35.682,
          lng: 139.768,
          max_intensity: '1',
          magnitude: 2.0,
        },
      ], { lat: 35.681236, lon: 139.767125 }, new Set(['eq-new-near-5w']));
    });

    await page.locator('.mq-filter-button', { hasText: '震度4以上' }).click();
    await expect.poll(() => visibleNames(page)).toEqual(['新着近距離5弱', '古い遠距離4']);
    await expect(page.locator('.mq-new-badge')).toHaveCount(1);

    await page.locator('.mq-sort-button', { hasText: '近い順' }).click();
    await expect.poll(() => visibleNames(page)).toEqual(['新着近距離5弱', '古い遠距離4']);
    await expect(page.locator('.mq-dist')).toHaveCount(2);
  });

  test('タブ切替を繰り返してもDOMやイベント状態が増殖しない', async ({ page }) => {
    await setupMocks(page);
    await openEarthquakeTab(page);

    for (let i = 0; i < 10; i += 1) {
      await page.locator('#mbc-tab-btn-action').click();
      await page.locator('#mbc-tab-btn-earthquake').click();
    }

    await expect(page.locator('#mbc-tab-panel-earthquake')).toHaveCount(1);
    await expect(page.locator('#magnitude-list')).toHaveCount(1);
    await expect(page.locator('#magnitude-filter-bar')).toHaveCount(1);
    await expect(page.locator('#magnitude-sort-bar')).toHaveCount(1);

    await page.locator('#magnitude-list .mq-item').nth(0).click();
    await page.locator('#magnitude-list .mq-item').nth(1).click();
    await expect(page.locator('#magnitude-list .mq-item--selected')).toHaveCount(1);
  });
});
