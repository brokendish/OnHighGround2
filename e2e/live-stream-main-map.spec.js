'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';
const DEMO_1942 = '2026-06-30T19:42:00%2B09:00';

function streamUrl(query) {
  return `${DOCKER_BASE}/live/stream${query}`;
}

async function gotoAndCaptureErrors(page, url) {
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', error => {
    pageErrors.push(error.message || String(error));
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  return { consoleErrors, pageErrors };
}

async function expectNoBrowserErrors(errors) {
  expect(errors.pageErrors, 'page errors').toEqual([]);
  expect(errors.consoleErrors, 'console errors').toEqual([]);
}

test.describe('/live/stream — Stream Phase 3-A 中央メイン地図 本番地図基盤化', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('center map initializes as a Leaflet map', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap).toBeVisible();
    await expect(centerMap).toHaveClass(/leaflet-container/);
    await expect(centerMap.locator('.leaflet-tile-pane img.leaflet-tile-loaded').first()).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('center map shows OSM/CARTO attribution', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    const attribution = page.getByTestId('live-stream-center-map').locator('.leaflet-control-attribution');
    await expect(attribution).toBeVisible();
    await expect(attribution).toContainText('OpenStreetMap');
    await expectNoBrowserErrors(errors);
  });

  test('center map has no operable controls (view-only)', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.locator('.leaflet-control-zoom')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });

  test('demo=1 alert view shows earthquake and rain pulses on the production map', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=alert&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap.getByTestId('live-stream-pulse-earthquake')).toBeVisible();
    await expect(centerMap.getByTestId('live-stream-pulse-rain')).toBeVisible();
    await expectNoBrowserErrors(errors);
  });

  test('state=calm shows the production map with no warning pulses', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(
      page,
      streamUrl(`?state=calm&demo=1&chrome=off&demoNow=${DEMO_1942}`),
    );

    const centerMap = page.getByTestId('live-stream-center-map');
    await expect(centerMap).toHaveClass(/leaflet-container/);
    await expect(centerMap.getByTestId('live-stream-pulse-earthquake')).toHaveCount(0);
    await expect(centerMap.getByTestId('live-stream-pulse-rain')).toHaveCount(0);
    await expect(centerMap.getByTestId('live-stream-pulse-tide')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });

  test('/live regression: normal Leaflet map unaffected by stream map view', async ({ page }) => {
    const errors = await gotoAndCaptureErrors(page, `${DOCKER_BASE}/live`);

    await expect(page.locator('#live-map')).toBeVisible();
    await expect(page.locator('.ls-stage')).toHaveCount(0);
    await expectNoBrowserErrors(errors);
  });
});
