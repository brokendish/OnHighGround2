'use strict';

const { test, expect } = require('@playwright/test');

function tideHourlyPayload(date) {
  const records = Array.from({ length: 24 }, (_, h) => ({
    station: 'TK',
    datetime: `${date}T${String(h).padStart(2, '0')}:00:00+09:00`,
    tide_cm: Math.round(95 + Math.sin((h / 24) * Math.PI * 2) * 80),
  }));
  return {
    station: 'TK',
    date,
    records,
    extremes: {
      high_tides: [{ time: `${date}T04:00:00+09:00`, tide_cm: 188 }],
      low_tides: [{ time: `${date}T10:00:00+09:00`, tide_cm: 1 }],
    },
  };
}

async function openInfoTab(page, viewport) {
  if (viewport) await page.setViewportSize(viewport);

  await page.route('/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.route('/api/tide/current**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      lat: 35.6415,
      lon: 139.7905,
      available: true,
      station: { id: 'TK', name: '東京', distance_km: 2.3, lat: 35.65, lon: 139.767 },
      current_tide_cm: 97,
      next_high_tide: { time: '2026-05-16T17:00:00+09:00', tide_cm: 197, remaining_minutes: 90 },
      next_low_tide: { time: '2026-05-16T10:00:00+09:00', tide_cm: 1, remaining_minutes: 30 },
      source: 'jma',
    }),
  }));
  await page.route('/api/tide/hourly**', route => {
    const date = new URL(route.request().url()).searchParams.get('date') || '2026-05-16';
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tideHourlyPayload(date)) });
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
  await expect(page.locator('#lip-tide-card')).toBeVisible();
  await page.waitForTimeout(100);
}

test.describe('Info tab card UI', () => {
  test('現在状況カードに潮位・満干潮・観測地点・現在時刻が表示される', async ({ page }) => {
    await openInfoTab(page);

    await expect(page.locator('.lip-card-hdr-title').filter({ hasText: '現在状況カード' })).toBeVisible();
    await expect(page.locator('#lip-tide-card-num')).toHaveText('97');
    await expect(page.locator('#lip-tide-card-high-time')).toHaveText('17:00');
    await expect(page.locator('#lip-tide-card-low-time')).toHaveText('10:00');
    await expect(page.locator('#lip-tide-card-name')).toHaveText('東京');
    await expect(page.locator('#lip-tide-card-clock')).toContainText('現在時刻');

    await expect(page.locator('#lip-tide-card-high-time')).toHaveCSS('color', 'rgb(239, 68, 68)');
    await expect(page.locator('#lip-tide-card-low-time')).toHaveCSS('color', 'rgb(14, 165, 233)');
  });

  test('時間変化カード・環境カード・拡張カードがカード構造で表示される', async ({ page }) => {
    await openInfoTab(page);

    await expect(page.locator('.lip-card-hdr-title').filter({ hasText: '時間変化カード' })).toBeVisible();
    await expect(page.locator('#lip-tide-graph')).toBeVisible();
    await expect(page.locator('#lip-sun-moon-timeline')).toBeVisible();
    await expect(page.locator('.lip-card-hdr-title').filter({ hasText: '環境カード' })).toBeVisible();
    await expect(page.locator('#lip-astro-sunrise')).toHaveText('04:35');
    await expect(page.locator('#lip-astro-sunset')).toHaveText('18:39');
    await expect(page.locator('#lip-astro-moonrise')).toHaveText('03:35');
    await expect(page.locator('#lip-astro-moonset')).toHaveText('18:12');
    await expect(page.locator('#lip-env-dark-start')).toHaveText('18:39');
    await expect(page.locator('#lip-env-dark-end')).toHaveText('03:35');

    const weather = page.locator('.lip-card-hdr-title').filter({ hasText: '気象（将来予報）' });
    await expect(weather).toBeVisible();
    const weatherCard = weather.locator('xpath=ancestor::*[contains(@class, "lip-card-section")]');
    await expect(weatherCard).toHaveClass(/lip-accordion-collapsed/);
    await weather.click();
    await expect(weatherCard).not.toHaveClass(/lip-accordion-collapsed/);
  });

  test('モバイル幅でカード群が横スクロールを発生させない', async ({ page }) => {
    await openInfoTab(page, { width: 390, height: 844 });

    const overflow = await page.evaluate(() => {
      const panel = document.getElementById('mbc-tab-panel-info');
      return panel.scrollWidth - panel.clientWidth;
    });
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
