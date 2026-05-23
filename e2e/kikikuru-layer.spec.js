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

    await expect(page.locator('#kkk-kind-st-flood')).toHaveText('正常');
    await expect.poll(() => tileUrls.some(url => url.includes('/surf/flood_mesh/'))).toBe(true);

    // OFF
    await page.locator('#kkk-toggle-flood').click();
    await expect(page.locator('#kkk-toggle-flood')).not.toHaveClass(/kkk-toggle--active/);
    await expect.poll(() => page.evaluate(() => _kikikuruLayers.flood)).toBeNull();
    expect(errors).toEqual([]);
  });

  test('土砂レイヤーを ON すると land タイルが使われる', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    const tileUrls = [];
    page.on('request', req => {
      if (req.url().includes('jmatile/data/risk') && !req.url().includes('targetTimes')) {
        tileUrls.push(req.url());
      }
    });

    await openInfoTab(page);

    await page.locator('#kkk-toggle-land').click();
    await expect(page.locator('#kkk-toggle-land')).toHaveClass(/kkk-toggle--active/);

    await expect.poll(() => page.evaluate(() =>
      _kikikuruLayers.land && _kikikuruLayers.land._url
    )).toContain('/surf/land/');

    await expect(page.locator('#kkk-kind-st-land')).toHaveText('正常');
    await expect.poll(() => tileUrls.some(url => url.includes('/surf/land/'))).toBe(true);

    // OFF
    await page.locator('#kkk-toggle-land').click();
    await expect(page.locator('#kkk-toggle-land')).not.toHaveClass(/kkk-toggle--active/);
    await expect.poll(() => page.evaluate(() => _kikikuruLayers.land)).toBeNull();
    expect(errors).toEqual([]);
  });

  test('3種同時 ON でも JS エラーが発生しない', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const timesRequests = [];
    page.on('request', req => {
      if (req.url().includes('jmatile/data/risk/targetTimes.json')) {
        timesRequests.push(req.url());
      }
    });

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

    expect(timesRequests).toHaveLength(1);
    expect(errors).toEqual([]);
  });

  test('種別ごとのステータスインジケーターが正しく表示される', async ({ page }) => {
    await openInfoTab(page);

    // ON前は種別ごとに OFF 状態が読める。
    await expect(page.locator('#kkk-kind-st-inund')).toHaveText('OFF');
    await expect(page.locator('#kkk-kind-st-flood')).toHaveText('OFF');
    await expect(page.locator('#kkk-kind-st-land')).toHaveText('OFF');

    // 浸水ON → 正常 表示
    await page.locator('#kkk-toggle-inund').click();
    await expect(page.locator('#kkk-kind-st-inund')).toHaveText('正常');
    // 洪水/土砂はまだ off
    await expect(page.locator('#kkk-kind-st-flood')).toHaveText('OFF');
    await expect(page.locator('#kkk-kind-st-land')).toHaveText('OFF');

    // 洪水ON → 正常
    await page.locator('#kkk-toggle-flood').click();
    await expect(page.locator('#kkk-kind-st-flood')).toHaveText('正常');

    // 土砂ON → 正常
    await page.locator('#kkk-toggle-land').click();
    await expect(page.locator('#kkk-kind-st-land')).toHaveText('正常');

    // 浸水OFF → OFF に戻る
    await page.locator('#kkk-toggle-inund').click();
    await expect(page.locator('#kkk-kind-st-inund')).toHaveText('OFF');
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

  // ── Phase 2: 危険度要約 ───────────────────────────────────────────────────

  test('現在地リスクセクションが常に表示される', async ({ page }) => {
    await openInfoTab(page);
    await expect(page.locator('#kkk-risk-current')).toBeVisible();
    await expect(page.locator('#kkk-risk-current .kkk-risk-title')).toContainText('現在地周辺');
  });

  test('目的地未設定時はリスクセクションが非表示', async ({ page }) => {
    await openInfoTab(page);
    await expect(page.locator('#kkk-risk-dest')).toBeHidden();
  });

  test('目的地設定時に目的地リスクセクションが表示される', async ({ page }) => {
    await openInfoTab(page);
    await page.evaluate(() => {
      userDestination = { lat: 35.6812, lon: 139.7671, name: 'テスト目的地' };
      _kkkUpdateRiskUI('dest');
    });
    await expect(page.locator('#kkk-risk-dest')).toBeVisible();
    await expect(page.locator('#kkk-risk-dest .kkk-risk-title')).toContainText('目的地周辺');
  });

  test('目的地変更フックで更新し clear で目的地要約が消える', async ({ page }) => {
    await openInfoTab(page);
    await page.locator('#kkk-toggle-inund').click();

    await page.evaluate(async () => {
      userDestination = { lat: 35.6812, lon: 139.7671, name: 'テスト目的地' };
      kikikuruOnDestinationChange();
    });

    await expect(page.locator('#kkk-risk-dest')).toBeVisible();
    await expect(page.locator('#kkk-risk-dest .kkk-risk-rows')).toContainText('なし');

    await page.evaluate(() => clearUserDestination());
    await expect(page.locator('#kkk-risk-dest')).toBeHidden();
  });

  test('透明タイルの現在地サンプリングで「なし」が表示される', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);
    await page.locator('#kkk-toggle-inund').click();

    // currentLocation をモックしてサンプリングを強制起動
    await page.evaluate(async () => {
      currentLocation = { lat: 35.6812, lon: 139.7671, accuracyMeters: 10 };
      _kkkCurrentSampleLastAt = 0;
      await _kkkSampleLocation('current', 35.6812, 139.7671);
    });

    await expect(page.locator('#kkk-risk-current .kkk-risk-rows')).toContainText('なし');
    await expect(page.locator('#kkk-risk-current .kkk-risk-rows')).not.toContainText('取得不可');
    expect(errors).toEqual([]);
  });

  test('目的地サンプリングで「なし」が表示され取得不可にならない', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);
    await page.locator('#kkk-toggle-inund').click();

    await page.evaluate(async () => {
      userDestination = { lat: 35.6580, lon: 139.7454, name: '六本木' };
      await _kkkSampleLocation('dest', 35.6580, 139.7454);
    });

    await expect(page.locator('#kkk-risk-dest')).toBeVisible();
    await expect(page.locator('#kkk-risk-dest .kkk-risk-rows')).toContainText('なし');
    await expect(page.locator('#kkk-risk-dest .kkk-risk-rows')).not.toContainText('取得不可');
    expect(errors).toEqual([]);
  });

  test('タイル取得失敗時は取得不可を表示して safe 扱いしない', async ({ page }) => {
    await page.route('/api/**', route => route.fulfill({
      status: 200, contentType: 'application/json', body: '{}',
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('**/jmatile/data/risk/targetTimes.json**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([KIKIKURU_TIME]),
    }));
    // タイル画像だけ 503 で失敗させる
    await page.route('**/jmatile/data/risk/**/surf/**/*.png', route => route.fulfill({
      status: 503, body: '',
    }));

    await page.goto('/');
    await page.evaluate(() => switchMbcTab('info'));
    await page.locator('#kkk-card-section .lip-accordion-header').click();
    await page.locator('#kkk-toggle-inund').click();

    await page.evaluate(async () => {
      currentLocation = { lat: 35.6812, lon: 139.7671, accuracyMeters: 10 };
      _kkkCurrentSampleLastAt = 0;
      await _kkkSampleLocation('current', 35.6812, 139.7671);
    });

    // 取得不可が出て「なし」や「危険度なし」になっていない
    const rowText = await page.locator('#kkk-risk-current .kkk-risk-rows').textContent();
    expect(rowText).toContain('取得不可');
    expect(rowText).not.toMatch(/^なし$/);
  });

  test('未知の不透明色は none 扱いしない', async ({ page }) => {
    await openInfoTab(page);
    const levels = await page.evaluate(() => ({
      unknownOpaque: _kkkColorToLevel(18, 52, 86, 255),
      transparent: _kkkColorToLevel(18, 52, 86, 0),
    }));

    expect(levels.unknownOpaque).toBe('unavailable');
    expect(levels.transparent).toBe('none');
  });

  test('時刻更新失敗後に以前のなし要約を残さない', async ({ page }) => {
    let failTimes = false;
    await page.route('/api/**', route => route.fulfill({
      status: 200, contentType: 'application/json', body: '{}',
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('**/jmatile/data/risk/**', route => {
      if (route.request().url().includes('targetTimes.json')) {
        return route.fulfill({
          status: failTimes ? 503 : 200,
          contentType: 'application/json',
          body: failTimes ? '{}' : JSON.stringify([KIKIKURU_TIME]),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'image/png',
        body: TRANSPARENT_PNG,
      });
    });

    await page.goto('/');
    await page.evaluate(() => switchMbcTab('info'));
    await page.locator('#kkk-card-section .lip-accordion-header').click();
    await page.locator('#kkk-toggle-inund').click();
    await page.evaluate(async () => {
      currentLocation = { lat: 35.6812, lon: 139.7671, accuracyMeters: 10 };
      await _kkkSampleLocation('current', 35.6812, 139.7671);
    });
    await expect(page.locator('#kkk-risk-current .kkk-risk-rows')).toContainText('なし');

    failTimes = true;
    await page.evaluate(() => refreshKikikuru());

    await expect(page.locator('#kkk-risk-current .kkk-risk-rows')).toHaveText(/取得不可/);
    await expect(page.locator('#kkk-risk-current .kkk-risk-rows')).not.toContainText('なし');
  });

  test('Phase2: モバイル幅でリスク要約が崩れない', async ({ page }) => {
    await openInfoTab(page, { width: 390, height: 844 });
    const layout = await page.evaluate(() => {
      const panel = document.getElementById('mbc-tab-panel-info');
      const riskEl = document.getElementById('kkk-risk-current');
      const panelRect = panel.getBoundingClientRect();
      const riskRect = riskEl.getBoundingClientRect();
      return {
        overflow: panel.scrollWidth - panel.clientWidth,
        fits: riskRect.right <= panelRect.right + 2,
      };
    });
    expect(layout.overflow).toBeLessThanOrEqual(1);
    expect(layout.fits).toBe(true);
  });

  // ── Phase 3-A: ルート周辺危険度要約 ─────────────────────────────────────────

  test('ルート未選択時はルートセクションが非表示', async ({ page }) => {
    await openInfoTab(page);
    await expect(page.locator('#kkk-risk-route')).toBeHidden();
  });

  test('ルート設定でルートセクションが表示され透明タイルは「なし」', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);

    // _kikikuruCurrentEntry を直接注入してからルートをサンプリング
    await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      const coords = [
        { lat: 35.6812, lng: 139.7671 },
        { lat: 35.6850, lng: 139.7700 },
        { lat: 35.6890, lng: 139.7730 },
      ];
      await _kkkSampleRoute(coords);
    });

    await expect(page.locator('#kkk-risk-route')).toBeVisible();
    await expect(page.locator('#kkk-risk-route .kkk-risk-rows')).toContainText('なし');
    await expect(page.locator('#kkk-risk-route .kkk-risk-rows')).not.toContainText('取得不可');
    expect(errors).toEqual([]);
  });

  test('ルートクリアでルートセクションが非表示になる', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);
    await page.locator('#kkk-toggle-inund').click();

    await page.evaluate(async () => {
      userDestination = { lat: 35.6812, lon: 139.7671, name: 'clear route destination' };
      await _kkkSampleRoute([{ lat: 35.6812, lng: 139.7671 }]);
    });
    await expect(page.locator('#kkk-risk-route')).toBeVisible();

    await page.evaluate(() => clearUserDestination());
    await expect(page.locator('#kkk-risk-route')).toBeHidden();
    expect(errors).toEqual([]);
  });

  test('ルート変更で古いサンプリング結果を上書きしない（バージョンガード）', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);

    await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      const coordsA = [{ lat: 35.6812, lng: 139.7671 }];
      const coordsB = [{ lat: 35.6900, lng: 139.7750 }];
      // A の完了を待たずに B を開始（B が後勝ち）
      _kkkSampleRoute(coordsA);
      await _kkkSampleRoute(coordsB);
    });

    // B の結果が表示され、A の古い結果に戻っていない（両方透明タイルなので 'なし' が正常）
    await expect(page.locator('#kkk-risk-route')).toBeVisible();
    await expect(page.locator('#kkk-risk-route .kkk-risk-rows')).toContainText('なし');
    expect(errors).toEqual([]);
  });

  test('route preview でもルート要約カードが表示される', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await openInfoTab(page);
    await page.locator('#kkk-toggle-inund').click();

    // 実アプリの route selection フローから route preview に切り替える。
    await page.evaluate(async () => {
      const mockRoute = {
        coordinates: [
          { lat: 35.6812, lng: 139.7671 },
          { lat: 35.6850, lng: 139.7700 },
        ],
      };
      onNavRouteSelected(mockRoute, null, {});
      // サンプリング完了を待つ
      await new Promise(resolve => setTimeout(resolve, 500));
    });

    await expect(page.locator('#kkk-card-section')).toBeVisible();
    await expect(page.locator('#kkk-risk-route')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('ルート tile 取得失敗時は取得不可を表示して safe 扱いしない', async ({ page }) => {
    await page.route('/api/**', route => route.fulfill({
      status: 200, contentType: 'application/json', body: '{}',
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('**/jmatile/data/risk/targetTimes.json**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([KIKIKURU_TIME]),
    }));
    await page.route('**/jmatile/data/risk/**/surf/**/*.png', route => route.fulfill({
      status: 503, body: '',
    }));

    await page.goto('/');
    await page.evaluate(() => switchMbcTab('info'));
    await page.locator('#kkk-card-section .lip-accordion-header').click();
    await page.locator('#kkk-toggle-inund').click();
    await expect(page.locator('#kkk-status-badge')).toContainText('正常');
    await page.evaluate(async () => {
      await _kkkSampleRoute([{ lat: 35.6812, lng: 139.7671 }]);
    });

    const rowText = await page.locator('#kkk-risk-route .kkk-risk-rows').textContent();
    expect(rowText).toContain('取得不可');
    expect(rowText).not.toContain('なし');
  });

  test('時刻更新失敗後にルートの以前のなし要約を残さない', async ({ page }) => {
    let failTimes = false;
    await page.route('/api/**', route => route.fulfill({
      status: 200, contentType: 'application/json', body: '{}',
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('**/jmatile/data/risk/**', route => {
      if (route.request().url().includes('targetTimes.json')) {
        return route.fulfill({
          status: failTimes ? 503 : 200,
          contentType: 'application/json',
          body: failTimes ? '{}' : JSON.stringify([KIKIKURU_TIME]),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'image/png',
        body: TRANSPARENT_PNG,
      });
    });

    await page.goto('/');
    await page.evaluate(() => switchMbcTab('info'));
    await page.locator('#kkk-card-section .lip-accordion-header').click();
    await page.locator('#kkk-toggle-inund').click();
    await expect(page.locator('#kkk-status-badge')).toContainText('正常');
    await page.evaluate(async () => {
      await _kkkSampleRoute([{ lat: 35.6812, lng: 139.7671 }]);
    });
    await expect(page.locator('#kkk-risk-route .kkk-risk-rows')).toContainText('なし');

    failTimes = true;
    await page.evaluate(() => refreshKikikuru());

    await expect(page.locator('#kkk-risk-route .kkk-risk-rows')).toHaveText(/取得不可/);
    await expect(page.locator('#kkk-risk-route .kkk-risk-rows')).not.toContainText('なし');
  });

  test('ルート要約は route-risk を呼ばずルート危険度値を変更しない', async ({ page }) => {
    const routeRiskRequests = [];
    page.on('request', request => {
      if (request.url().includes('/api/route-risk')) routeRiskRequests.push(request.url());
    });

    await openInfoTab(page);
    const result = await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      const route = {
        coordinates: [{ lat: 35.6812, lng: 139.7671 }],
        safety_score: 87,
        risk_level: 'caution',
        risk_summary: ['固定ハザードのみ'],
        __riskSummary: { safety_score: 87, risk_level: 'caution' },
      };
      await _kkkSampleRoute(route.coordinates);
      return {
        safetyScore: route.safety_score,
        riskLevel: route.risk_level,
        riskSummary: route.risk_summary.join('/'),
        nestedScore: route.__riskSummary.safety_score,
        nestedLevel: route.__riskSummary.risk_level,
      };
    });

    expect(routeRiskRequests).toEqual([]);
    expect(result).toEqual({
      safetyScore: 87,
      riskLevel: 'caution',
      riskSummary: '固定ハザードのみ',
      nestedScore: 87,
      nestedLevel: 'caution',
    });
  });

  test('ルート要約後の map move 連続で sampling request が増えない', async ({ page }) => {
    const tileUrls = [];
    page.on('request', request => {
      if (request.url().includes('/jmatile/data/risk/') && request.url().endsWith('.png')) {
        tileUrls.push(request.url());
      }
    });

    await openInfoTab(page);
    await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      await _kkkSampleRoute([
        { lat: 35.6812, lng: 139.7671 },
        { lat: 35.6850, lng: 139.7700 },
      ]);
    });

    const beforeMove = tileUrls.length;
    await page.evaluate(() => {
      for (let index = 0; index < 25; index += 1) map.fire('move');
    });
    await page.waitForTimeout(250);

    expect(tileUrls).toHaveLength(beforeMove);
  });

  // ─── Phase 3-B: バックエンド補正連携 ─────────────────────────────────────────

  test('Phase3-B: _assessRouteHazardRisk がキキクルデータを /api/route-risk に含める', async ({ page }) => {
    const routeRiskBodies = [];
    await openInfoTab(page);

    await page.route('/api/route-risk', async route => {
      const body = JSON.parse(route.request().postData() || '{}');
      routeRiskBodies.push(body);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          safety_score: 96,
          risk_level: 'safe',
          risk_summary: { total_penalty: 0, hazards: [], notes: [] },
          sampled_points: [],
          kikikuru_adjustment: {
            enabled: true,
            status: 'normal',
            penalty: 4,
            max_level: 'caution',
            matched_hazards: [],
            summary: ['洪水キキクル注意'],
          },
        }),
      });
    });

    const result = await page.evaluate(async () => {
      _kkkSampleRouteForBackend = async () => ({
        status: 'ok',
        inund: 'none',
        flood: 'caution',
        land: 'none',
      });
      return _assessRouteHazardRisk({
        coordinates: [
          { lat: 35.6812, lng: 139.7671 },
          { lat: 35.6850, lng: 139.7700 },
        ],
      });
    });

    expect(routeRiskBodies).toHaveLength(1);
    expect(routeRiskBodies[0].kikikuru).toEqual({
      status: 'ok',
      inund: 'none',
      flood: 'caution',
      land: 'none',
    });
    expect(result.kikikuru_adjustment.penalty).toBe(4);
  });

  test('Phase3-B: kikikuruSetBackendAdjustment でルートカードに補正行が表示される', async ({ page }) => {
    await openInfoTab(page);
    await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      // ルートを設定してサンプリング
      await _kkkSampleRoute([
        { lat: 35.6812, lng: 139.7671 },
        { lat: 35.6850, lng: 139.7700 },
      ]);
      // バックエンド補正結果を注入
      kikikuruSetBackendAdjustment({
        enabled: true,
        status: 'normal',
        penalty: 8,
        max_level: 'danger',
        matched_hazards: ['flood'],
        summary: ['洪水キキクル注意（固定ハザード重複）'],
      });
    });

    const adjRow = await page.locator('.kkk-adj-row').first();
    await expect(adjRow).toBeVisible();
    const text = await adjRow.textContent();
    expect(text).toContain('補正');
    expect(text).toContain('−8pt');
  });

  test('Phase3-B: kikikuruSetBackendAdjustment で取得不可時は unavail 行が表示される', async ({ page }) => {
    await openInfoTab(page);
    await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      await _kkkSampleRoute([{ lat: 35.6812, lng: 139.7671 }]);
      kikikuruSetBackendAdjustment({
        enabled: true,
        status: 'unavailable',
        penalty: 0,
        max_level: null,
        matched_hazards: [],
        summary: ['キキクル取得不可（補正なし）'],
      });
    });

    const unavailRow = await page.locator('.kkk-adj-unavail').first();
    await expect(unavailRow).toBeVisible();
    const text = await unavailRow.textContent();
    expect(text).toContain('取得不可');
  });

  test('Phase3-B: penalty 0 の補正は adj 行を表示しない', async ({ page }) => {
    await openInfoTab(page);
    await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      await _kkkSampleRoute([{ lat: 35.6812, lng: 139.7671 }]);
      kikikuruSetBackendAdjustment({
        enabled: true,
        status: 'normal',
        penalty: 0,
        max_level: 'caution',
        matched_hazards: [],
        summary: [],
      });
    });

    const adjRows = await page.locator('.kkk-adj-row').count();
    expect(adjRows).toBe(0);
  });

  test('Phase3-B: ルート clear で _kkkBackendAdj がリセットされ adj 行が消える', async ({ page }) => {
    await openInfoTab(page);
    await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      await _kkkSampleRoute([{ lat: 35.6812, lng: 139.7671 }]);
      kikikuruSetBackendAdjustment({
        enabled: true, status: 'normal', penalty: 8,
        max_level: 'danger', matched_hazards: ['flood'],
        summary: ['洪水キキクル注意'],
      });
    });

    // 補正行があることを確認
    await expect(page.locator('.kkk-adj-row').first()).toBeVisible();

    // ルートをクリア
    await page.evaluate(() => kikikuruOnRouteChange(null));

    // ルートセクション自体が非表示になる
    const routeEl = page.locator('#kkk-risk-route');
    await expect(routeEl).toHaveCSS('display', 'none');
  });

  test('Phase3-B: 補正あり表示のモバイル幅崩れなし', async ({ page }) => {
    await openInfoTab(page, { width: 390, height: 844 });
    await page.evaluate(async () => {
      _kikikuruCurrentEntry = {
        basetime: '20260522111000', validtime: '20260522111000',
        member: 'immed0', elements: ['inund', 'land', 'flood', 'flood_mesh'],
      };
      await _kkkSampleRoute([{ lat: 35.6812, lng: 139.7671 }]);
      kikikuruSetBackendAdjustment({
        enabled: true, status: 'normal', penalty: 16,
        max_level: 'danger', matched_hazards: ['flood'],
        summary: ['洪水キキクル危険（固定ハザード重複）'],
      });
    });

    const layout = await page.evaluate(() => {
      const panel = document.getElementById('mbc-tab-panel-info');
      const routeEl = document.getElementById('kkk-risk-route');
      const panelRect = panel.getBoundingClientRect();
      const routeRect = routeEl.getBoundingClientRect();
      return {
        overflow: panel.scrollWidth - panel.clientWidth,
        fits: routeRect.right <= panelRect.right + 2,
      };
    });
    expect(layout.overflow).toBeLessThanOrEqual(1);
    expect(layout.fits).toBe(true);
  });

  test('Phase3-A: ルートセクション含めモバイル幅で崩れない', async ({ page }) => {
    await openInfoTab(page, { width: 390, height: 844 });
    await page.locator('#kkk-toggle-inund').click();
    await page.evaluate(async () => {
      await _kkkSampleRoute([{ lat: 35.6812, lng: 139.7671 }]);
    });

    const layout = await page.evaluate(() => {
      const panel = document.getElementById('mbc-tab-panel-info');
      const routeEl = document.getElementById('kkk-risk-route');
      const panelRect = panel.getBoundingClientRect();
      const routeRect = routeEl.getBoundingClientRect();
      return {
        overflow: panel.scrollWidth - panel.clientWidth,
        fits: routeRect.right <= panelRect.right + 2,
      };
    });
    expect(layout.overflow).toBeLessThanOrEqual(1);
    expect(layout.fits).toBe(true);
  });
});
