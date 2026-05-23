'use strict';

const { test, expect } = require('@playwright/test');

async function mockSimTraffic(page, observedRequests = [], routeRiskBodies = []) {
  page.on('request', request => observedRequests.push(request.url()));
  // 単一ハンドラ: /api/route-risk を先に判定し、他は {} を返す
  await page.route('/api/**', async route => {
    const url = route.request().url();
    if (url.includes('/api/route-risk')) {
      const body = JSON.parse(route.request().postData() || '{}');
      routeRiskBodies.push(body);
      const kkk  = body.kikikuru;
      let adj = { enabled: false, status: 'off', penalty: 0, max_level: null, matched_hazards: [], summary: [] };
      if (kkk) {
        if (kkk.status === 'unavailable') {
          adj = { enabled: true, status: 'unavailable', penalty: 0, max_level: null, matched_hazards: [], summary: [] };
        } else if (kkk.status === 'unknown') {
          adj = { enabled: true, status: 'unknown', penalty: 0, max_level: null, matched_hazards: [], summary: [] };
        } else if (kkk.status === 'ok') {
          const hasLevel = v => v === 'caution' || v === 'danger';
          const penalty  = (hasLevel(kkk.flood) ? (kkk.flood === 'danger' ? 8 : 4) : 0)
                         + (hasLevel(kkk.inund) ? (kkk.inund === 'danger' ? 6 : 3) : 0)
                         + (hasLevel(kkk.land)  ? (kkk.land  === 'danger' ? 8 : 4) : 0);
          const maxLevel = [kkk.inund, kkk.flood, kkk.land].includes('danger') ? 'danger' : 'caution';
          const matchedHazards = kkk.flood === 'danger' ? ['flood'] : [];
          adj = { enabled: true, status: 'ok', penalty, max_level: maxLevel, matched_hazards: matchedHazards, summary: [] };
        }
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ safety_score: 84.0, risk_level: 'caution', kikikuru_adjustment: adj }),
      });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
}

test.describe('Simulation Mode — キキクル検証パネル (Phase 3-D)', () => {

  test('キキクル検証パネルが左ペインに表示される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await expect(page.locator('#kkk-scenario-buttons')).toBeVisible();
    await expect(page.locator('.kkk-scenario-btn').first()).toBeVisible();
  });

  test('シナリオボタンが11件以上ある', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    const count = await page.locator('.kkk-scenario-btn').count();
    expect(count).toBeGreaterThanOrEqual(11);
  });

  test('疑似オーバーレイ凡例で3種と注意・危険の表現を確認できる', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await expect(page.locator('#kkk-sim-legend')).toContainText('浸水キキクル');
    await expect(page.locator('#kkk-sim-legend')).toContainText('洪水キキクル');
    await expect(page.locator('#kkk-sim-legend')).toContainText('土砂キキクル');
    await expect(page.locator('#kkk-sim-legend')).toContainText('注意: 薄色 / 危険: 濃色');
  });

  test('「洪水 危険」シナリオで補正セクションが表示される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    await expect(page.locator('#kkk-adj-section')).toBeVisible();
    const text = await page.locator('#kkk-adj-display').textContent();
    expect(text).toContain('洪水 危険');
  });

  test('「洪水 危険」でキキクル種別テーブルに洪水=危険が表示される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    const text = await page.locator('#kkk-adj-display').textContent();
    expect(text).toContain('洪水キキクル');
    expect(text).toContain('危険');
  });

  test('「取得不可」シナリオで取得不可が表示される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="unavailable"]').click();
    await expect(page.locator('#kkk-adj-section')).toBeVisible();
    const text = await page.locator('#kkk-adj-display').textContent();
    expect(text).toContain('取得不可');
  });

  test('「取得不可」を safe 扱いしない', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="unavailable"]').click();
    const text = await page.locator('#kkk-adj-display').textContent();
    expect(text).toContain('取得不可');
    expect(text).not.toContain('安全寄り'); // STATUS_DISPLAY_NAMES['safe'] — これが出たら safe 扱い
    // 説明文として「安全を意味しません」が含まれることを確認
    expect(text).toContain('安全を意味しません');
  });

  test('「判定不可」シナリオで判定不可が表示される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="unknown"]').click();
    const text = await page.locator('#kkk-adj-display').textContent();
    expect(text).toContain('判定不可');
    expect(text).not.toContain('安全寄り'); // STATUS_DISPLAY_NAMES['safe'] — これが出たら safe 扱い
    expect(text).toContain('安全を意味しません');
  });

  test('「3種同時 危険」で3種すべてが表示される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="three_danger"]').click();
    const text = await page.locator('#kkk-adj-display').textContent();
    expect(text).toContain('浸水キキクル');
    expect(text).toContain('洪水キキクル');
    expect(text).toContain('土砂キキクル');
  });

  test('「3種同時 危険」で3種の疑似オーバーレイを描画しクリアできる', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="three_danger"]').click();
    await expect.poll(() => page.evaluate(() => SimMap.getKikikuruOverlayCount())).toBe(3);
    await page.locator('#kkk-clear-btn').click();
    await expect.poll(() => page.evaluate(() => SimMap.getKikikuruOverlayCount())).toBe(0);
  });

  test('選択シナリオが現在地・目的地・ルート周辺サマリーに反映される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    for (const id of ['#kkk-summary-current', '#kkk-summary-destination', '#kkk-summary-route']) {
      await expect(page.locator(id)).toContainText('洪水 危険');
    }
  });

  test('取得不可・判定不可の周辺サマリーを安全扱いしない', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="unavailable"]').click();
    await expect(page.locator('#kkk-summary-route')).toContainText('取得不可（安全を意味しません）');
    await page.locator('.kkk-scenario-btn[data-key="unknown"]').click();
    await expect(page.locator('#kkk-summary-route')).toContainText('判定不可（安全を意味しません）');
  });

  test('シナリオ選択でボタンに active クラスが付く', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="land_caution"]').click();
    await expect(page.locator('.kkk-scenario-btn[data-key="land_caution"]')).toHaveClass(/active/);
    await expect(page.locator('.kkk-scenario-btn[data-key="flood_danger"]')).not.toHaveClass(/active/);
  });

  test('クリアボタンで補正セクションが非表示になる', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    await expect(page.locator('#kkk-adj-section')).toBeVisible();
    await page.locator('#kkk-clear-btn').click();
    await expect(page.locator('#kkk-adj-section')).toBeHidden();
    await expect(page.locator('#kkk-adj-preview')).toBeEmpty();
  });

  test('URL param ?kikikuruScenario=flood_danger でシナリオが自動選択される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html?kikikuruScenario=flood_danger');
    await expect(page.locator('.kkk-scenario-btn[data-key="flood_danger"]')).toHaveClass(/active/);
    await expect(page.locator('#kkk-adj-section')).toBeVisible();
  });

  test('URL param ハイフン区切りも正規化される', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html?kikikuruScenario=flood-danger');
    await expect(page.locator('.kkk-scenario-btn[data-key="flood_danger"]')).toHaveClass(/active/);
  });

  test('window.setKikikuruSimulationScenario でシナリオ注入できる', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.evaluate(() => {
      window.setKikikuruSimulationScenario({ enabled: true, scenario: 'three_danger' });
    });
    await expect(page.locator('#kkk-adj-section')).toBeVisible();
    const text = await page.locator('#kkk-adj-display').textContent();
    expect(text).toContain('3種同時 危険');
  });

  test('setKikikuruSimulationScenario({ enabled: false }) でパネルが非表示', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    await expect(page.locator('#kkk-adj-section')).toBeVisible();
    await page.evaluate(() => {
      window.setKikikuruSimulationScenario({ enabled: false });
    });
    await expect(page.locator('#kkk-adj-section')).toBeHidden();
  });

  test('route-risk 補正プレビューが表示される（penalty > 0 シナリオ）', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    await expect(page.locator('#kkk-adj-preview .kkk-adj-preview--active')).toBeVisible({ timeout: 5000 });
  });

  test('固定ハザード重複シナリオでリアルタイム補正理由を表示する', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    const preview = page.locator('#kkk-adj-preview .kkk-adj-preview--overlap');
    await expect(preview).toBeVisible({ timeout: 5000 });
    await expect(preview).toContainText('リアルタイム補正');
    await expect(preview).toContainText('洪水リスクが上昇しています');
    await expect(preview).toContainText('固定ハザードとキキクルが重なっています');
  });

  test('route-risk プレビューは backend 契約の緯度・経度順で座標を送る', async ({ page }) => {
    const routeRiskBodies = [];
    await mockSimTraffic(page, [], routeRiskBodies);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    await expect.poll(() => routeRiskBodies.length).toBeGreaterThan(0);
    expect(routeRiskBodies[0].coordinates).toEqual([
      [35.681236, 139.767125],
      [35.69, 139.78],
    ]);
  });

  test('取得不可シナリオの補正プレビューで neutral 表示が出る', async ({ page }) => {
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="unavailable"]').click();
    await expect(page.locator('#kkk-adj-preview .kkk-adj-preview--neutral')).toBeVisible({ timeout: 5000 });
  });

  test('通常画面 / ではキキクル検証パネルが存在しない', async ({ page }) => {
    await page.route('/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('**/jmatile/**', route => route.fulfill({
      status: 200, contentType: 'application/json', body: '[]',
    }));
    await page.goto('/');
    await expect(page.locator('#kkk-adj-section')).toHaveCount(0);
    await expect(page.locator('.kkk-scenario-btn')).toHaveCount(0);
  });

  test('シミュレーション操作は JMA タイル取得や localStorage 永続化を行わない', async ({ page }) => {
    const requests = [];
    await mockSimTraffic(page, requests);
    await page.goto('/admin/simulation.html');
    await page.locator('.kkk-scenario-btn[data-key="three_danger"]').click();
    await expect(page.locator('#kkk-adj-preview')).toContainText('リアルタイム補正');
    expect(requests.filter(url => url.includes('jmatile')).length).toBe(0);
    expect(await page.evaluate(() => Object.keys(localStorage).filter(key => /kikikuru/i.test(key)))).toEqual([]);
  });

  test('モバイル幅でシナリオ操作と結果確認が横はみ出しなく行える', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockSimTraffic(page);
    await page.goto('/admin/simulation.html');
    await expect(page.locator('#kkk-scenario-buttons')).toBeVisible();
    await page.locator('.kkk-scenario-btn[data-key="flood_danger"]').click();
    await expect(page.locator('#kkk-summary-route')).toContainText('洪水 危険');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });

});
