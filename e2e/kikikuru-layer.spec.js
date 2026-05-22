'use strict';

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
  'base64',
);

const KIKIKURU_TIME = {
  basetime: '20260522111000',
  validtime: '20260522111000',
  member: 'immed0',
  elements: ['inund', 'land', 'flood', 'flood_mesh'],
};

async function mockAppTraffic(page) {
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{}',
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.route('**/jmatile/data/risk/**', route => {
    if (route.request().url().includes('targetTimes.json')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([KIKIKURU_TIME]),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: TRANSPARENT_PNG,
    });
  });
}

async function openInfoTab(page, viewport) {
  if (viewport) await page.setViewportSize(viewport);
  await mockAppTraffic(page);
  await page.goto('/');
  await page.evaluate(() => switchMbcTab('info'));
  await page.locator('#kkk-card-section .lip-accordion-header').click();
}

test.describe('Kikikuru display layer', () => {
  test('情報タブで浸水レイヤーを ON/OFF し凡例と取得状態を表示する', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);

    await expect(page.locator('#kkk-toggle-inund')).toBeVisible();
    await page.locator('#kkk-toggle-inund').click();
    await expect(page.locator('#kkk-toggle-inund')).toHaveClass(/kkk-toggle--active/);
    await expect(page.locator('#kikikuru-map-btn')).toHaveClass(/map-overlay-btn--active/);
    await page.evaluate(() => switchMbcTab('legend'));
    await expect(page.locator('#kkk-legend')).toBeVisible();
    await expect(page.locator('#kkk-legend')).toContainText('キキクル（現在の危険度）');
    await expect(page.locator('#kkk-status-badge')).toContainText('正常');
    await expect(page.locator('#kkk-status-text')).toContainText('時点');
    await expect.poll(() => page.evaluate(() => _kikikuruLayers.inund && _kikikuruLayers.inund._url))
      .toContain('/surf/inund/');

    await page.evaluate(() => switchMbcTab('info'));
    await page.locator('#kkk-toggle-inund').click();
    await expect(page.locator('#kkk-toggle-inund')).not.toHaveClass(/kkk-toggle--active/);
    await expect(page.locator('#kikikuru-map-btn')).not.toHaveClass(/map-overlay-btn--active/);
    await expect(page.locator('#kkk-legend')).toBeHidden();
    await expect.poll(() => page.evaluate(() => _kikikuruLayers.inund)).toBeNull();
    expect(errors).toEqual([]);
  });

  test('時刻取得失敗時も取得不可を表示して画面を保つ', async ({ page }) => {
    await page.route('/api/**', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{}',
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('**/jmatile/data/risk/targetTimes.json**', route => route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{}',
    }));

    await page.goto('/');
    await page.evaluate(() => switchMbcTab('info'));
    await page.locator('#kkk-card-section .lip-accordion-header').click();
    await page.locator('#kkk-toggle-inund').click();

    await expect(page.locator('#kkk-status-badge')).toContainText('取得不可');
    await expect(page.locator('#kkk-status-text')).toHaveText('取得不可');
    await expect(page.locator('#map')).toBeVisible();
    await expect.poll(() => page.evaluate(() => _kikikuruLayers.inund)).toBeNull();
  });

  test('洪水レイヤーを ON すると flood_mesh タイルが使われる', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    const tileUrls = [];
    page.on('request', req => {
      if (req.url().includes('jmatile/data/risk') && !req.url().includes('targetTimes')) {
        tileUrls.push(req.url());
      }
    });

    await openInfoTab(page);

    await page.locator('#kkk-toggle-flood').click();
    await expect(page.locator('#kkk-toggle-flood')).toHaveClass(/kkk-toggle--active/);

    await expect.poll(() => page.evaluate(() =>
      _kikikuruLayers.flood && _kikikuruLayers.flood._url
    )).toContain('/surf/flood_mesh/');

    await expect(page.locator('#kkk-kind-st-flood')).toContainText('●');

    // OFF
    await page.locator('#kkk-toggle-flood').click();
    await expect(page.locator('#kkk-toggle-flood')).not.toHaveClass(/kkk-toggle--active/);
    await expect.poll(() => page.evaluate(() => _kikikuruLayers.flood)).toBeNull();
    expect(errors).toEqual([]);
  });

  test('土砂レイヤーを ON すると land タイルが使われる', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);

    await page.locator('#kkk-toggle-land').click();
    await expect(page.locator('#kkk-toggle-land')).toHaveClass(/kkk-toggle--active/);

    await expect.poll(() => page.evaluate(() =>
      _kikikuruLayers.land && _kikikuruLayers.land._url
    )).toContain('/surf/land/');

    await expect(page.locator('#kkk-kind-st-land')).toContainText('●');

    // OFF
    await page.locator('#kkk-toggle-land').click();
    await expect(page.locator('#kkk-toggle-land')).not.toHaveClass(/kkk-toggle--active/);
    await expect.poll(() => page.evaluate(() => _kikikuruLayers.land)).toBeNull();
    expect(errors).toEqual([]);
  });

  test('3種同時 ON でも JS エラーが発生しない', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);

    await page.locator('#kkk-toggle-inund').click();
    await page.locator('#kkk-toggle-flood').click();
    await page.locator('#kkk-toggle-land').click();

    await expect(page.locator('#kkk-toggle-inund')).toHaveClass(/kkk-toggle--active/);
    await expect(page.locator('#kkk-toggle-flood')).toHaveClass(/kkk-toggle--active/);
    await expect(page.locator('#kkk-toggle-land')).toHaveClass(/kkk-toggle--active/);

    await expect.poll(() => page.evaluate(() =>
      _kikikuruLayers.inund && _kikikuruLayers.flood && _kikikuruLayers.land
    )).toBeTruthy();

    await page.evaluate(() => switchMbcTab('legend'));
    await expect(page.locator('#kkk-legend')).toBeVisible();
    await expect(page.locator('#kkk-legend-kinds')).toContainText('浸水');
    await expect(page.locator('#kkk-legend-kinds')).toContainText('洪水');
    await expect(page.locator('#kkk-legend-kinds')).toContainText('土砂');

    expect(errors).toEqual([]);
  });

  test('種別ごとのステータスインジケーターが正しく表示される', async ({ page }) => {
    await openInfoTab(page);

    // ON前はテキストなし（off状態）
    await expect(page.locator('#kkk-kind-st-inund')).toHaveText('');
    await expect(page.locator('#kkk-kind-st-flood')).toHaveText('');
    await expect(page.locator('#kkk-kind-st-land')).toHaveText('');

    // 浸水ON → ● 表示
    await page.locator('#kkk-toggle-inund').click();
    await expect(page.locator('#kkk-kind-st-inund')).toContainText('●');
    // 洪水/土砂はまだ off
    await expect(page.locator('#kkk-kind-st-flood')).toHaveText('');
    await expect(page.locator('#kkk-kind-st-land')).toHaveText('');

    // 洪水ON → ●
    await page.locator('#kkk-toggle-flood').click();
    await expect(page.locator('#kkk-kind-st-flood')).toContainText('●');

    // 土砂ON → ●
    await page.locator('#kkk-toggle-land').click();
    await expect(page.locator('#kkk-kind-st-land')).toContainText('●');

    // 浸水OFF → テキストなしに戻る
    await page.locator('#kkk-toggle-inund').click();
    await expect(page.locator('#kkk-kind-st-inund')).toHaveText('');
  });

  test('モバイル幅でキキクル UI が情報タブに収まる', async ({ page }) => {
    await openInfoTab(page, { width: 390, height: 844 });

    const layout = await page.evaluate(() => {
      const panel = document.getElementById('mbc-tab-panel-info');
      const card = document.getElementById('kkk-card-section');
      const row = card.querySelector('.kkk-toggle-row');
      const panelRect = panel.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      return {
        overflow: panel.scrollWidth - panel.clientWidth,
        rowFitsPanel: rowRect.left >= panelRect.left - 1 && rowRect.right <= panelRect.right + 1,
      };
    });

    expect(layout.overflow).toBeLessThanOrEqual(1);
    expect(layout.rowFitsPanel).toBe(true);
  });
});
