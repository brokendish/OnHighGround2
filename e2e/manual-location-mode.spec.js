/**
 * manual-location-mode.spec.js — 手動現在地モード競合バグ回帰テスト
 *
 * 「地図上から現在地を手動選択する」が ON のとき、
 * 現在地設定と長押し目的地設定が競合しないことを保証する。
 *
 * 検証対象:
 *   A. 手動現在地設定後に manual mode が自動解除される
 *   B. manual mode 解除後の長押しで目的地候補（📍 ポップアップ）が出る
 *   C. manual mode ON のまま長押しした場合、manual mode が解除されて目的地候補が出る
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── 共通モック ────────────────────────────────────────────────────────────────

async function setupBasicMocks(page) {
  await page.route('/api/elevation**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ elevation: 3.5, lat: 35.6415, lon: 139.7905 }),
  }));
  await page.route('/api/hazard-check**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ is_danger: false, hazards: [], hazard_assessment: {} }),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
}

async function openSidebar(page) {
  const wrapper = page.locator('#sidebarWrapper');
  const isOpen = await wrapper.evaluate(el => !el.classList.contains('collapsed'));
  if (!isOpen) {
    await page.locator('#sidebarToggle').click();
    await expect(wrapper).not.toHaveClass(/collapsed/, { timeout: 3000 });
  }
}

// ── テストケース ─────────────────────────────────────────────────────────────

test.describe('Manual Location Mode: 手動選択モード競合バグ回帰テスト', () => {

  /**
   * A. 手動現在地設定後に manual mode が自動解除される
   *
   *    checkbox を ON → 地図クリック（現在地設定）→
   *    checkbox が OFF になり hint が消える。
   */
  test('手動現在地設定後に checkbox が OFF になり hint が消える', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await openSidebar(page);

    const checkbox = page.locator('#manualLocationMode');
    const hint     = page.locator('#manualLocationHint');

    // 手動選択モードを ON にする
    await checkbox.check();
    await expect(hint).toBeVisible({ timeout: 2000 });

    // 地図上をクリック（page.evaluate で map.click イベントを発火）
    await page.evaluate(() => {
      // Leaflet の map.click イベントを擬似的に発火する
      if (typeof map !== 'undefined') {
        map.fire('click', {
          latlng: L.latLng(35.6415, 139.7905),
          originalEvent: new MouseEvent('click', { bubbles: true }),
        });
      }
    });

    // updateCurrentLocation が成功すると exitManualLocationMode() が呼ばれ OFF になる
    await expect(checkbox).not.toBeChecked({ timeout: 5000 });
    await expect(hint).toBeHidden({ timeout: 3000 });
  });

  /**
   * A-2. 手動現在地設定後に isManualLocationMode フラグが false になる
   *
   *      DOM だけでなく JS 変数側も確認。
   */
  test('手動現在地設定後に isManualLocationMode が false になる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await openSidebar(page);

    await page.locator('#manualLocationMode').check();

    // 地図クリックをイベントとして発火
    await page.evaluate(() => {
      if (typeof map !== 'undefined') {
        map.fire('click', {
          latlng: L.latLng(35.6415, 139.7905),
          originalEvent: new MouseEvent('click', { bubbles: true }),
        });
      }
    });

    // JS 変数が false になること
    await expect
      .poll(() => page.evaluate(() => typeof isManualLocationMode !== 'undefined' ? isManualLocationMode : null),
             { timeout: 5000 })
      .toBe(false);
  });

  /**
   * B. 手動現在地設定（→ manual mode 自動解除）後の長押しで目的地候補ポップアップが出る
   *
   *    manual mode が OFF になった状態なので、
   *    長押しによる setDestinationCandidate() だけが発火し、
   *    現在地更新には戻らないことを確認する。
   */
  test('manual mode 解除後の長押しで「ここへ行く」ポップアップが表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await openSidebar(page);

    // manual mode ON → 地図クリックで現在地設定 → 自動 OFF
    await page.locator('#manualLocationMode').check();
    await page.evaluate(() => {
      if (typeof map !== 'undefined') {
        map.fire('click', {
          latlng: L.latLng(35.6415, 139.7905),
          originalEvent: new MouseEvent('click', { bubbles: true }),
        });
      }
    });
    await expect(page.locator('#manualLocationMode')).not.toBeChecked({ timeout: 5000 });

    // manual mode が OFF になったので、次は長押しで目的地候補を設定する
    // setDestinationCandidate() を JS 経由で直接呼んで目的地ポップアップを確認
    await page.evaluate(() => {
      if (typeof setDestinationCandidate === 'function') {
        setDestinationCandidate(35.6500, 139.7950, 'テスト目的地');
      }
    });

    // 「ここへ行く」ポップアップが表示される
    await expect(page.locator('text=ここへ行く')).toBeVisible({ timeout: 3000 });

    // 現在地が目的地の座標に変わっていないこと（isManualLocationMode が OFF だったので）
    const isManual = await page.evaluate(() =>
      typeof isManualLocationMode !== 'undefined' ? isManualLocationMode : null
    );
    expect(isManual).toBe(false);
  });

  /**
   * C. manual mode ON のまま長押し → manual mode が解除されて目的地候補が出る
   *
   *    contextmenu / fireFromClient の先頭で exitManualLocationMode() を呼ぶため、
   *    長押し完了時点で manual mode が解除されていること。
   */
  test('manual mode ON のまま長押しすると manual mode が解除されて目的地候補が出る', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await openSidebar(page);

    const checkbox = page.locator('#manualLocationMode');
    const hint     = page.locator('#manualLocationHint');

    // manual mode ON のまま長押しを模擬
    await checkbox.check();
    await expect(hint).toBeVisible({ timeout: 2000 });

    // Leaflet の contextmenu イベントを直接発火（長押し相当）
    await page.evaluate(() => {
      if (typeof map !== 'undefined') {
        map.fire('contextmenu', {
          latlng: L.latLng(35.6500, 139.7950),
          originalEvent: new MouseEvent('contextmenu', { bubbles: true }),
        });
      }
    });

    // 目的地候補ポップアップが表示される
    await expect(page.locator('text=ここへ行く')).toBeVisible({ timeout: 3000 });

    // manual mode が解除されている
    await expect(checkbox).not.toBeChecked({ timeout: 3000 });
    await expect(hint).toBeHidden({ timeout: 3000 });
  });

  /**
   * C-2. デスクトップ長押し（mousedown timer 経由）でも manual mode が解除される
   *
   *      fireFromClient() 内の exitManualLocationMode() が効いていることを確認。
   *      Playwright の page.mouse で 700ms 長押しを実行する。
   */
  test('デスクトップ長押し（700ms mousedown）後に manual mode が解除される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await openSidebar(page);

    await page.locator('#manualLocationMode').check();
    await expect(page.locator('#manualLocationHint')).toBeVisible({ timeout: 2000 });

    // 地図中央付近でマウス長押し
    const mapBox = await page.locator('#map').boundingBox();
    const cx = mapBox.x + mapBox.width  / 2;
    const cy = mapBox.y + mapBox.height / 2;

    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.waitForTimeout(750);   // 600ms しきい値より十分長く
    await page.mouse.up();

    // 長押しで目的地候補が設定され、manual mode が解除されている
    await expect(page.locator('#manualLocationMode')).not.toBeChecked({ timeout: 3000 });
    await expect(page.locator('#manualLocationHint')).toBeHidden({ timeout: 3000 });

    // 「ここへ行く」ポップアップが表示されている
    await expect(page.locator('text=ここへ行く')).toBeVisible({ timeout: 3000 });
  });

});
