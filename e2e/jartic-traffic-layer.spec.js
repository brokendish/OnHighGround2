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
            // 上り=320/下り=280 は /live の classify_volume ではともに very_high
            status: 'very_high',
            status_label: '交通量非常に多い',
            status_up: 'very_high',
            status_up_label: '交通量非常に多い',
            status_down: 'very_high',
            status_down_label: '交通量非常に多い',
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
            // 0台は欠損ではなく very_low（/live の classify_volume: v<=3）
            status: 'very_low',
            status_label: '交通量極端に少ない',
            status_up: 'very_low',
            status_up_label: '交通量極端に少ない',
            status_down: 'very_low',
            status_down_label: '交通量極端に少ない',
        },
        {
            code: 'T003',
            lat: 35.70,
            lon: 139.75,
            up: 40,
            down: 5,
            total: 45,
            small: 42,
            large: 3,
            observed_at: '2026-06-29T09:55:00+09:00',
            unit: '5min',
            type: '一般国道',
            // 上り=40 は normal、下り=5 は low → 高い方(low)を採用
            status: 'low',
            status_label: '交通量少ない',
            status_up: 'normal',
            status_up_label: '通常',
            status_down: 'low',
            status_down_label: '交通量少ない',
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

// #layer-toggle-btn / #legend-toggle-btn は現行DOMに存在しない旧セレクタ。
// 実際のレイヤー/凡例パネル開閉は下部タブバー #mbc-tab-btn-layer / #mbc-tab-btn-legend
// （frontend/js/app.js の switchMbcTab）で行われる。
async function openLayerPanel(page) {
    await page.locator('#mbc-tab-btn-layer').click();
    await expect(page.locator('#mbc-tab-panel-layer')).toBeVisible();
}

async function openLegendPanel(page) {
    await page.locator('#mbc-tab-btn-legend').click();
    await expect(page.locator('#mbc-tab-panel-legend')).toBeVisible();
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

test('ポップアップに「渋滞中」「道路が混雑しています」等の断定文言が含まれない', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);

    await setJarticTrafficToggle(page, true);
    await openFirstJarticPopup(page);

    const popupText = await page.locator('.jt-popup').textContent();
    // 「通行止め」「規制」は仕様書で指定された免責文言
    // （"...断定するものではありません" という否定形）の中でのみ許容される。
    // ここでは断定的な禁止表現のみを検査する。
    const badWords = ['渋滞', '混雑', '事故'];
    for (const w of badWords) {
        expect(popupText).not.toContain(w);
    }
    // 免責文言（/live と同一文言）が含まれる
    expect(popupText).toContain('断定するものではありません');
});

// ── Phase 7-B.3: /live 同一の色分け・凡例・低ズーム制御 ─────────────────────────

test('PC: OFF/ON状態のスクリーンショットを保存する', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);
    await openLayerPanel(page);

    await page.screenshot({ path: 'test-results/jartic-traffic-desktop-off.png' });

    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);
    await page.screenshot({ path: 'test-results/jartic-traffic-desktop.png' });

    await expect(page.locator('.jartic-traffic-marker').first()).toBeAttached();
});

test('ラベルは「道路交通量」（省略・改称されていない）', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);
    await openLayerPanel(page);

    const label = page.locator('#jartic-traffic-toggle-label');
    await expect(label).toContainText('道路交通量');
});

// /live 側 live-road-traffic-layer.js _STATUS_COLOR と同一値（false positive防止のため
// クラス名ではなく、実際に描画された背景色（computed style）を検証する）
// Phase 7-B.3.1: マーカーは L.circleMarker(SVG path) から L.divIcon(HTML div) へ変更。
const JT_STATUS_COLOR = {
    very_high: '#dc2626',
    high:      '#d97706',
    normal:    '#22c55e',
    low:       '#1f6feb',
    very_low:  '#7c3aed',
    unknown:   '#9ca3af',
};

// #rrggbb → "rgb(r, g, b)"（getComputedStyleの戻り値形式に合わせる）
function hexToRgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

async function jtMarkerFills(page) {
    return page.evaluate(() =>
        Array.from(document.querySelectorAll('.jartic-traffic-marker')).map(el => ({
            status: (el.getAttribute('class') || '').match(/jartic-traffic-status-(\S+)/)?.[1] || null,
            backgroundColor: getComputedStyle(el).backgroundColor,
        }))
    );
}

test('トグルON時、複数カテゴリの色分けマーカーが実際の背景色で表示される（/live と同一分類）', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    const fills = await jtMarkerFills(page);
    expect(fills.length).toBe(3);

    // クラス名だけでなく、実際に描画された computed background-color が
    // /live と同一の16進色であることを検証する
    for (const { status, backgroundColor } of fills) {
        expect(status).not.toBeNull();
        expect(backgroundColor).toBe(hexToRgb(JT_STATUS_COLOR[status]));
    }

    const distinctColors = new Set(fills.map(f => f.backgroundColor));
    expect(distinctColors.size).toBeGreaterThanOrEqual(3);
    expect(fills.some(f => f.backgroundColor === hexToRgb(JT_STATUS_COLOR.very_high))).toBe(true);
    expect(fills.some(f => f.backgroundColor === hexToRgb(JT_STATUS_COLOR.very_low))).toBe(true);
    expect(fills.some(f => f.backgroundColor === hexToRgb(JT_STATUS_COLOR.low))).toBe(true);
});

test('マーカーが四角形＋白枠で描画される（避難所マーカーとの誤認防止）', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    const shapes = await page.evaluate(() =>
        Array.from(document.querySelectorAll('.jartic-traffic-marker')).map(el => {
            const cs = getComputedStyle(el);
            return {
                width:  parseFloat(cs.width),
                height: parseFloat(cs.height),
                borderTopLeftRadius: parseFloat(cs.borderTopLeftRadius),
                borderWidth: parseFloat(cs.borderTopWidth),
                borderColor: cs.borderTopColor,
                borderStyle: cs.borderTopStyle,
            };
        })
    );

    expect(shapes.length).toBeGreaterThan(0);
    for (const s of shapes) {
        // 幅と高さがほぼ同じ（正方形に近い）
        expect(Math.abs(s.width - s.height)).toBeLessThanOrEqual(1);
        // 円形(50%)へ戻っていない — 角丸は幅の1/4未満（明確な四角形）
        expect(s.borderTopLeftRadius).toBeLessThan(s.width / 4);
        // 白枠が設定されている
        expect(s.borderStyle).toBe('solid');
        expect(s.borderWidth).toBeGreaterThanOrEqual(1.5);
        expect(s.borderColor).toBe('rgb(255, 255, 255)');
    }
});

test('凡例記号も同じ四角形＋白枠になっており、色・順序は変わっていない', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(300);
    await openLegendPanel(page);

    const swatches = await page.evaluate(() =>
        Array.from(document.querySelectorAll('#jartic-traffic-legend .jt-legend-swatch')).map(el => {
            const cs = getComputedStyle(el);
            return {
                width:  parseFloat(cs.width),
                height: parseFloat(cs.height),
                borderRadius: parseFloat(cs.borderTopLeftRadius),
                borderColor:  cs.borderTopColor,
                background:   cs.backgroundColor,
            };
        })
    );

    expect(swatches.length).toBe(6); // very_high/high/normal/low/very_low/unknown
    for (const sw of swatches) {
        expect(Math.abs(sw.width - sw.height)).toBeLessThanOrEqual(1);
        expect(sw.borderRadius).toBeLessThan(sw.width / 4); // 丸形ではない
        expect(sw.borderColor).toBe('rgb(255, 255, 255)');
    }

    // 表示順（多い→少ない→不明）と色が維持されている
    const expectedOrder = ['very_high', 'high', 'normal', 'low', 'very_low', 'unknown'];
    expect(swatches.map(s => s.background)).toEqual(
        expectedOrder.map(status => hexToRgb(JT_STATUS_COLOR[status])),
    );

    const legendLabels = await page.locator('#jartic-traffic-legend').textContent();
    expect(legendLabels).toContain('交通量非常に多い');
    expect(legendLabels).toContain('交通量多い');
    expect(legendLabels).toContain('通常');
    expect(legendLabels).toContain('交通量少ない');
    expect(legendLabels).toContain('交通量極端に少ない');
    expect(legendLabels).toContain('状態不明');
});

test('マーカークリックで観測点ごとの状態（上り・下り）が表示される', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await openFirstJarticPopup(page);

    const popup = page.locator('.jt-popup');
    await expect(popup).toContainText('状態（上り）');
    await expect(popup).toContainText('状態（下り）');
    await expect(popup).toContainText('交通量非常に多い');
});

test('トグルON時に凡例パネルへ道路交通量の凡例が表示される', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(300);

    // #mbc-tab-btn-legend で実際に凡例タブへ切り替え、真に画面表示されることを検証する
    await openLegendPanel(page);

    const legend = page.locator('#jartic-traffic-legend');
    await expect(legend).toBeVisible();
    await expect(legend).toContainText('道路交通量');
    await expect(legend).toContainText('交通量非常に多い');
});

test('トグルOFF時は凡例パネルの道路交通量凡例も非表示になる', async ({ page }) => {
    await setupBaseMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(200);

    await setJarticTrafficToggle(page, false);
    await page.waitForTimeout(200);

    await openLegendPanel(page);
    const legend = page.locator('#jartic-traffic-legend');
    await expect(legend).toBeHidden();
});

test('低ズーム時は取得せず案内文言のみ表示する', async ({ page }) => {
    let called = false;
    await setupBaseMocks(page, url => { called = true; return JARTIC_OK; });
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(400);

    // 初期表示（zoom 13）分の呼び出しをリセットしてから、地図をズームアウトする。
    // map は index.html 側で const 宣言されており window.map ではなく
    // トップレベル字句スコープ経由でのみ参照できる（他の script タグと共有）。
    called = false;
    await page.evaluate(() => map.setZoom(9));
    await page.waitForTimeout(600); // zoomend → デバウンス(250ms) を待つ

    expect(called).toBe(false);
    const status = page.locator('#jartic-traffic-status');
    await expect(status).toContainText('拡大');

    const markerCount = await page.evaluate(() =>
        document.querySelectorAll('.jartic-traffic-marker').length
    );
    expect(markerCount).toBe(0);
});

test('0件のとき「この範囲に交通量観測点はありません」を表示する', async ({ page }) => {
    await setupBaseMocks(page, () => JARTIC_EMPTY);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    const status = page.locator('#jartic-traffic-status');
    await expect(status).toContainText('この範囲に交通量観測点はありません');
});

test('取得失敗時は「道路交通量：取得できません」を表示する', async ({ page }) => {
    await setupBaseMocks(page, () => JARTIC_UNAVAILABLE);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    const status = page.locator('#jartic-traffic-status');
    await expect(status).toContainText('取得できません');
});

test('連続パン操作でも API 呼び出しがデバウンスされる（0回でPASSしない下限つき）', async ({ page }) => {
    let callCount = 0;
    await setupBaseMocks(page, () => { callCount++; return JARTIC_OK; });
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(300);

    const countAfterOpen = callCount;

    // 短時間に連続で地図を動かす（moveend が5回発火する）
    await page.evaluate(() => {
        for (let i = 0; i < 5; i++) {
            map.panBy([5, 5], { animate: false });
        }
    });
    await page.waitForTimeout(600);

    const delta = callCount - countAfterOpen;
    // デバウンスにより、5回の連続 moveend が1回に集約されることを検証する。
    // 上限だけでなく下限も課すことで「0回でもPASSする」false positive を防ぐ。
    expect(delta).toBe(1);
});

test('Abort/トークン方式により、先発BBOX Aが後着しても最終表示は後発BBOX Bのままになる', async ({ page }) => {
    // 地図移動前(A)は応答を遅延、移動後(B)は即応答させ、
    // 「遅れて届いたAの結果でBの表示が巻き戻らない」ことを検証する。
    const RESP_A = {
        status: 'ok', source: 'JARTIC / 国土交通省交通量API', updated_at: '2026-06-29T10:00:00+09:00',
        items: [{ code: 'A-STALE', lat: 35.6812, lon: 139.7671, up: 320, down: 280, total: 600, small: 520, large: 80,
            observed_at: '2026-06-29T09:55:00+09:00', unit: '5min', type: '一般国道',
            status: 'very_high', status_label: '交通量非常に多い',
            status_up: 'very_high', status_up_label: '交通量非常に多い',
            status_down: 'very_high', status_down_label: '交通量非常に多い' }],
    };
    const RESP_B = {
        status: 'ok', source: 'JARTIC / 国土交通省交通量API', updated_at: '2026-06-29T10:05:00+09:00',
        items: [{ code: 'B-FRESH', lat: 35.70, lon: 139.75, up: 5, down: 5, total: 10, small: 10, large: 0,
            observed_at: '2026-06-29T10:00:00+09:00', unit: '5min', type: '一般国道',
            status: 'low', status_label: '交通量少ない',
            status_up: 'low', status_up_label: '交通量少ない',
            status_down: 'low', status_down_label: '交通量少ない' }],
    };

    let requestCount = 0;
    await page.route('/favicon.ico', r => r.fulfill({ status: 204, body: '' }));
    await page.route('/api/**', r => {
        const url = r.request().url();
        if (url.includes('/stream')) return r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 10000\n\n' });
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
    await page.route('/api/jartic/traffic**', async r => {
        requestCount += 1;
        if (requestCount === 1) {
            // A（1回目のリクエスト）は大きく遅延させ、Bより後に到着させる
            await new Promise(res => setTimeout(res, 1200));
            return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RESP_A) });
        }
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RESP_B) });
    });
    const TRANSPARENT_PNG = Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
        'base64',
    );
    await page.route('**/basemaps.cartocdn.com/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));
    await page.route('**/openstreetmap.org/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }));

    await gotoIndex(page);
    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true); // → 1回目のリクエスト（A・遅延）を発火

    // デバウンス(250ms)後に地図を動かし、2回目のリクエスト（B・即応答）を発火させる
    await page.waitForTimeout(300);
    await page.evaluate(() => map.panBy([50, 50], { animate: false }));

    // Bの応答（即時）到着を待つ
    await page.waitForTimeout(600);

    // Aの遅延応答が届いた後（1200ms超）も、表示が古いA由来のデータへ巻き戻らないことを確認
    await page.waitForTimeout(1200);
    await page.waitForSelector('.jartic-traffic-marker', { timeout: 3000 });
    await page.evaluate(() => {
        const marker = document.querySelector('.jartic-traffic-marker');
        marker.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    });
    const popupText = await page.locator('.jt-popup').textContent();

    expect(requestCount).toBeGreaterThanOrEqual(2);
    // 最終表示は後発Bのみであり、遅れて届いた先発Aの観測点コードを含まない
    expect(popupText).toContain('B-FRESH');
    expect(popupText).not.toContain('A-STALE');

    const markerCount = await page.evaluate(() => document.querySelectorAll('.jartic-traffic-marker').length);
    expect(markerCount).toBe(1); // Aの古いマーカーがBに重複残存していない
});

test('10回のON/OFF反復でリスナー・API・マーカーが増殖せず console error も出ない', async ({ page }) => {
    let callCount = 0;
    await setupBaseMocks(page, () => { callCount++; return JARTIC_OK; });

    // ページには本タスクと無関係な既存ノイズ（Leafletデフォルトアイコン404、
    // 地震SSEモック未対応時のEventSource警告等）が toggle 操作前から存在するため、
    // ここでは「10回反復によって新たに発生する」問題（未捕捉例外・jartic関連の
    // console.error）だけを対象にする。ページ全体のconsole clean化は本タスクの範囲外。
    const consoleErrors = [];
    page.on('console', msg => {
        if (msg.type() === 'error' && /jartic/i.test(msg.text())) consoleErrors.push(msg.text());
    });
    page.on('pageerror', err => consoleErrors.push(String(err)));

    await gotoIndex(page);
    await openLayerPanel(page);

    for (let i = 0; i < 10; i++) {
        await setJarticTrafficToggle(page, true);
        await page.waitForTimeout(120);
        await setJarticTrafficToggle(page, false);
        await page.waitForTimeout(80);
    }

    // OFF直後の呼び出し数を記録し、OFF中に通信が発生していないことを確認する
    const callCountAfterLoop = callCount;
    await page.waitForTimeout(400);
    expect(callCount).toBe(callCountAfterLoop);

    // 最終状態は OFF：マーカー・凡例とも残っていない
    const markerCountOff = await page.evaluate(() => document.querySelectorAll('.jartic-traffic-marker').length);
    expect(markerCountOff).toBe(0);

    // 最後にもう一度ONにして、10回反復後もリスナーが多重登録されず1回分のマーカーのみ描画されることを確認
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(400);
    const markerCountOn = await page.evaluate(() => document.querySelectorAll('.jartic-traffic-marker').length);
    expect(markerCountOn).toBe(JARTIC_OK.items.length); // 重複描画されていない

    // moveend を1回発火しても、リスナー多重登録があれば呼び出し数が跳ね上がるはず
    const beforeMove = callCount;
    await page.evaluate(() => map.panBy([10, 10], { animate: false }));
    await page.waitForTimeout(500);
    expect(callCount - beforeMove).toBe(1); // 2以上ならリスナーが多重登録されている

    expect(consoleErrors, `console errors: ${consoleErrors.join(' | ')}`).toEqual([]);
});

// ── モバイル: 情報パネル最大化・警告UI干渉 ───────────────────────────────────────

function tsunamiActiveBody() {
    return {
        source: 'mock',
        status: 'active',
        observed_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ttl_seconds: 60,
        areas: [
            { code: null, name: '東京湾内湾', level: 'warning', level_label: '津波警報',
              expected_height: null, arrival_time: null, is_target: true },
        ],
        message: '津波警報が発表されています。',
    };
}

async function setupMobileMocks(page, jarticFactory = () => JARTIC_OK) {
    await setupBaseMocks(page, jarticFactory);
    await page.route('/api/tsunami/warnings/current', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tsunamiActiveBody()) }));
    await page.route('/emergency-shelters**', r =>
        r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: [], count: 0, total_count: 0 }) }));
}

test.describe('モバイル: 情報パネル最大化・津波警告UIとの干渉', () => {
    test.beforeEach(async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
    });

    test('津波警告表示中でも道路交通量トグル・凡例が正常に操作できる', async ({ page }) => {
        await setupMobileMocks(page);
        await gotoIndex(page);

        const banner = page.locator('#tsunami-warning-banner');
        await expect(banner).toBeVisible({ timeout: 5000 });

        await openLayerPanel(page);
        await setJarticTrafficToggle(page, true);
        await page.waitForTimeout(500);
        await expect(page.locator('.jartic-traffic-marker').first()).toBeAttached();

        await openLegendPanel(page);
        await expect(page.locator('#jartic-traffic-legend')).toBeVisible();
        await expect(page.locator('#jartic-traffic-legend')).toContainText('道路交通量');

        // 警告バナーは凡例タブに切り替えても表示され続ける
        await expect(banner).toBeVisible();

        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        );
        expect(overflow).toBe(false);

        await page.screenshot({ path: 'test-results/jartic-traffic-mobile.png' });
    });

    test('情報パネル最大化時に道路交通量の要素が警告UI・パネル操作を妨げない', async ({ page }) => {
        await setupMobileMocks(page);
        await gotoIndex(page);

        const banner = page.locator('#tsunami-warning-banner');
        await expect(banner).toBeVisible({ timeout: 5000 });

        // 道路交通量をONにしてから情報パネルを最大化する
        await openLayerPanel(page);
        await setJarticTrafficToggle(page, true);
        await page.waitForTimeout(500);

        await page.locator('#mbc-tab-btn-info').click();
        await expect(page.locator('#map-bottom-controls')).toHaveClass(/mbc-info-active/);
        await page.locator('#map-bottom-handle').click();
        await expect(page.locator('#map-bottom-controls')).toHaveClass(/mbc-info-expanded/);

        // 凡例タブは非表示（情報タブと排他）のため、道路交通量の凡例が最大化パネルへ重ならない
        await expect(page.locator('#jartic-traffic-legend')).toBeHidden();

        const layout = await page.evaluate(() => {
            const bannerEl = document.getElementById('tsunami-warning-banner');
            const overlay  = document.getElementById('map-ui-overlay');
            const handle   = document.getElementById('map-bottom-handle');
            const rectJson = el => el.getBoundingClientRect().toJSON();
            const pointTarget = rect => {
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                const el = document.elementFromPoint(x, y);
                const interactive = el?.closest?.('#map-bottom-handle, #map-bottom-controls, .mbc-tab-btn, #mbc-tabs');
                return { id: el?.id || '', interactiveId: interactive?.id || '' };
            };
            return {
                bannerVisible: bannerEl.offsetParent !== null,
                bannerZ: getComputedStyle(bannerEl).zIndex,
                overlayZ: getComputedStyle(overlay).zIndex,
                overlayPointerEvents: getComputedStyle(overlay).pointerEvents,
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                handleTarget: pointTarget(handle.getBoundingClientRect()),
            };
        });

        // 警告バナーは最大化パネルの下に隠れず、閉じる操作（handle）も塞がれていない
        expect(layout.bannerVisible).toBe(true);
        expect(Number(layout.overlayZ)).toBeGreaterThan(Number(layout.bannerZ));
        expect(layout.overlayPointerEvents).toBe('none');
        expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
        expect([layout.handleTarget.id, layout.handleTarget.interactiveId].join(' '))
            .toMatch(/map-bottom-handle|mbc-|map-bottom-controls/);

        await page.screenshot({ path: 'test-results/jartic-traffic-mobile-panel-max.png', fullPage: true });

        // 最大化パネルを閉じても道路交通量トグル・凡例が引き続き機能する
        await page.locator('#map-bottom-handle').click();
        await expect(page.locator('#map-bottom-controls')).toHaveClass(/mbc-collapsed/);
        await openLegendPanel(page);
        await expect(page.locator('#jartic-traffic-legend')).toBeVisible();
    });

    test('道路交通量ポップアップは津波警告バナーより不適切に前面へ出ない', async ({ page }) => {
        await setupMobileMocks(page);
        await gotoIndex(page);

        await expect(page.locator('#tsunami-warning-banner')).toBeVisible({ timeout: 5000 });

        await openLayerPanel(page);
        await setJarticTrafficToggle(page, true);
        await openFirstJarticPopup(page);
        await expect(page.locator('.jt-popup')).toBeVisible();

        const zCompare = await page.evaluate(() => {
            const popupPane = document.querySelector('.leaflet-popup-pane');
            const bannerEl  = document.getElementById('tsunami-warning-banner');
            return {
                popupZ:  Number(getComputedStyle(popupPane).zIndex) || 0,
                bannerZ: Number(getComputedStyle(bannerEl).zIndex) || 0,
            };
        });
        // Leafletポップアップは地図内の要素であり、津波警告バナー（画面全体の警告UI）より
        // 高いz-indexで画面全体を覆ってはならない
        expect(zCompare.popupZ).toBeLessThan(zCompare.bannerZ);

        await page.screenshot({ path: 'test-results/jartic-traffic-popup.png' });
    });
});

// ── Phase 7-B.3.1: 避難所と交通量マーカーの同時表示（識別性確認用スクリーンショット） ──

const SHELTER_TEST_SITES = [
    { name: '有明小学校', lat: 35.6418, lon: 139.7908, category: 'evacuation_shelter', designation: '指定避難所', address: '東京都江東区有明', hazard_types: ['tsunami'], region: 'tokyo' },
    { name: '有明北緑道公園', lat: 35.6422, lon: 139.7912, category: 'emergency_evacuation_site', designation: '指定緊急避難場所', address: '東京都江東区有明', hazard_types: ['tsunami'], region: 'tokyo' },
];

const JARTIC_NEAR_SHELTERS = {
    status: 'ok',
    source: 'JARTIC / 国土交通省交通量API',
    updated_at: '2026-06-29T10:00:00+09:00',
    items: [
        { code: 'S001', lat: 35.6420, lon: 139.7918, up: 320, down: 280, total: 600, small: 520, large: 80,
          observed_at: '2026-06-29T09:55:00+09:00', unit: '5min', type: '一般国道',
          status: 'very_high', status_label: '交通量非常に多い',
          status_up: 'very_high', status_up_label: '交通量非常に多い', status_down: 'very_high', status_down_label: '交通量非常に多い' },
        { code: 'S002', lat: 35.6426, lon: 139.7925, up: 5, down: 5, total: 10, small: 10, large: 0,
          observed_at: '2026-06-29T09:55:00+09:00', unit: '5min', type: '一般国道',
          status: 'low', status_label: '交通量少ない',
          status_up: 'low', status_up_label: '交通量少ない', status_down: 'low', status_down_label: '交通量少ない' },
    ],
};

async function setupCombinedMocks(page) {
    await setupBaseMocks(page, () => JARTIC_NEAR_SHELTERS);
    await page.route('**/api/emergency-shelters**', r => r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ count: SHELTER_TEST_SITES.length, total_count: SHELTER_TEST_SITES.length, data: SHELTER_TEST_SITES }),
    }));
    await page.route('**/emergency-shelters**', r => r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ count: SHELTER_TEST_SITES.length, total_count: SHELTER_TEST_SITES.length, data: SHELTER_TEST_SITES }),
    }));
}

test('PC: 避難所と道路交通量マーカーを同時表示し形状で識別できる', async ({ page }) => {
    await setupCombinedMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    await expect(page.locator('.jartic-traffic-marker').first()).toBeAttached();
    // 避難所アイコンが存在すれば形状DOMが変更されていないことも合わせて確認する
    const shelterCount = await page.locator('.shelter-icon').count();

    const shapes = await page.evaluate(() => {
        const jartic  = document.querySelector('.jartic-traffic-marker');
        const shelter = document.querySelector('.shelter-icon');
        const csJt = jartic ? getComputedStyle(jartic) : null;
        return {
            jarticBorderRadius: csJt ? csJt.borderTopLeftRadius : null,
            shelterExists: !!shelter,
            shelterHasSvg: shelter ? !!shelter.querySelector('svg, img') : false,
        };
    });
    expect(shapes.jarticBorderRadius).not.toBeNull();
    if (shelterCount > 0) {
        expect(shapes.shelterExists).toBe(true);
        expect(shapes.shelterHasSvg).toBe(true);
    }

    // レイヤーパネルを閉じ（「操作」タブへ戻す）、マーカー同士を拡大して見比べやすくする
    await page.locator('#mbc-tab-btn-action').click();
    await page.evaluate(() => map.setView([35.6421, 139.7916], 18));
    await page.waitForTimeout(400);
    await page.screenshot({ path: 'test-results/jartic-traffic-with-shelters-desktop.png' });
});

test('モバイル: 避難所と道路交通量マーカーを同時表示し形状で識別できる', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setupCombinedMocks(page);
    await gotoIndex(page);

    await openLayerPanel(page);
    await setJarticTrafficToggle(page, true);
    await page.waitForTimeout(500);

    await expect(page.locator('.jartic-traffic-marker').first()).toBeAttached();

    const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflow).toBe(false);

    await page.locator('#mbc-tab-btn-action').click();
    await page.evaluate(() => map.setView([35.6421, 139.7916], 18));
    await page.waitForTimeout(400);
    await page.screenshot({ path: 'test-results/jartic-traffic-with-shelters-mobile.png' });
});
