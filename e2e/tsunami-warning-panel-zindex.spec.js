'use strict';

const { test, expect } = require('@playwright/test');

function tsunamiActiveBody(level = 'warning') {
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
    areas: [
      {
        code: null,
        name: '東京湾内湾',
        level,
        level_label: labels[level],
        expected_height: null,
        arrival_time: null,
        is_target: true,
      },
      {
        code: null,
        name: '相模湾・三浦半島沿岸',
        level,
        level_label: labels[level],
        expected_height: null,
        arrival_time: null,
        is_target: true,
      },
      {
        code: null,
        name: '千葉県九十九里・外房',
        level,
        level_label: labels[level],
        expected_height: null,
        arrival_time: null,
        is_target: true,
      },
      {
        code: null,
        name: '非常に長い対象地域名テスト海岸線ブロック',
        level,
        level_label: labels[level],
        expected_height: null,
        arrival_time: null,
        is_target: true,
      },
    ],
    message: `${labels[level]}が発表されています。`,
  };
}

async function setupTsunamiActiveMocks(page) {
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('/api/tsunami/warnings/current', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(tsunamiActiveBody('warning')),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
}

async function openExpandedInfoPanel(page) {
  await page.locator('#mbc-tab-btn-info').click();
  await expect(page.locator('#map-bottom-controls')).toHaveClass(/mbc-info-active/);
  await page.locator('#map-bottom-handle').click();
  await expect(page.locator('#map-bottom-controls')).toHaveClass(/mbc-info-expanded/);
}

test.describe('Tsunami warning banner and mobile info panel stacking', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setupTsunamiActiveMocks(page);
    await page.goto('/');
  });

  test('mobile tsunami warning stays behind expanded info panel controls', async ({ page }) => {
    const banner = page.locator('#tsunami-warning-banner');
    await expect(banner).toBeVisible({ timeout: 5000 });
    await expect(banner).toContainText('津波警報');

    await openExpandedInfoPanel(page);

    const layout = await page.evaluate(() => {
      const bannerEl = document.getElementById('tsunami-warning-banner');
      const overlay = document.getElementById('map-ui-overlay');
      const controls = document.getElementById('map-bottom-controls');
      const handle = document.getElementById('map-bottom-handle');
      const tabs = document.getElementById('mbc-tabs');
      const infoPanel = document.getElementById('mbc-tab-panel-info');
      const pointTarget = rect => {
        const x = rect.left + rect.width / 2;
        const y = rect.top + rect.height / 2;
        const el = document.elementFromPoint(x, y);
        const interactive = el?.closest?.('#map-bottom-handle, #map-bottom-controls, .mbc-tab-btn, #mbc-tabs');
        return el ? {
          id: el.id,
          tag: el.tagName,
          className: String(el.getAttribute('class') || ''),
          interactiveId: interactive?.id || '',
          interactiveClassName: String(interactive?.getAttribute?.('class') || ''),
        } : null;
      };
      const rectJson = el => el.getBoundingClientRect().toJSON();
      return {
        bannerVisible: bannerEl.offsetParent !== null,
        bodyRaised: document.body.classList.contains('mbc-panel-info-expanded'),
        bannerZ: getComputedStyle(bannerEl).zIndex,
        overlayZ: getComputedStyle(overlay).zIndex,
        controlsZ: getComputedStyle(controls).zIndex,
        overlayPointerEvents: getComputedStyle(overlay).pointerEvents,
        bannerPointerEvents: getComputedStyle(bannerEl).pointerEvents,
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        handleRect: rectJson(handle),
        tabsRect: rectJson(tabs),
        infoRect: rectJson(infoPanel),
        handleTopTarget: pointTarget(handle.getBoundingClientRect()),
        infoScrollable: infoPanel.scrollHeight > infoPanel.clientHeight,
      };
    });

    expect(layout.bannerVisible).toBe(true);
    expect(layout.bodyRaised).toBe(true);
    expect(Number(layout.overlayZ)).toBeGreaterThan(Number(layout.bannerZ));
    expect(layout.overlayPointerEvents).toBe('none');
    expect(layout.bannerPointerEvents).toBe('auto');
    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
    expect([
      layout.handleTopTarget.id,
      layout.handleTopTarget.className,
      layout.handleTopTarget.interactiveId,
      layout.handleTopTarget.interactiveClassName,
    ].join(' ')).toMatch(/map-bottom-handle|mbc-|map-bottom-controls/);
    expect(layout.infoScrollable).toBe(true);

    await page.screenshot({
      path: 'test-results/tsunami-warning-panel-zindex-mobile.png',
      fullPage: true,
    });
  });

  test('mobile info panel can be collapsed while tsunami warning is active', async ({ page }) => {
    await openExpandedInfoPanel(page);

    await page.locator('#map-bottom-handle').click();
    await expect(page.locator('#map-bottom-controls')).toHaveClass(/mbc-collapsed/);
    await expect(page.locator('#tsunami-warning-banner')).toBeVisible();
  });

  test('mobile info panel tabs and scrolling work while tsunami warning is active', async ({ page }) => {
    await openExpandedInfoPanel(page);

    await page.locator('#mbc-tab-btn-layer').click();
    await expect(page.locator('#mbc-tab-btn-layer')).toHaveClass(/mbc-tab-btn--active/);
    await expect(page.locator('#mbc-tab-panel-layer')).toBeVisible();

    await page.locator('#mbc-tab-btn-info').click();
    await expect(page.locator('#mbc-tab-btn-info')).toHaveClass(/mbc-tab-btn--active/);
    await expect(page.locator('#mbc-tab-panel-info')).toBeVisible();

    const scrollResult = await page.evaluate(() => {
      const panel = document.getElementById('mbc-tab-panel-info');
      const before = panel.scrollTop;
      panel.scrollTop = panel.scrollHeight;
      return {
        before,
        after: panel.scrollTop,
        scrollHeight: panel.scrollHeight,
        clientHeight: panel.clientHeight,
      };
    });

    expect(scrollResult.scrollHeight).toBeGreaterThan(scrollResult.clientHeight);
    expect(scrollResult.after).toBeGreaterThan(scrollResult.before);
    await expect(page.locator('#tsunami-warning-banner')).toBeVisible();
  });
});
