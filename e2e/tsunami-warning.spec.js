'use strict';

const { test, expect } = require('@playwright/test');

function tsunamiBody(level) {
  if (level === 'none') {
    return {
      source: 'mock',
      status: 'none',
      observed_at: null,
      updated_at: new Date().toISOString(),
      ttl_seconds: 60,
      areas: [],
      message: '',
    };
  }
  const labels = {
    major_warning: '大津波警報',
    warning: '津波警報',
    advisory: '津波注意報',
  };
  return {
    source: 'mock',
    status: 'active',
    observed_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ttl_seconds: 60,
    areas: [{
      code: null,
      name: '東京湾内湾',
      level,
      level_label: labels[level],
      expected_height: null,
      arrival_time: null,
      is_target: true,
    }],
    message: `${labels[level]}が発表されています。`,
  };
}

async function setupCommonMocks(page, level) {
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('/api/tsunami/warnings/current', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(tsunamiBody(level)),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
}

test.describe('Tsunami warning banner', () => {
  test('通常時は控えめに非表示で、地図表示を壊さない', async ({ page }) => {
    await setupCommonMocks(page, 'none');
    await page.goto('/');

    await expect(page.locator('#map')).toBeVisible();
    await expect(page.locator('#tsunami-warning-banner')).toBeHidden();
  });

  test('津波注意報は橙系バナーで対象エリアを表示する', async ({ page }) => {
    await setupCommonMocks(page, 'advisory');
    await page.goto('/');

    const banner = page.locator('#tsunami-warning-banner');
    await expect(banner).toBeVisible({ timeout: 5000 });
    await expect(banner).toHaveClass(/tw-advisory/);
    await expect(banner).toContainText('東京湾内湾');
  });

  test('津波警報は赤系バナーを出し津波レイヤーを自動ONにする', async ({ page }) => {
    await setupCommonMocks(page, 'warning');
    await page.goto('/');

    const banner = page.locator('#tsunami-warning-banner');
    await expect(banner).toBeVisible({ timeout: 5000 });
    await expect(banner).toHaveClass(/tw-danger/);
    await expect(page.locator('#showTsunamiHazardTokyo')).toBeChecked();
  });

  test('津波警報中はナビ中UIにも警告を表示する', async ({ page }) => {
    await setupCommonMocks(page, 'warning');
    await page.goto('/');

    await page.evaluate(async () => {
      navigationMode = 'navigation_active';
      await _tsunamiWarningUpdate();
    });

    const navBanner = page.locator('#navBanner');
    await expect(navBanner).toBeVisible({ timeout: 5000 });
    await expect(navBanner).toContainText('津波警報');
    await expect(navBanner).toHaveClass(/nav-banner-danger/);
  });

  test('大津波警報は最重要警告文言として表示する', async ({ page }) => {
    await setupCommonMocks(page, 'major_warning');
    await page.goto('/');

    const banner = page.locator('#tsunami-warning-banner');
    await expect(banner).toBeVisible({ timeout: 5000 });
    await expect(banner).toHaveClass(/tw-danger/);
    await expect(banner).toContainText('大津波警報');
  });

  test('forecast（津波予報）のみの場合はバナーを表示しない', async ({ page }) => {
    // JMAが advisory → forecast に格下げした状態（解除途中）
    await page.route('/api/**', route => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({}),
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('/api/tsunami/warnings/current', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        source: 'jma_xml',
        status: 'active',
        observed_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ttl_seconds: 60,
        areas: [
          { code: null, name: '茨城県',               level: 'forecast', level_label: '津波予報', expected_height: null, arrival_time: null, is_target: false },
          { code: null, name: '千葉県九十九里・外房', level: 'forecast', level_label: '津波予報', expected_height: null, arrival_time: null, is_target: false },
          { code: null, name: '千葉県内房',           level: 'forecast', level_label: '津波予報', expected_height: null, arrival_time: null, is_target: false },
        ],
        message: '津波予報が発表されています。',
      }),
    }));

    await page.goto('/');
    // 津波予報は避難不要レベル — バナーを出してはいけない
    await expect(page.locator('#tsunami-warning-banner')).toBeHidden({ timeout: 5000 });
  });

  test('status=stale のときは警告バナーを表示しない', async ({ page }) => {
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
    await page.route('/api/tsunami/warnings/current', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        source: 'jma_xml',
        status: 'stale',
        observed_at: new Date(Date.now() - 3_600_000).toISOString(),
        updated_at: new Date().toISOString(),
        ttl_seconds: 60,
        areas: [{
          code: null,
          name: '東京湾内湾',
          level: 'warning',
          level_label: '津波警報',
          expected_height: null,
          arrival_time: null,
          is_target: false,
        }],
        message: '津波警報が発表されています。',
      }),
    }));

    await page.goto('/');
    // stale は情報古い可能性があり、避難警告バナーとして表示してはいけない
    await expect(page.locator('#tsunami-warning-banner')).toBeHidden({ timeout: 5000 });
  });

  test('status=cleared のとき（解除後）はバナーが非表示', async ({ page }) => {
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
    await page.route('/api/tsunami/warnings/current', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        source: 'mock',
        status: 'cleared',
        observed_at: null,
        updated_at: new Date().toISOString(),
        ttl_seconds: 60,
        areas: [],
        message: '',
      }),
    }));

    await page.goto('/');
    await expect(page.locator('#tsunami-warning-banner')).toBeHidden({ timeout: 5000 });
  });

  test('API取得失敗後に古い警告が出続けない', async ({ page }) => {
    let failMode = false;

    // Playwright: 後から登録したルートが優先されるため、特定ルートは最後に登録する
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
    await page.route('/api/tsunami/warnings/current', route => {
      if (failMode) {
        route.fulfill({ status: 500 });
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(tsunamiBody('advisory')),
        });
      }
    });

    await page.goto('/');
    const banner = page.locator('#tsunami-warning-banner');

    // 初回: 津波注意報バナーが表示される
    await expect(banner).toBeVisible({ timeout: 5000 });

    // API を失敗モードへ切替え、手動更新を呼ぶ
    failMode = true;
    await page.evaluate(() => _tsunamiWarningUpdate());

    // バナーが非表示になる（古い警告を出し続けない）
    await expect(banner).toBeHidden({ timeout: 3000 });
  });

  test('APIが500エラーの場合はバナーを表示しない', async ({ page }) => {
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
    await page.route('/api/tsunami/warnings/current', route => route.fulfill({
      status: 500,
    }));

    await page.goto('/');
    await expect(page.locator('#tsunami-warning-banner')).toBeHidden({ timeout: 5000 });
  });
});
