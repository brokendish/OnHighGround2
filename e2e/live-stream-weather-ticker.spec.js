'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const DEMO_NOW = '2026-07-03T13:05:00%2B09:00';

function streamUrl(query) {
  const sep = (query || '').includes('?') ? '&' : '?';
  return `${DOCKER_BASE}/live/stream${query || ''}${sep}focusSpeed=test&runtimeSpeed=test&weatherSpeed=test&demoNow=${DEMO_NOW}`;
}

function weatherPoint(overrides) {
  return Object.assign({
    id: 'kanto_tokyo',
    pref_code: '13',
    pref_name: '東京都',
    point_name: '東京',
    display_order: 310,
    weather_code: 3,
    weather_category: 'cloudy',
    weather_label: '曇',
    temperature_c: 28.0,
    humidity_percent: 76,
    precipitation_probability_percent: 40,
    flags: {
      precipitation_high: false,
      temperature_hot: false,
      temperature_cold: false,
      humidity_high: false,
    },
  }, overrides || {});
}

function weatherResponse({ items, cacheStatus, forecastTime, fetchedAt } = {}) {
  return {
    status: cacheStatus === 'unavailable' && !items ? 'unavailable' : 'ok',
    source: 'Open-Meteo Forecast',
    forecast_time: forecastTime || '2026-07-03T13:00:00+09:00',
    fetched_at: fetchedAt || '2026-07-03T13:05:00+09:00',
    cache_status: cacheStatus || 'fresh',
    items: items || [weatherPoint()],
  };
}

async function mockAllLiveApis(page, { weather } = {}) {
  await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
  await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
  await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
  await page.route('**/api/live/weather/jma/prefectures**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify(weather || weatherResponse()),
  }));
}

async function gotoAndCapturePageErrors(page, url) {
  const pageErrors = [];
  page.on('pageerror', e => {
    const text = e.message || String(e);
    if (text.includes('Failed to fetch')) return;
    pageErrors.push(text);
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return pageErrors;
}

test.describe('/live/stream — Phase 8-A 全国気象ミニテロップ', () => {

  test('1: パネルが右カラム上部（鉄道情報より前）に表示され、出典が明記される', async ({ page }) => {
    await mockAllLiveApis(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl());
    const panel = page.locator('[data-testid="live-stream-panel-weather"]');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('全国気象');
    await expect(page.locator('[data-testid="live-stream-source-badge-weather"]')).toHaveText('Open-Meteo Forecast');

    const order = await page.evaluate(() => {
      const cols = document.querySelectorAll('.ls-col');
      const rightCol = cols[cols.length - 1];
      const children = Array.from(rightCol.children);
      return children.map(el => el.getAttribute('data-panel'));
    });
    expect(order.indexOf('weather')).toBeLessThan(order.indexOf('railway'));
    expect(order.indexOf('weather')).toBeLessThan(order.indexOf('tide'));
    expect(errors).toEqual([]);
  });

  test('2: ヘッダーに forecast_time / fetched_at がJST HH:mm形式で表示される', async ({ page }) => {
    await mockAllLiveApis(page, {
      weather: weatherResponse({ forecastTime: '2026-07-03T23:00:00+09:00', fetchedAt: '2026-07-03T23:05:12+09:00' }),
    });
    await gotoAndCapturePageErrors(page, streamUrl());
    await expect(page.locator('[data-testid="live-stream-weather-meta"]')).toContainText('23:00時点 / 23:05取得');
  });

  test('3: 地点セルに天気バッジ・気温・湿度・降水確率が表示される', async ({ page }) => {
    await mockAllLiveApis(page, {
      weather: weatherResponse({ items: [weatherPoint({ point_name: '那覇', weather_label: '晴', temperature_c: 30 })] }),
    });
    await gotoAndCapturePageErrors(page, streamUrl());
    const cell = page.locator('[data-testid="live-stream-weather-point"]').first();
    await expect(cell).toContainText('那覇');
    await expect(cell).toContainText('晴');
    await expect(cell).toContainText('30℃');
    await expect(cell.locator('.wm-badge')).toHaveCount(1);
  });

  test('4: 降水確率70%以上・気温35℃以上・0℃以下・湿度85%以上が強調classになる', async ({ page }) => {
    await mockAllLiveApis(page, {
      weather: weatherResponse({
        items: [weatherPoint({
          id: 'p1', point_name: '強調地点', temperature_c: 35, humidity_percent: 85,
          precipitation_probability_percent: 70,
          flags: { precipitation_high: true, temperature_hot: true, temperature_cold: false, humidity_high: true },
        })],
      }),
    });
    await gotoAndCapturePageErrors(page, streamUrl());
    const cell = page.locator('[data-testid="live-stream-weather-point"]').first();
    await expect(cell.locator('.wm-flag-precip-high')).toHaveCount(1);
    await expect(cell.locator('.wm-flag-temp-hot')).toHaveCount(1);
    await expect(cell.locator('.wm-flag-humidity-high')).toHaveCount(1);
  });

  test('5: 気温0℃以下は低温強調classになる', async ({ page }) => {
    await mockAllLiveApis(page, {
      weather: weatherResponse({
        items: [weatherPoint({
          id: 'p1', point_name: '稚内', temperature_c: -2,
          flags: { precipitation_high: false, temperature_hot: false, temperature_cold: true, humidity_high: false },
        })],
      }),
    });
    await gotoAndCapturePageErrors(page, streamUrl());
    const cell = page.locator('[data-testid="live-stream-weather-point"]').first();
    await expect(cell.locator('.wm-flag-temp-cold')).toHaveCount(1);
  });

  test('6: 7地点(2ページ分)で、ページ送りにより表示地点が切り替わり、北海道地点も含まれる', async ({ page }) => {
    // フォント拡大 (YouTube配信での視認性向上) に伴い1ページの表示件数は6件
    const items = [];
    for (let i = 0; i < 6; i++) {
      items.push(weatherPoint({ id: `p${i}`, point_name: `地点${i}`, display_order: (i + 1) * 10 }));
    }
    items.push(weatherPoint({ id: 'hokkaido_wakkanai', pref_code: '01', pref_name: '北海道', point_name: '稚内', display_order: 530 }));
    await mockAllLiveApis(page, { weather: weatherResponse({ items }) });
    await gotoAndCapturePageErrors(page, streamUrl());

    await expect(page.locator('[data-testid="live-stream-weather-point"]')).toHaveCount(6);
    const firstPageIds = await page.locator('[data-testid="live-stream-weather-point"]').evaluateAll(
      els => els.map(el => el.dataset.pointId)
    );
    expect(firstPageIds).not.toContain('hokkaido_wakkanai');

    // weatherSpeed=test によりページ送り間隔は300ms
    await page.waitForFunction(() => {
      const els = document.querySelectorAll('[data-testid="live-stream-weather-point"]');
      return Array.from(els).some(el => el.dataset.pointId === 'hokkaido_wakkanai');
    }, null, { timeout: 5000 });

    const secondPageIds = await page.locator('[data-testid="live-stream-weather-point"]').evaluateAll(
      els => els.map(el => el.dataset.pointId)
    );
    expect(secondPageIds).toContain('hokkaido_wakkanai');
  });

  test('7: stale時に「更新遅延」が表示され、データは誤って消えない', async ({ page }) => {
    await mockAllLiveApis(page, {
      weather: weatherResponse({ cacheStatus: 'stale', forecastTime: '2026-07-03T22:00:00+09:00', fetchedAt: '2026-07-03T22:10:00+09:00' }),
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl());
    await expect(page.locator('[data-testid="live-stream-weather-meta"]')).toContainText('更新遅延');
    await expect(page.locator('[data-testid="live-stream-weather-point"]')).toHaveCount(1);
    expect(errors).toEqual([]);
  });

  test('8: unavailable時に「更新停止中」が表示され、「天気なし」と誤表示しない', async ({ page }) => {
    await mockAllLiveApis(page, {
      weather: {
        status: 'unavailable', source: 'Open-Meteo Forecast',
        forecast_time: null, fetched_at: '2026-07-03T21:40:00+09:00',
        cache_status: 'unavailable', items: [],
      },
    });
    const errors = await gotoAndCapturePageErrors(page, streamUrl());
    const meta = page.locator('[data-testid="live-stream-weather-meta"]');
    await expect(meta).toContainText('更新停止中');
    await expect(meta).toContainText('21:40取得');
    await expect(page.locator('[data-testid="live-stream-weather-unavailable"]')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('9: /live/stream の既存パネル（鉄道・潮位）が破壊されていない', async ({ page }) => {
    await mockAllLiveApis(page);
    const errors = await gotoAndCapturePageErrors(page, streamUrl());
    await expect(page.locator('[data-testid="live-stream-panel-rail"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-panel-tide"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-panel-earthquake"]')).toBeVisible();
    await expect(page.locator('[data-testid="live-stream-panel-rain"]')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('10: frontend が Open-Meteo を直接叩いていない', async ({ page }) => {
    await mockAllLiveApis(page);
    let directCallSeen = false;
    await page.route('**api.open-meteo.com**', route => { directCallSeen = true; route.abort(); });
    await gotoAndCapturePageErrors(page, streamUrl());
    await page.waitForTimeout(500);
    expect(directCallSeen).toBe(false);
  });

  test('11: /live は影響を受けない', async ({ page }) => {
    const errors = await gotoAndCapturePageErrors(page, `${DOCKER_BASE}/live`);
    expect(errors).toEqual([]);
  });
});
