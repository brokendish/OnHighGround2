'use strict';

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
  'base64',
);

function tideHourlyPayload(date) {
  return {
    station: 'TK',
    date,
    records: Array.from({ length: 24 }, (_, hour) => ({
      station: 'TK',
      datetime: `${date}T${String(hour).padStart(2, '0')}:00:00+09:00`,
      tide_cm: Math.round(100 + Math.sin((hour / 24) * Math.PI * 2) * 70),
    })),
    extremes: {
      high_tides: [{ time: `${date}T04:00:00+09:00`, tide_cm: 185 }],
      low_tides: [{ time: `${date}T10:00:00+09:00`, tide_cm: 10 }],
    },
  };
}

function rainTimesPayload() {
  return {
    basetime: '20260521120000',
    times: [
      {
        validtime: '20260521115000',
        offset_minutes: -10,
        tile_url_template: '/rain-tiles/past/{z}/{x}/{y}.png',
      },
      {
        validtime: '20260521120000',
        offset_minutes: 0,
        tile_url_template: '/rain-tiles/now/{z}/{x}/{y}.png',
      },
      {
        validtime: '20260521121000',
        offset_minutes: 10,
        tile_url_template: '/rain-tiles/forecast/{z}/{x}/{y}.png',
      },
    ],
  };
}

async function openRainRadarInfoTab(page, viewport) {
  if (viewport) await page.setViewportSize(viewport);

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
  await page.route('/rain-tiles/**', route => route.fulfill({
    status: 200,
    contentType: 'image/png',
    body: TRANSPARENT_PNG,
  }));
  await page.route('/api/weather/rain/tile/times**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(rainTimesPayload()),
  }));
  await page.route('/api/tide/current**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      available: true,
      station: { id: 'TK', name: '東京', distance_km: 2.3, lat: 35.65, lon: 139.767 },
      current_tide_cm: 104,
      next_high_tide: { time: '2026-05-16T17:00:00+09:00', tide_cm: 190 },
      next_low_tide: { time: '2026-05-16T10:00:00+09:00', tide_cm: 10 },
    }),
  }));
  await page.route('/api/tide/hourly**', route => {
    const date = new URL(route.request().url()).searchParams.get('date') || '2026-05-16';
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(tideHourlyPayload(date)),
    });
  });
  await page.route('/api/astro/current**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      sunrise: '2026-05-16T04:35:00+09:00',
      sunset: '2026-05-16T18:39:00+09:00',
      moonrise: '2026-05-16T03:35:00+09:00',
      moonset: '2026-05-16T18:12:00+09:00',
      moon_phase: 27.6,
      moon_label: '新月',
    }),
  }));

  await page.goto('/');
  await page.evaluate(async () => {
    switchMbcTab('info');
    _lipUpdateNavMode('browse');
    _lipUpdate(35.6415, 139.7905, 12);
    await _tideUpdate(35.6415, 139.7905);
    await _astroUpdate(35.6415, 139.7905);
  });
  await page.locator('#rain-toggle-btn').click();
  await expect(page.locator('#rain-toggle-btn')).toHaveClass(/map-overlay-btn--active/);
  await expect(page.locator('#lip-rain-slider')).toBeEnabled();
}

async function openWeatherCard(page) {
  const card = page.locator('#lip-weather-card-section');
  if (await card.evaluate(el => el.classList.contains('lip-accordion-collapsed'))) {
    await page.locator('#lip-weather-card-header').click();
  }
  await expect(card).not.toHaveClass(/lip-accordion-collapsed/);
  return card;
}

test.describe('Weather card rain radar controls', () => {
  test('雨量レーダー controls は気象カード内で操作でき、折りたたみ状態を保つ', async ({ page }) => {
    await openRainRadarInfoTab(page);

    const errors = [];
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });

    const card = await openWeatherCard(page);
    const radar = page.locator('#lip-rain-radar-ctrl-section');
    await expect(radar).toBeVisible();
    await expect(radar.locator('.lip-section-title')).toContainText('雨量レーダー予測');
    await expect(page.locator('#lip-weather-card-section #lip-rain-radar-ctrl-section')).toHaveCount(1);
    await expect(page.locator('#loc-info-nonnav > #lip-rain-radar-ctrl-section')).toHaveCount(0);

    await page.locator('#lip-rain-slider').fill('-10');
    await expect(page.locator('#lip-rain-offset-label')).toHaveText('10分前');
    await expect.poll(() => page.evaluate(() => _rainLayer && _rainLayer._url)).toContain('/rain-tiles/past/');

    await page.locator('#lip-rain-now-btn').click();
    await expect(page.locator('#lip-rain-slider')).toHaveValue('0');
    await expect(page.locator('#lip-rain-offset-label')).toHaveText('現在');
    await expect.poll(() => page.evaluate(() => _rainLayer && _rainLayer._url)).toContain('/rain-tiles/now/');

    await page.locator('#lip-rain-anim-btn').click();
    await expect(page.locator('#lip-rain-anim-btn')).toContainText('停止');
    await expect.poll(() => page.evaluate(() => rainRadar.offset), { timeout: 2500 }).not.toBe(0);
    await expect(page.locator('#lip-rain-offset-label')).not.toHaveText('現在');
    await expect.poll(() => page.evaluate(() => _rainLayer && _rainLayer._url)).not.toContain('/rain-tiles/now/');
    await expect(page.locator('#lip-rain-time-text')).not.toHaveText('');
    await page.locator('#lip-rain-anim-btn').click();

    await page.locator('#lip-rain-slider').fill('-10');
    await page.locator('#lip-weather-card-header').click();
    await expect(card).toHaveClass(/lip-accordion-collapsed/);
    await expect(radar).toBeHidden();
    await page.locator('#lip-weather-card-header').click();
    await expect(radar).toBeVisible();
    await expect(page.locator('#lip-rain-slider')).toHaveValue('-10');

    await expect(page.locator('#lip-tide-graph')).toBeVisible();
    await expect(page.locator('#lip-sun-moon-timeline')).toBeVisible();
    await expect(page.locator('#lip-astro-section')).toBeVisible();
    await expect(page.locator('.lip-section-title').filter({ hasText: '周辺の安全情報' })).toBeVisible();
    await expect(page.locator('.lip-card-hdr-title').filter({ hasText: '地震' })).toBeVisible();
    await expect(page.locator('.lip-card-hdr-title').filter({ hasText: 'その他情報' })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('モバイルで rain radar controls が気象カード幅に収まる', async ({ page }) => {
    await openRainRadarInfoTab(page, { width: 390, height: 844 });
    await openWeatherCard(page);

    const layout = await page.evaluate(() => {
      const panel = document.getElementById('mbc-tab-panel-info');
      const card = document.getElementById('lip-weather-card-section');
      const slider = document.getElementById('lip-rain-slider');
      const nowBtn = document.getElementById('lip-rain-now-btn');
      const animBtn = document.getElementById('lip-rain-anim-btn');
      const body = card.querySelector('.lip-accordion-body');
      panel.scrollTop = panel.scrollHeight;
      const panelRect = panel.getBoundingClientRect();
      const bodyRect = body.getBoundingClientRect();
      const fitsBody = el => {
        const rect = el.getBoundingClientRect();
        return rect.left >= bodyRect.left - 1 && rect.right <= bodyRect.right + 1;
      };
      return {
        overflow: panel.scrollWidth - panel.clientWidth,
        panelScrollable: panel.scrollHeight > panel.clientHeight,
        panelScrolled: panel.scrollTop > 0 || panel.scrollHeight <= panel.clientHeight,
        panelHeight: panelRect.height,
        sliderFits: fitsBody(slider),
        nowFits: fitsBody(nowBtn),
        animFits: fitsBody(animBtn),
      };
    });

    expect(layout.overflow).toBeLessThanOrEqual(1);
    expect(layout.panelScrollable).toBe(true);
    expect(layout.panelScrolled).toBe(true);
    expect(layout.panelHeight).toBeGreaterThan(0);
    expect(layout.sliderFits).toBe(true);
    expect(layout.nowFits).toBe(true);
    expect(layout.animFits).toBe(true);
  });
});
