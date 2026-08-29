/**
 * attribution.spec.js — 第三者データ出典表示 E2E（Phase 2-D Round 2、P2D-UI-ATTRIBUTION）
 *
 * 対応する指示書: tasks/public-release/phase2d_claude_remediation_instruction_round2.md 第6節・13.3節5
 *
 * backend 不要。静的 HTML + 実際のLeaflet地図初期化を確認する
 * （CDN経由のLeaflet自体は実ネットワーク取得、他のsmoke.spec.js等と同じ前提）。
 */

'use strict';

const { test, expect } = require('@playwright/test');

test.describe('UI attribution: `/` トップ画面', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('/api/**', route => route.fulfill({ status: 200, body: '{}' }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.goto('/');
    await page.waitForSelector('.leaflet-control-attribution', { timeout: 10000 });
  });

  test('地図の恒常的attribution controlにOSM/ODbLと第三者データ出典が表示される', async ({ page }) => {
    const text = await page.locator('.leaflet-control-attribution').innerText();
    expect(text).toContain('OpenStreetMap');
    expect(text).toContain('ODbL');
    expect(text).toContain('国土数値情報');
    expect(text).toContain('国土地理院');
    expect(text).toContain('気象庁');
  });

  test('attribution controlはCSSで不可視化されていない', async ({ page }) => {
    const control = page.locator('.leaflet-control-attribution');
    await expect(control).toBeVisible();
  });

  test('JARTIC道路交通量レイヤーON中は必須免責文言が表示され、OFFで消える', async ({ page }) => {
    const hasFn = await page.evaluate(() => typeof window.showJarticTrafficLayer === 'function');
    test.skip(!hasFn, 'showJarticTrafficLayer が未定義（読み込み順序の変更等を検知したら要調査）');

    await page.evaluate(() => window.showJarticTrafficLayer());
    await expect(page.locator('.leaflet-control-attribution')).toContainText(
      'このサービスは、交通量API機能を使用していますが、サービスの内容は国土交通省によって保証されたものではありません。'
    );

    await page.evaluate(() => window.hideJarticTrafficLayer());
    await expect(page.locator('.leaflet-control-attribution')).not.toContainText(
      '交通量API機能を使用していますが'
    );
  });

  test('行政区域境界レイヤーを表示すると国土数値情報の加工表示が追加される', async ({ page }) => {
    const hasFns = await page.evaluate(
      () => typeof window.loadBoundaryLayer === 'function' && typeof window.showBoundaryLayer === 'function'
    );
    test.skip(!hasFns, 'boundary layer 関数が未定義');

    await page.evaluate(async () => {
      await window.loadBoundaryLayer('tokyo');
      window.showBoundaryLayer('tokyo');
    });
    await expect(page.locator('.leaflet-control-attribution')).toContainText(
      '国土交通省 国土数値情報（行政区域データ）を加工して作成'
    );
  });
});

test.describe('UI attribution: `/live`', () => {
  test('地図の恒常的attribution controlに基本出典が表示される', async ({ page }) => {
    await page.goto('/live');
    await page.waitForSelector('.leaflet-control-attribution', { timeout: 10000 });
    const text = await page.locator('.leaflet-control-attribution').innerText();
    expect(text).toContain('OSM');
    expect(text).toContain('ODbL');
    expect(text).toContain('国土数値情報');
  });
});

test.describe('UI attribution: `/live/stream`', () => {
  // /live/stream は実backend（Docker Compose、http://127.0.0.1:8080）を前提とする画面であり、
  // 他の /live/stream 系spec（例: live-stream-main-map.spec.js）と同じ規約に従う。
  // 既定の静的file-server harness（baseURL 8787）にはbackendがないため対象外とする。
  const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';

  test('地図の恒常的attribution controlに基本出典が表示される', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&chrome=off`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-control-attribution', { timeout: 15000 });
    const text = await page.locator('.leaflet-control-attribution').first().innerText();
    expect(text).toContain('OpenStreetMap');
    expect(text).toContain('国土数値情報');
  });
});
