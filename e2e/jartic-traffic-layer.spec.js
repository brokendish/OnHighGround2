'use strict';
/**
 * jartic-traffic-layer.spec.js — 交通量観測点レイヤー MVP 確認
 *
 * OnHighGround2 本体（index.html）に追加した交通量観測点レイヤーを検証。
 * backend は不要 — API はすべてモックで受ける。
 */

const { test, expect } = require('@playwright/test');

// ── サンプルデータ ────────────────────────────────────────────────────────────

const JARTIC_OK = {
    status: 'ok',
    source: 'JARTIC / 国土交通省交通量API',
    updated_at: '2026-06-29T10:00:00+09:00',
    items: [
        {
            code: 'T001',
            lat: 35.6812,
            lon: 139.7671,
            up: 320,
            down: 280,
            total: 600,
            small: 520,
            large: 80,
            observed_at: '2026-06-29T09:55:00+09:00',
            unit: '5min',
            type: '一般国道',
        },
        {
            code: 'T002',
            lat: 35.6503,
            lon: 139.6941,
            up: 0,
            down: 0,
            total: 0,
            small: 0,
            large: 0,
            observed_at: '2026-06-29T09:55:00+09:00',
            unit: '5min',
            type: null,
        },
    ],
};

const JARTIC_UNAVAILABLE = {
    status: 'unavailable',
    source: 'JARTIC / 国土交通省交通量API',
    updated_at: null,
    items: [],
    message: '交通量観測点データを取得できません',
};

const JARTIC_EMPTY = {
    status: 'ok',
    source: 'JARTIC / 国土交通省交通量API',
    updated_at: '2026-06-29T10:00:00+09:00',
    items: [],
};

// BBOX 外アイテム（lat=40, lon=145 は bbox に含まれない想定）
const JARTIC_BBOX_FILTERED = {
    status: 'ok',
    source: 'JARTIC / 国土交通省交通量API',
    updated_at: '2026-06-29T10:00:00+09:00',
    items: [],
};

// ── 共通モック設定 ────────────────────────────────────────────────────────────

async function setupBaseMocks(page, jarticFactory = () => JARTIC_OK) {
    await page.route('/favicon.ico', r => r.fulfill({ status: 204, body: '' }));

    // 主要 API をすべて空/成功で受ける
    await page.route('/api/**', r => {
        const url = r.request().url();
        if (url.includes('/stream')) {
            return r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 10000\n\n' });
        }
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });

    // 地震・津波・気象系
    await page.route('/api/earthquakes**', r => {
        const url = r.request().url();
        if (url.includes('/stream')) return r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 10000\n\n' });
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, items: [] }) });
    });
    await page.route('/api/admin/config**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ config: [] }) }));
    await page.route('/api/elevation**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ elevation: 5 }) }));

    // 交通量観測点 API
    await page.route('/api/jartic/traffic**', r => {
        const body = jarticFactory(r.request().url());
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });

    // タイル・地図画像
    const TRANSPARENT_PNG = Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
        'base64',
    );
    await page.route('**/basemaps.cartocdn.com/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/openstreetmap.org/**', r =>
        r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
}

async function gotoIndex(page) {
    await page.goto('/');
    await page.waitForSelector('#map', { timeout: 10000 });
}

async function openLayerPanel(page) {
    const layerBtn = page.locator('#layer-toggle-btn');
    if (await layerBtn.count() > 0) await layerBtn.click();
}

async function setJarticTrafficToggle(page, checked) {
    await page.evaluate(nextChecked => {
        const toggle = document.querySelector('#jartic-traffic-toggle');
        if (!toggle) throw new Error('jartic traffic toggle not found');
        toggle.checked = nextChecked;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
        if (nextChecked && typeof window.showJarticTrafficLayer === 'function') {
            window.showJarticTrafficLayer();
        }
        if (!nextChecked && typeof window.hideJarticTrafficLayer === 'function') {
            window.hideJarticTrafficLayer();
        }
    }, checked);
    const toggle = page.locator('#jartic-traffic-toggle');
    await expect(toggle).toBeAttached();
    expect(await toggle.isChecked()).toBe(checked);
}

async function openFirstJarticPopup(page) {
    await page.waitForSelector('.jartic-traffic-marker', { state: 'attached', timeout: 5000 });
    await page.evaluate(() => {
        const marker = document.querySelector('.jartic-traffic-marker');
        if (!marker) throw new Error('jartic traffic marker not found');
        marker.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    });
}

// ── テスト ────────────────────────────────────────────────────────────────────

test('交通量観測点トグルがレイヤーパネルに存在する', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    // レイヤーパネルを開く
    await openLayerPanel(page);

    const toggle = page.locator('#jartic-traffic-toggle');
    await expect(toggle).toBeAttached();
});

test('交通量観測点トグルの初期状態は OFF', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);

    const toggle = page.locator('#jartic-traffic-toggle');
    await expect(toggle).not.toBeChecked();
});

test('トグル ON で /api/jartic/traffic が呼ばれる', async ({ page }) => {
    let called = false;
    await setupBaseMocks(page, url => { called = true; return JARTIC_OK; });
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    expect(called).toBe(true);
});

test('トグル ON で bbox パラメータ付きリクエストが送られる', async ({ page }) => {
    let capturedUrl = '';
    await setupBaseMocks(page, url => { capturedUrl = url; return JARTIC_OK; });
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    expect(capturedUrl).toContain('bbox=');
});

test('トグル OFF でマーカーが消える（レイヤーが地図から除去される）', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(300);

    await setJarticTrafficToggle(page, false);
    await page.waitForTimeout(300);

    // isJarticTrafficLayerVisible() が false になっている
    const visible = await page.evaluate(() =>
        typeof window.isJarticTrafficLayerVisible === 'function'
            ? window.isJarticTrafficLayerVisible()
            : false
    );
    expect(visible).toBe(false);
});

test('マーカーポップアップに「交通量観測点」が含まれる', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await openFirstJarticPopup(page);

    await expect(page.locator('.jt-popup-title')).toHaveText('交通量観測点');
});

test('上り・下り・合計・小型・大型・観測時刻・観測点コード・出典が popup に含まれる', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await openFirstJarticPopup(page);

    const popup = page.locator('.jt-popup');
    await expect(popup).toContainText('上り');
    await expect(popup).toContainText('320台');
    await expect(popup).toContainText('下り');
    await expect(popup).toContainText('280台');
    await expect(popup).toContainText('合計');
    await expect(popup).toContainText('600台');
    await expect(popup).toContainText('小型');
    await expect(popup).toContainText('520台');
    await expect(popup).toContainText('大型');
    await expect(popup).toContainText('80台');
    await expect(popup).toContainText('観測時刻');
    await expect(popup).toContainText('2026-06-29');
    await expect(popup).toContainText('観測点コード');
    await expect(popup).toContainText('T001');
    await expect(popup).toContainText('出典: JARTIC / 国土交通省交通量API');
});

test('status=unavailable のとき API 呼び出しはされるがマーカーは表示されない', async ({ page }) => {
    await setupBaseMocks(page, () => JARTIC_UNAVAILABLE);
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    // マーカーが 0 件（SVG circle が存在しない、または leaflet-pane が空）
    const markerCount = await page.evaluate(() =>
        document.querySelectorAll('.jartic-traffic-marker').length
    );
    // unavailable 時は 0 件
    expect(markerCount).toBe(0);
});

test('items=[] のとき（BBOX外または観測点なし）マーカーは 0 件', async ({ page }) => {
    await setupBaseMocks(page, () => JARTIC_EMPTY);
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    const markerCount = await page.evaluate(() =>
        document.querySelectorAll('.jartic-traffic-marker').length
    );
    expect(markerCount).toBe(0);
});

test('/live 側に 交通量観測点トグルが存在しない', async ({ page }) => {
    await page.route('/favicon.ico', r => r.fulfill({ status: 204 }));
    await page.route('/api/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    const TRANSPARENT_PNG = Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
        'base64',
    );
    await page.route('**/*.png', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));

    await page.goto('/live.html');
    await page.waitForTimeout(1000);

    const toggle = page.locator('#jartic-traffic-toggle');
    await expect(toggle).not.toBeAttached();
});

test('0台（up=0, down=0）の観測点もマーカーとして描画される', async ({ page }) => {
    const data = {
        ...JARTIC_OK,
        items: [{ code: 'Z001', lat: 35.68, lon: 139.77, up: 0, down: 0, total: 0, small: 0, large: 0, observed_at: '2026-06-29T09:55:00+09:00', unit: null, type: null }],
    };
    await setupBaseMocks(page, () => data);
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    const markerCount = await page.evaluate(() =>
        document.querySelectorAll('.jartic-traffic-marker').length
    );
    // 0台でも描画される（欠損ではない）
    expect(markerCount).toBeGreaterThanOrEqual(1);
});

test('ポップアップに「渋滞」「混雑」「規制」「通行止め」等の禁止文言が含まれない', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await openFirstJarticPopup(page);

    const popupText = await page.locator('.jt-popup').textContent();
    const badWords = ['渋滞', '混雑', '規制', '通行止め', '事故'];
    for (const w of badWords) {
        expect(popupText).not.toContain(w);
    }
});
