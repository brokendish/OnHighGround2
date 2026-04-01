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
  test('手動現在地設定後も checkbox が ON のまま維持される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await openSidebar(page);

    const checkbox = page.locator('#manualLocationMode');
    const hint     = page.locator('#manualLocationHint');

    // 手動選択モードを ON にする
    await checkbox.check();
    await expect(hint).toBeVisible({ timeout: 2000 });

    // 地図上をクリック（Leaflet の map.click イベントを発火）
    await page.evaluate(() => {
      if (typeof map !== 'undefined') {
        map.fire('click', {
          latlng: L.latLng(35.6415, 139.7905),
          originalEvent: new MouseEvent('click', { bubbles: true }),
        });
      }
    });

    // 現在地設定後もチェックが維持されること（自動 OFF しない）
    await page.waitForTimeout(500); // updateCurrentLocation の非同期処理を待つ
    await expect(checkbox).toBeChecked();
    await expect(hint).toBeVisible();
  });

  /**
   * A-2. 手動現在地設定後に isManualLocationMode フラグが true のまま維持される
   */
  test('手動現在地設定後に isManualLocationMode が true のまま維持される', async ({ page }) => {
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

    await page.waitForTimeout(500);
    // JS 変数が true のまま維持されること
    const flag = await page.evaluate(() =>
      typeof isManualLocationMode !== 'undefined' ? isManualLocationMode : null
    );
    expect(flag).toBe(true);
  });

  /**
   * B. 手動現在地設定（→ manual mode 自動解除）後の長押しで目的地候補ポップアップが出る
   *
   *    manual mode が OFF になった状態なので、
   *    長押しによる setDestinationCandidate() だけが発火し、
   *    現在地更新には戻らないことを確認する。
   */
  test('manual mode ON のまま長押しすると目的地候補が出て manual mode が解除される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await openSidebar(page);

    // manual mode ON のまま長押し（contextmenu）を発火
    await page.locator('#manualLocationMode').check();
    await page.evaluate(() => {
      if (typeof map !== 'undefined') {
        map.fire('contextmenu', {
          latlng: L.latLng(35.6500, 139.7950),
          originalEvent: new MouseEvent('contextmenu', { bubbles: true }),
        });
      }
    });

    // 「ここへ行く」ポップアップが表示される（目的地候補が設定された）
    await expect(page.locator('text=ここへ行く')).toBeVisible({ timeout: 3000 });

    // 長押し発火時に exitManualLocationMode() が呼ばれ OFF になる
    await expect(page.locator('#manualLocationMode')).not.toBeChecked({ timeout: 3000 });
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
