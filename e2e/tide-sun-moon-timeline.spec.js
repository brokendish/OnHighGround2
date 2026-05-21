/**
 * tide-sun-moon-timeline.spec.js — 潮位パネルの日月タイムライン回帰テスト。
 *
 * backend 不要。location-info-panel.js のタイムライン描画だけを直接検証する。
 */

'use strict';

const { test, expect } = require('@playwright/test');

async function openApp(page, apiHandler) {
  await page.route('/api/**', apiHandler || (route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{}',
  })));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.goto('/');
  await expect(page.locator('#lip-sun-moon-timeline')).toHaveCount(1);
  await page.evaluate(() => {
    const section = document.getElementById('lip-tide-section');
    if (section) section.style.display = 'block';
  });
}

const BASE_DAY = {
  sunrise: '2026-05-16T05:00:00+09:00',
  sunset: '2026-05-16T18:00:00+09:00',
  moonrise: null,
  moonset: null,
};

const NEXT_DAY = {
  sunrise: '2026-05-17T05:00:00+09:00',
  sunset: '2026-05-17T18:00:00+09:00',
  moonrise: null,
  moonset: null,
};

async function drawTimelineAndSample(page, { today = BASE_DAY, tomorrow = NEXT_DAY, previous = null, x = 200, y = 96 }) {
  return page.evaluate(({ today, tomorrow, previous, x, y }) => {
    const canvas = document.createElement('canvas');
    canvas.width = 400;
    canvas.height = 130;
    canvas.style.width = '400px';
    canvas.style.height = '130px';
    canvas.style.display = 'block';
    document.body.appendChild(canvas);
    const tMin = Date.parse('2026-05-16T00:00:00+09:00');
    const tMax = tMin + 24 * 3600 * 1000;
    _tlDrawCore({ canvas, todayData: today, tomorrowData: tomorrow, tMin, tMax, prevData: previous, nowMs: (tMin + tMax) / 2 }, 0);
    const pixel = Array.from(canvas.getContext('2d').getImageData(x, y, 1, 1).data);
    canvas.remove();
    return pixel;
  }, { today, tomorrow, previous, x, y });
}

function expectMoonBand(pixel) {
  expect(pixel[0]).toBeGreaterThan(60);
  expect(pixel[1]).toBeGreaterThan(70);
  expect(pixel[2]).toBeGreaterThan(85);
  expect(pixel[3]).toBe(255);
}

function expectMoonBackground(pixel) {
  expect(pixel[0]).toBeLessThan(50);
  expect(pixel[1]).toBeLessThan(60);
  expect(pixel[2]).toBeLessThan(80);
  expect(pixel[3]).toBe(255);
}

test.describe('Tide panel: sun/moon timeline', () => {
  test('24h 更新時に前日・当日・翌日の天体データを取得する', async ({ page }) => {
    const fetched = [];
    await openApp(page, async route => {
      const url = new URL(route.request().url());
      if (url.pathname !== '/api/astro/current') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
        return;
      }
      const date = url.searchParams.get('date');
      if (date) fetched.push(date);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sunrise: `${date}T05:00:00+09:00`,
          sunset: `${date}T18:00:00+09:00`,
          moonrise: null,
          moonset: null,
        }),
      });
    });

    const tMin = Date.parse('2026-05-16T21:00:00+09:00');
    await page.evaluate(async (start) => {
      await _sunMoonTimelineUpdate(35.6415, 139.7905, start, start + 24 * 3600 * 1000);
    }, tMin);

    expect(fetched.sort()).toEqual(['2026-05-16', '2026-05-17', '2026-05-18']);
  });

  test('前日から月が出たままの24h窓を月帯として描画する', async ({ page }) => {
    await openApp(page);

    const pixel = await drawTimelineAndSample(page, {
      previous: {
        sunrise: '2026-05-15T05:00:00+09:00',
        sunset: '2026-05-15T18:00:00+09:00',
        moonrise: '2026-05-15T22:00:00+09:00',
        moonset: null,
      },
    });

    expectMoonBand(pixel);
  });

  test('日の出・日の入が24h窓外でもタイムラインを描画できる', async ({ page }) => {
    await openApp(page);

    const sunPixel = await drawTimelineAndSample(page, {
      today: {
        sunrise: '2026-05-15T05:00:00+09:00',
        sunset: '2026-05-15T18:00:00+09:00',
        moonrise: null,
        moonset: null,
      },
      tomorrow: null,
      previous: null,
      x: 200,
      y: 43,
    });

    expect(sunPixel[3]).toBe(255);
  });

  test('月の出だけある場合は月の出以降を月帯として描画する', async ({ page }) => {
    await openApp(page);

    const beforeRise = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: '2026-05-16T06:00:00+09:00', moonset: null },
      x: 80,
    });
    const afterRise = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: '2026-05-16T06:00:00+09:00', moonset: null },
      x: 250,
    });

    expectMoonBackground(beforeRise);
    expectMoonBand(afterRise);
  });

  test('月の入だけある場合は開始時点から月の入までを月帯として描画する', async ({ page }) => {
    await openApp(page);

    const beforeSet = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: null, moonset: '2026-05-16T09:00:00+09:00' },
      x: 80,
    });
    const afterSet = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: null, moonset: '2026-05-16T09:00:00+09:00' },
      x: 250,
    });

    expectMoonBand(beforeSet);
    expectMoonBackground(afterSet);
  });

  test('moonrise / moonset が null の場合は月帯なしで描画する', async ({ page }) => {
    await openApp(page);

    const pixel = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: null, moonset: null },
      tomorrow: { ...NEXT_DAY, moonrise: null, moonset: null },
      previous: {
        sunrise: '2026-05-15T05:00:00+09:00',
        sunset: '2026-05-15T18:00:00+09:00',
        moonrise: null,
        moonset: null,
      },
      x: 200,
    });

    expectMoonBackground(pixel);
  });

  test('前日から月が出ていて24h窓の途中で月入りするケースを描画する', async ({ page }) => {
    await openApp(page);

    const beforeSet = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: null, moonset: '2026-05-16T10:00:00+09:00' },
      previous: {
        sunrise: '2026-05-15T05:00:00+09:00',
        sunset: '2026-05-15T18:00:00+09:00',
        moonrise: '2026-05-15T22:00:00+09:00',
        moonset: null,
      },
      x: 80,
    });
    const afterSet = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: null, moonset: '2026-05-16T10:00:00+09:00' },
      previous: {
        sunrise: '2026-05-15T05:00:00+09:00',
        sunset: '2026-05-15T18:00:00+09:00',
        moonrise: '2026-05-15T22:00:00+09:00',
        moonset: null,
      },
      x: 250,
    });

    expectMoonBand(beforeSet);
    expectMoonBackground(afterSet);
  });

  test('24h窓の途中で月が出て翌日に月入りするケースを描画する', async ({ page }) => {
    await openApp(page);

    const beforeRise = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: '2026-05-16T14:00:00+09:00', moonset: null },
      tomorrow: { ...NEXT_DAY, moonrise: null, moonset: '2026-05-17T04:00:00+09:00' },
      x: 80,
    });
    const afterRise = await drawTimelineAndSample(page, {
      today: { ...BASE_DAY, moonrise: '2026-05-16T14:00:00+09:00', moonset: null },
      tomorrow: { ...NEXT_DAY, moonrise: null, moonset: '2026-05-17T04:00:00+09:00' },
      x: 300,
    });

    expectMoonBackground(beforeRise);
    expectMoonBand(afterRise);
  });

  test('現在時刻ラインが潮位グラフと日月タイムラインで同じX座標になる', async ({ page }) => {
    await openApp(page);

    const result = await page.evaluate(({ today, tomorrow }) => {
      const tMin = Date.parse('2026-05-16T00:00:00+09:00');
      const tMax = tMin + 24 * 3600 * 1000;
      const tideCanvas = document.createElement('canvas');
      tideCanvas.width = 400;
      tideCanvas.height = 100;
      tideCanvas.style.width = '400px';
      tideCanvas.style.height = '100px';
      tideCanvas.style.display = 'block';
      const timelineCanvas = document.createElement('canvas');
      timelineCanvas.width = 400;
      timelineCanvas.height = 130;
      timelineCanvas.style.width = '400px';
      timelineCanvas.style.height = '130px';
      timelineCanvas.style.display = 'block';
      document.body.append(tideCanvas, timelineCanvas);
      _tideGraphDraw(
        tideCanvas,
        {
          records: [
            { datetime: '2026-05-16T00:00:00+09:00', tide_cm: 100 },
            { datetime: '2026-05-16T01:00:00+09:00', tide_cm: 110 },
          ],
          extremes: { high_tides: [], low_tides: [] },
        },
        tMin,
        tMax,
      );
      _tlDrawCore({ canvas: timelineCanvas, todayData: today, tomorrowData: tomorrow, tMin, tMax, prevData: null, nowMs: (tMin + tMax) / 2 }, 0);

      const hasRedNear = (canvas, expectedX, yStart, yEnd) => {
        const ctx = canvas.getContext('2d');
        for (let x = expectedX - 3; x <= expectedX + 3; x += 1) {
          for (let y = yStart; y <= yEnd; y += 1) {
            const [r, g, b, a] = ctx.getImageData(x, y, 1, 1).data;
            if (r > 200 && g < 120 && b < 120 && a > 0) {
              return true;
            }
          }
        }
        return false;
      };

      const dpr = window.devicePixelRatio || 1;
      const tideExpectedX = Math.round((68 + (400 - 68 - 10) / 2) * dpr);
      const timelineExpectedX = Math.round((68 + (400 - 68 - 10) / 2) * dpr);
      const result = {
        tideLine: hasRedNear(tideCanvas, tideExpectedX, 0, tideCanvas.height - 1),
        timelineLine: hasRedNear(timelineCanvas, timelineExpectedX, 0, timelineCanvas.height - 1),
      };
      tideCanvas.remove();
      timelineCanvas.remove();
      return result;
    }, { today: BASE_DAY, tomorrow: NEXT_DAY });

    expect(result.tideLine).toBe(true);
    expect(result.timelineLine).toBe(true);
  });

  test('折りたたみ再表示後に潮位Canvasと日月タイムラインの再描画が走る', async ({ page }) => {
    await openApp(page);

    const calls = await page.evaluate(async () => {
      let redraws = 0;
      _tideCache = {
        data: {
          available: true,
          station: { id: 'TK' },
        },
      };
      _tideGraphUpdate = async () => {
        redraws += 1;
      };

      _lipLevel = 1;
      _lipApplyLevel();
      _lipLevel = 2;
      _lipApplyLevel();
      await new Promise(resolve => setTimeout(resolve, 0));
      return redraws;
    });

    expect(calls).toBe(2);
  });
});
