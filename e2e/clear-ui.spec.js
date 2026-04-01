/**
 * clear-ui.spec.js — クリア動作回帰テスト
 *
 * 「地図をクリア」実行後にナビ関連の残存 UI が消えることを保証する。
 *
 * 検証対象:
 *   - #nav-announcement-bar（音声ナビ到着表示バー）
 *   - #navBanner（ナビステータスバー）
 *   - #recommendedPanel（推奨カード）
 *   - #destinationsPanel（候補一覧）
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── 共通モックセットアップ ────────────────────────────────────────────────────

async function setupBasicMocks(page, evacuationBody = null) {
  await page.route('/api/elevation**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ elevation: 3.5, lat: 35.6415, lon: 139.7905 }),
  }));
  await page.route('/api/hazard-check**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ is_danger: false, hazards: [], hazard_assessment: {} }),
  }));
  await page.route('/api/evacuation', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(evacuationBody ?? {
      current_location: { lat: 35.6415, lon: 139.7905, elevation: 3.5 },
      hazard_status: { is_danger: false, hazards: [] },
      time_to_impact: { supported: false },
      recommended: {
        name: '東雲小学校', type: 'emergency_shelter',
        lat: 35.65, lon: 139.80, elevation: 5.0, elevation_gain: 1.5,
        distance: 800, estimated_time_minutes: 12, safety_score: 45.0,
        hazard_safe: true,
        hazard_assessment: { tsunami: 'outside', flood: 'outside' },
        reason: 'テスト用',
      },
      destinations: [{
        name: '東雲小学校', type: 'emergency_shelter',
        lat: 35.65, lon: 139.80, elevation: 5.0, elevation_gain: 1.5,
        distance: 800, estimated_time_minutes: 12, safety_score: 45.0,
        hazard_safe: true,
        hazard_assessment: { tsunami: 'outside', flood: 'outside' },
      }],
      search_parameters: { transport_mode: 'walking', max_distance: 2000, min_elevation_gain: 10 },
    }),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
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

async function triggerSearch(page) {
  await openSidebar(page);
  await page.locator('#getCurrentLocation').click();
  await expect(page.locator('#getCurrentLocation')).toHaveText('現在地を取得', { timeout: 8000 });
  const searchBtn = page.locator('#searchDestinations');
  await expect(searchBtn).toBeEnabled({ timeout: 5000 });
  await searchBtn.click();
  await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
}

// ── テストケース ─────────────────────────────────────────────────────────────

test.describe('Clear UI: クリア動作回帰テスト', () => {

  /**
   * 1. 音声ナビ到着バー（#nav-announcement-bar）がクリアで消える
   *
   *    voiceNav.announce() で arrival カテゴリのメッセージを表示してからクリア。
   *    arrival は自動非表示しない設計なので、クリアで消えなければ UI 残存バグ。
   */
  test('到着メッセージ表示後にクリアすると #nav-announcement-bar が非表示になる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');

    // page.evaluate で voiceNav.announce() を直接呼んで到着バーを表示させる
    // （GPS ナビ到着を E2E 再現する最小手段）
    await page.evaluate(() => {
      if (typeof voiceNav !== 'undefined') {
        voiceNav.announce({
          id: 'nav-arrival-test',
          text: '目的地に到着しました',
          displayText: '目的地に到着しました',
          category: 'arrival',
          priority: 'high',
        });
      }
    });

    // バーが表示されていることを確認
    const bar = page.locator('#nav-announcement-bar');
    await expect(bar).toBeVisible({ timeout: 3000 });

    // clearMap を JavaScript 経由で発火（クリックが地図に遮蔽される場合のフォールバック）
    await page.evaluate(() => {
      document.getElementById('clearMap').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    // クリア後にバーが非表示になること
    await expect(bar).toBeHidden({ timeout: 3000 });
  });

  /**
   * 2. #navBanner がクリアで消える
   *
   *    _showNavBanner() を直接呼んでバナーを表示してからクリア。
   */
  test('navBanner 表示後にクリアすると #navBanner が非表示になる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');

    // _showNavBanner を直接呼んでバナーを表示
    await page.evaluate(() => {
      const banner = document.getElementById('navBanner');
      if (banner) {
        banner.textContent = '🏁 目的地に到達しました！お疲れさまでした。';
        banner.className = 'nav-banner nav-banner-success';
        banner.style.display = 'block';
      }
    });

    await expect(page.locator('#navBanner')).toBeVisible({ timeout: 3000 });

    await page.evaluate(() => {
      document.getElementById('clearMap').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    await expect(page.locator('#navBanner')).toBeHidden({ timeout: 3000 });
  });

  /**
   * 3. 避難先検索後にクリアすると推奨カード・候補一覧が消える
   */
  test('避難先検索後にクリアすると推奨カードと候補一覧が非表示になる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');
    await triggerSearch(page);

    // 検索結果が表示されていることを確認
    await expect(page.locator('#recommendedPanel')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 5000 });

    // clearMap ボタンをクリック（サイドバー内なので openSidebar 済み）
    await page.evaluate(() => {
      document.getElementById('clearMap').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    // 推奨カードと候補一覧が非表示になること
    await expect(page.locator('#recommendedPanel')).toBeHidden({ timeout: 3000 });
    await expect(page.locator('#destinationsPanel')).toBeHidden({ timeout: 3000 });
  });

  /**
   * 4. クリア後に古いナビ文言（到着・危険警告）がページ内に残らない
   */
  test('クリア後に到着・警告文言がページ内に残らない', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto('/');

    // 到着バーと navBanner を両方表示
    await page.evaluate(() => {
      // 音声ナビバー
      if (typeof voiceNav !== 'undefined') {
        voiceNav.announce({
          id: 'nav-arrival-test2',
          text: '目的地に到着しました',
          displayText: '目的地に到着しました',
          category: 'arrival',
          priority: 'high',
        });
      }
      // navBanner
      const banner = document.getElementById('navBanner');
      if (banner) {
        banner.textContent = '🏁 目的地に到達しました！お疲れさまでした。';
        banner.className = 'nav-banner nav-banner-success';
        banner.style.display = 'block';
      }
    });

    await page.evaluate(() => {
      document.getElementById('clearMap').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    // 表示中の要素（hidden でない）に到着・警告文言が含まれないこと
    await expect(page.locator('#nav-announcement-bar:visible')).toHaveCount(0);
    await expect(page.locator('#navBanner:visible')).toHaveCount(0);
  });
});
