'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';

test.describe('/live/stream — 各小画面ヘッダの情報提供元バッジ', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('1: earthquake panel shows the JMA/P2P source badge', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&chrome=off`, { waitUntil: 'domcontentloaded' });
    const badge = page.getByTestId('live-stream-source-badge-earthquake');
    await expect(badge).toBeVisible();
    expect(await badge.textContent()).toContain('JMA');
  });

  test('2: rain/kikikuru panel shows the JMA kikikuru/nowcast source badge', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&chrome=off`, { waitUntil: 'domcontentloaded' });
    const badge = page.getByTestId('live-stream-source-badge-rain');
    await expect(badge).toBeVisible();
    expect(await badge.textContent()).toContain('JMA');
  });

  test('3: railway panel shows the ODPT source badge and the "ODPT-covered lines only" caveat', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&chrome=off`, { waitUntil: 'domcontentloaded' });
    const badge = page.getByTestId('live-stream-source-badge-railway');
    await expect(badge).toBeVisible();
    expect(await badge.textContent()).toContain('ODPT');
    const note = page.getByTestId('live-stream-source-note-railway');
    await expect(note).toBeVisible();
    expect(await note.textContent()).toContain('ODPT対応路線');
  });

  test('4: tide panel shows the JMA tide observation source badge', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&chrome=off`, { waitUntil: 'domcontentloaded' });
    const badge = page.getByTestId('live-stream-source-badge-tide');
    await expect(badge).toBeVisible();
    expect(await badge.textContent()).toContain('JMA');
  });

  test('5: source badges do not overlap the win-meta (right side header info)', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&chrome=off`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    const panelTestIds = {
      earthquake: 'live-stream-panel-earthquake',
      rain:       'live-stream-panel-rain',
      railway:    'live-stream-panel-rail',
      tide:       'live-stream-panel-tide',
    };
    for (const panel of Object.keys(panelTestIds)) {
      const badge = page.getByTestId(`live-stream-source-badge-${panel}`);
      const meta = page.locator(`[data-testid="${panelTestIds[panel]}"] .win-meta`);
      const badgeBox = await badge.boundingBox();
      const metaBox = await meta.boundingBox();
      expect(badgeBox).not.toBeNull();
      expect(metaBox).not.toBeNull();
      // バッジの右端がメタ情報の左端より内側 (重なっていない) こと
      expect(badgeBox.x + badgeBox.width).toBeLessThanOrEqual(metaBox.x + 1);
    }
  });

  test('6: source badges are present in real (non-demo) mode too', async ({ page }) => {
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [] } }) }));
    await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));
    await page.goto(`${DOCKER_BASE}/live/stream?chrome=off`, { waitUntil: 'domcontentloaded' });
    for (const panel of ['earthquake', 'rain', 'railway', 'tide']) {
      await expect(page.getByTestId(`live-stream-source-badge-${panel}`)).toBeVisible();
    }
  });

  test('7: state=calm still shows the source badges', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?state=calm&chrome=off`, { waitUntil: 'domcontentloaded' });
    for (const panel of ['earthquake', 'rain', 'railway', 'tide']) {
      await expect(page.getByTestId(`live-stream-source-badge-${panel}`)).toBeVisible();
    }
  });

  test('8: /live is unaffected by the source badge addition', async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(e.message || String(e)));
    await page.goto(`${DOCKER_BASE}/live`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(800);
    expect(pageErrors).toEqual([]);
    await expect(page.locator('.win-src')).toHaveCount(0);
  });
});
