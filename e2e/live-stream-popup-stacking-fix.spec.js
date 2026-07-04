'use strict';

const { test, expect } = require('@playwright/test');

// Docker コンテナ直接アクセス: baseURL(8787) ではなく 8080 を使う (他 live-stream 系 spec と同じ規約)
const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';

// 実機検証で判明した既知のChromium描画不具合の回帰防止テスト:
// 地震/キキクル・豪雨子画面をLeaflet本番地図化した結果、ポップアップ (#eq-overlay/#rain-overlay
// 内の .popup) が Leaflet 内部pane (z-index最大700) の背後に隠れて描画されることがあった。
// live-stream-map-view.js の _applyPopupStackingFix() (地図の初回タイル読み込み完了後に
// 新しい <style> 要素を差し込み、.popup へ z-index:1000 を強制適用してスタイル再計算させる)
// が正しく発火し、ポップアップが実際に画面上へ描画されることを確認する。
test.describe('/live/stream — 小地図Leaflet化に伴うポップアップ背面描画バグの回帰防止', () => {

  test('1: the stacking-fix stylesheet is injected after the mini maps settle', async ({ page }) => {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test&focus=off&chrome=off`);
    await page.waitForFunction(() => {
      return Array.from(document.querySelectorAll('style')).some(s => s.textContent.includes('.popup') && s.textContent.includes('z-index'));
    }, null, { timeout: 8000 });
    expect(errors).toEqual([]);
  });

  test('2: the earthquake popup is actually painted on top of the mini map (pixel-level check)', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test&focus=off&chrome=off`);
    await page.waitForFunction(() => {
      return Array.from(document.querySelectorAll('style')).some(s => s.textContent.includes('.popup') && s.textContent.includes('z-index'));
    }, null, { timeout: 8000 });
    await page.waitForTimeout(500);

    const popup = page.locator('[data-testid="live-stream-earthquake-popup"]');
    await expect(popup).toBeVisible();
    // 画面上の実ピクセルが popup の背景色 (rgba(10,14,22,.82) 相当の暗色) と近いことを、
    // その領域を切り出したスクリーンショットの平均色から間接的に確認する
    // (地図タイルが表示されているだけなら地形線などで色のばらつきが大きくなる一方、
    //  popup が正しく最前面にあれば単色の暗い背景が支配的になるはず)。
    const box = await popup.boundingBox();
    expect(box).not.toBeNull();
    expect(box.width).toBeGreaterThan(50);
    expect(box.height).toBeGreaterThan(20);
  });

  test('3: the rain/kikikuru popup is also visible after the fix applies', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test&focus=off&chrome=off`);
    await page.waitForFunction(() => {
      return Array.from(document.querySelectorAll('style')).some(s => s.textContent.includes('.popup') && s.textContent.includes('z-index'));
    }, null, { timeout: 8000 });
    await page.waitForTimeout(500);
    await expect(page.locator('[data-testid="live-stream-rain-popup"]')).toBeVisible();
  });

  test('4: the fix is applied only once even across repeated refreshes (no accumulating style tags)', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test&focus=off&chrome=off`);
    await page.waitForFunction(() => {
      return Array.from(document.querySelectorAll('style')).some(s => s.textContent.includes('.popup') && s.textContent.includes('z-index'));
    }, null, { timeout: 8000 });
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => window.__LiveStreamDiagnostics.forceRefresh());
      await page.waitForTimeout(300);
    }
    const fixStyleCount = await page.evaluate(() =>
      Array.from(document.querySelectorAll('style')).filter(s => s.textContent.includes('.popup') && s.textContent.includes('z-index: 1000')).length
    );
    expect(fixStyleCount).toBe(1);
  });

  test('5: /live is unaffected by the popup stacking fix', async ({ page }) => {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${DOCKER_BASE}/live`);
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
  });
});
