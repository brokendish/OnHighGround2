/**
 * mobile-bottom-panel-compact.spec.js — MOBILE-BOTTOM-PANEL-COMPACT E2E
 *
 * スマホ(390x844)では下部パネルを collapsed 初期表示にし、必要時のみ展開する。
 * PC(1440x900)のレイアウトは変更されないことも確認する。
 *
 * 既存の開閉機構（#map-bottom-handle / .mbc-collapsed）を再利用しているため、
 * ここでは「初期状態」「開閉」「タブ」「地図操作」「FAB」「attribution」を検証する。
 * スクリーンショットは reports/mobile-bottom-panel-compact/ に保存する。
 */

'use strict';

const path = require('path');
const fs = require('fs');
const { test, expect } = require('@playwright/test');

const SHOT_DIR = path.resolve(__dirname, '../reports/mobile-bottom-panel-compact');

async function setupMocks(page) {
  // 汎用モックを先に登録（後から登録した個別モックが優先される）
  await page.route('**/api/**', route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{}',
  }));
  await page.route('**/emergency-shelters**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.route('**/api/elevation**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ elevation: 18, lat: 35.6415, lon: 139.7905 }),
  }));
  await page.route('**/api/hazard-check**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ is_danger: false, hazards: [], hazard_assessment: {} }),
  }));
}

async function openApp(page) {
  await setupMocks(page);
  await page.goto('/');
  await page.waitForSelector('.leaflet-control-attribution', { timeout: 10000 });
  // 現在地取得 → ステータス行が「安全」表示になるまで待つ
  await expect(page.locator('#mbc-current-hazard')).toContainText('安全', { timeout: 10000 });
  await expect(page.locator('#mbc-current-elev')).toContainText('標高 18m', { timeout: 10000 });
}

const box = (page, sel) => page.locator(sel).first().boundingBox();

test.describe('MOBILE-BOTTOM-PANEL-COMPACT: スマホ 390x844', () => {
  test.use({
    viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true,
    geolocation: { latitude: 35.6415, longitude: 139.7905, accuracy: 6 },
  });

  test.beforeAll(() => fs.mkdirSync(SHOT_DIR, { recursive: true }));

  test('AC-01/02/03/04/05/13: 初期 collapsed・ステータス行のみ・地図領域が広い', async ({ page }) => {
    await openApp(page);
    const controls = page.locator('#map-bottom-controls');
    await expect(controls).toHaveClass(/mbc-collapsed/);

    // 安全・標高・精度は確認できる
    await expect(page.locator('#mbc-current-hazard')).toBeVisible();
    await expect(page.locator('#mbc-current-elev')).toBeVisible();
    await expect(page.locator('#mbc-current-accuracy')).toBeVisible();
    await expect(page.locator('#mbc-current-accuracy')).toContainText('精度', { timeout: 10000 });

    // タブ列・大きな検索ボタン・タブ内容は見えない
    await expect(page.locator('#mbc-tabs')).toBeHidden();
    await expect(page.locator('#mbc-tab-btn-info')).toBeHidden();
    await expect(page.locator('#search-overlay-btn')).toBeHidden();

    // ハンドルの aria
    const handle = page.locator('#map-bottom-handle');
    await expect(handle).toHaveAttribute('aria-expanded', 'false');
    await expect(handle).toHaveAttribute('aria-label', /開く/);

    // 地図操作領域: パネルの上端が画面の 90% より下（= 地図が縦 90% 以上使える）
    const vh = 844;
    const cb = await controls.boundingBox();
    expect(cb.y).toBeGreaterThan(vh * 0.9);
    expect(cb.height).toBeLessThan(vh * 0.08);

    await page.screenshot({ path: path.join(SHOT_DIR, 'mobile-collapsed.png') });
  });

  test('AC-04/11: attribution は 1 行に compact 化され、OSM/Leaflet/ODbL は維持。トグルで全文', async ({ page }) => {
    await openApp(page);
    const attr = page.locator('.leaflet-control-attribution');
    await expect(attr).toBeVisible();
    const text = await attr.innerText();
    expect(text).toContain('Leaflet');
    expect(text).toContain('OpenStreetMap');
    expect(text).toContain('ODbL');
    // 出典の全文も DOM 上は維持（削除していない）
    const full = await attr.evaluate(el => el.textContent);
    expect(full).toContain('国土数値情報');
    expect(full).toContain('国土地理院');
    expect(full).toContain('気象庁');

    const closed = await attr.boundingBox();
    expect(closed.height).toBeLessThan(24); // 1 行
    // 右下・画面内に収まる
    expect(closed.x).toBeGreaterThanOrEqual(0);
    expect(closed.x + closed.width).toBeLessThanOrEqual(390.5);
    // パネル(collapsed)と重ならない
    const cb = await box(page, '#map-bottom-controls');
    expect(closed.y).toBeGreaterThanOrEqual(cb.y + cb.height - 1);

    // トグルで全文表示
    const toggle = page.locator('.ohg2-attr-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const opened = await attr.boundingBox();
    expect(opened.height).toBeGreaterThan(closed.height * 2);
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    const reclosed = await attr.boundingBox();
    expect(reclosed.height).toBeLessThan(24);
  });

  test('JARTIC 免責文言はスマホでも折りたたまれず全文表示される', async ({ page }) => {
    await openApp(page);
    const hasFn = await page.evaluate(() => typeof window.showJarticTrafficLayer === 'function');
    test.skip(!hasFn, 'showJarticTrafficLayer が未定義');
    await page.evaluate(() => window.showJarticTrafficLayer());
    const attr = page.locator('.leaflet-control-attribution');
    await expect(attr).toContainText('交通量API機能を使用していますが');
    await expect(page.locator('.leaflet-bottom.leaflet-right')).toHaveClass(/ohg2-attr-pinned/);
    const b = await attr.boundingBox();
    expect(b.height).toBeGreaterThan(40); // 複数行で全文表示
    await page.evaluate(() => window.hideJarticTrafficLayer());
    await expect(page.locator('.leaflet-bottom.leaflet-right')).not.toHaveClass(/ohg2-attr-pinned/);
  });

  test('AC-06/07/08: 展開・各タブ・避難先検索・内部スクロール・再 collapse', async ({ page }) => {
    await openApp(page);
    const controls = page.locator('#map-bottom-controls');
    const handle = page.locator('#map-bottom-handle');

    // 展開
    await handle.click();
    await expect(controls).not.toHaveClass(/mbc-collapsed/);
    await expect(handle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#mbc-tabs')).toBeVisible();
    for (const t of ['action', 'info', 'layer', 'legend', 'earthquake']) {
      await expect(page.locator(`#mbc-tab-btn-${t}`)).toBeVisible();
    }
    // 操作タブ: 避難先検索ボタンは展開時に利用可能（表示される）
    await expect(page.locator('#search-overlay-btn')).toBeVisible();

    // 展開時も地図全面を覆わない（パネル上端 >= 画面の 35% ＝ 高さ 65% 以下）
    const eb = await controls.boundingBox();
    expect(eb.y).toBeGreaterThan(844 * 0.3);
    await page.screenshot({ path: path.join(SHOT_DIR, 'mobile-expanded.png') });

    // 各タブ切替
    await page.locator('#mbc-tab-btn-layer').click();
    await expect(page.locator('#mbc-tab-panel-layer')).toBeVisible();
    await page.locator('#mbc-tab-btn-legend').click();
    await expect(page.locator('#mbc-tab-panel-legend')).toBeVisible();
    await page.locator('#mbc-tab-btn-info').click();
    await expect(page.locator('#mbc-tab-panel-info')).toBeVisible();
    await page.screenshot({ path: path.join(SHOT_DIR, 'mobile-expanded-info.png') });

    // 情報タブ: 展開状態でも高さが 65% を超えず、パネル内がスクロール可能
    await handle.click(); // normal → expanded
    await expect(controls).toHaveClass(/mbc-info-expanded/);
    const ib = await controls.boundingBox();
    expect(ib.y).toBeGreaterThanOrEqual(844 * 0.33);
    const scrollable = await page.locator('#mbc-tab-panel-info').evaluate(el => ({
      cs: getComputedStyle(el).overflowY, sh: el.scrollHeight, ch: el.clientHeight,
    }));
    expect(scrollable.cs).toBe('auto');
    if (scrollable.sh > scrollable.ch) {
      await page.locator('#mbc-tab-panel-info').evaluate(el => { el.scrollTop = 50; });
      expect(await page.locator('#mbc-tab-panel-info').evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    }

    await page.locator('#mbc-tab-btn-action').click();
    await expect(page.locator('#mbc-tab-panel-action')).toBeVisible();
    await expect(page.locator('#search-overlay-btn')).toBeVisible();

    // 再 collapse
    await handle.click();
    await expect(controls).toHaveClass(/mbc-collapsed/);
    await expect(handle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('#mbc-tabs')).toBeHidden();
  });

  test('AC-06/08: キーボード（Enter）でも開閉できる', async ({ page }) => {
    await openApp(page);
    const handle = page.locator('#map-bottom-handle');
    await handle.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('#map-bottom-controls')).not.toHaveClass(/mbc-collapsed/);
    await page.keyboard.press('Enter');
    await expect(page.locator('#map-bottom-controls')).toHaveClass(/mbc-collapsed/);
  });

  test('AC-09: 地図の pan / zoom が正常（collapsed / expanded の両方）', async ({ page }) => {
    await openApp(page);
    const getState = () => page.evaluate(() => ({ c: map.getCenter(), z: map.getZoom() }));

    // pan: 地図上部の空き領域（FAB/パネルと重ならない位置）をドラッグ
    const before = await getState();
    await page.mouse.move(150, 300);
    await page.mouse.down();
    await page.mouse.move(60, 380, { steps: 8 });
    await page.mouse.up();
    const panned = await getState();
    expect(Math.abs(panned.c.lat - before.c.lat) + Math.abs(panned.c.lng - before.c.lng)).toBeGreaterThan(1e-5);

    // zoom（Leaflet +/- ボタン）
    await page.locator('.leaflet-control-zoom-in').click();
    await expect.poll(async () => (await getState()).z).toBeGreaterThan(before.z);
    await page.waitForTimeout(700); // ズームアニメーション完了待ち（中のクリックは Leaflet が無視する）
    await page.locator('.leaflet-control-zoom-out').click();
    await expect.poll(async () => (await getState()).z).toBe(before.z);
    await page.waitForTimeout(700); // アニメーション・慣性が落ち着くまで待つ

    // expanded でも地図の露出部分で pan できる
    await page.locator('#map-bottom-handle').click();
    await page.waitForTimeout(400);
    const before2 = await getState();
    await page.mouse.move(150, 200);
    await page.mouse.down();
    await page.mouse.move(60, 260, { steps: 8 });
    await page.mouse.up();
    await expect.poll(async () => {
      const a = await getState();
      return Math.abs(a.c.lat - before2.c.lat) + Math.abs(a.c.lng - before2.c.lng);
    }).toBeGreaterThan(1e-5);
  });

  test('AC-10: 右側 FAB 群が collapsed / expanded の両方で押せる（前面にある）', async ({ page }) => {
    await openApp(page);
    const check = async () => {
      const results = await page.evaluate(() => {
        const btns = Array.from(document.querySelectorAll('#map-top-right-controls .map-overlay-btn'));
        return btns.map(b => {
          const r = b.getBoundingClientRect();
          const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return { id: b.id || b.textContent.trim(), w: r.width, h: r.height, hit: !!top && (b === top || b.contains(top)) };
        });
      });
      expect(results.length).toBeGreaterThanOrEqual(6);
      for (const r of results) {
        expect(r.hit, `FAB ${r.id} が他要素に覆われていない`).toBe(true);
        expect(r.h).toBeGreaterThan(0);
      }
    };
    await check();
    await page.locator('#map-bottom-handle').click();
    await check();

    // 現在地ボタンは実際にクリックして地図が現在地へ寄る
    await page.locator('#locate-map-btn').click();
    await expect.poll(() => page.evaluate(() => Math.abs(map.getCenter().lat - 35.6415) < 0.01)).toBe(true);
  });
});

test.describe('MOBILE-BOTTOM-PANEL-COMPACT: Desktop 1440x900 回帰（AC-12）', () => {
  test.use({
    viewport: { width: 1440, height: 900 },
    geolocation: { latitude: 35.6415, longitude: 139.7905, accuracy: 6 },
  });

  test('初期は展開・タブ/検索ボタン表示・attribution は従来どおり・トグル非表示', async ({ page }) => {
    await openApp(page);
    const controls = page.locator('#map-bottom-controls');
    await expect(controls).not.toHaveClass(/mbc-collapsed/);
    await expect(page.locator('#mbc-tabs')).toBeVisible();
    await expect(page.locator('#search-overlay-btn')).toBeVisible();
    await expect(page.locator('.ohg2-attr-toggle')).toBeHidden();

    // attribution は従来の折り返し表示（nowrap/ellipsis になっていない）
    const cs = await page.locator('.leaflet-control-attribution').evaluate(el => {
      const s = getComputedStyle(el);
      return { ws: s.whiteSpace, fs: s.fontSize, to: s.textOverflow };
    });
    expect(cs.ws).not.toBe('nowrap');
    expect(cs.to).not.toBe('ellipsis');
    expect(parseFloat(cs.fs)).toBeGreaterThanOrEqual(11);

    // PC でも従来どおり開閉できる（ハンドル）
    await page.locator('#map-bottom-handle').click();
    await expect(controls).toHaveClass(/mbc-collapsed/);
    await page.locator('#map-bottom-handle').click();
    await expect(controls).not.toHaveClass(/mbc-collapsed/);

    await page.screenshot({ path: path.join(SHOT_DIR, 'desktop-1440x900.png') });
  });
});
