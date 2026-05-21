'use strict';

const { test, expect } = require('@playwright/test');

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

async function openRainyInfoTab(page, viewport) {
  if (viewport) await page.setViewportSize(viewport);

  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{}',
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
  await page.route('/api/weather/alerts/current**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'ok',
      severity: 'none',
      alerts: [],
      location: { area_name: '江東区' },
      updated_at: '2026-05-16T12:00:00+09:00',
    }),
  }));
  await page.route('/api/weather/precipitation/summary**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'ok',
      severity: 'advisory',
      current: { intensity: 'weak', label: '弱い雨' },
      forecast: [{ minutes: 30, intensity: 'moderate' }],
    }),
  }));
  await page.route('/api/weather/risk/context**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'ok', risk_level: 'none', combined: [], hazards: {} }),
  }));
  await page.goto('/');
  await page.evaluate(async () => {
    switchMbcTab('info');
    _lipUpdateNavMode('browse');
    _lipUpdate(35.6415, 139.7905, 12);
    await _tideUpdate(35.6415, 139.7905);
    await _astroUpdate(35.6415, 139.7905);
    await _weatherServiceUpdate(35.6415, 139.7905);
  });
  await expect(page.locator('#weather-alert-banner')).toContainText('現在地周辺で雨域を検出');
  await expect(page.locator('#lip-sun-moon-timeline')).toBeVisible();
}

test.describe('Rainy weather sun/moon layout', () => {
  test('雨域バナーと気象カード更新後も天体カードとタイムラインを残す', async ({ page }) => {
    await openRainyInfoTab(page);

    await expect(page.locator('#lip-astro-section')).toBeVisible();
    await expect(page.locator('#lip-astro-sunrise')).toHaveText('04:35');
    await expect(page.locator('#lip-astro-moonrise')).toHaveText('03:35');
    await expect(page.locator('#lip-astro-note')).toContainText('月齢');
    await expect(page.locator('#lip-wc-precip-summary')).toContainText('弱い雨');

    const state = await page.locator('#lip-sun-moon-timeline').evaluate(canvas => {
      const rect = canvas.getBoundingClientRect();
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      return {
        width: rect.width,
        height: rect.height,
        hasPaint: pixels.some((value, index) => index % 4 === 3 && value > 0),
        inTimeCard: !!canvas.closest('.lip-card-section'),
      };
    });
    expect(state.width).toBeGreaterThanOrEqual(100);
    expect(state.height).toBeGreaterThan(0);
    expect(state.hasPaint).toBe(true);
    expect(state.inTimeCard).toBe(true);
  });

  test('雨域バナー表示中のモバイル情報タブに横スクロールを出さない', async ({ page }) => {
    await openRainyInfoTab(page, { width: 390, height: 844 });

    const overflow = await page.evaluate(() => {
      const panel = document.getElementById('mbc-tab-panel-info');
      return panel.scrollWidth - panel.clientWidth;
    });
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
