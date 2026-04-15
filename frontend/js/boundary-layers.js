/**
 * boundary-layers.js — 行政界レイヤー管理
 *
 * ハザードレイヤー（hazard-layers.js）とは独立したモジュール。
 * 将来の都道府県拡張（神奈川、千葉、埼玉等）を見越した定義ベース構造。
 *
 * ─ 将来の都道府県追加方法 ─────────────────────────────────────────────────
 * 都道府県を1件追加するには以下 3 か所を変更する:
 *
 *   1. BOUNDARY_LAYERS (このファイル) に新エントリを追加
 *   2. map-overlay-ui.js の administrativeLayerMenu にアイテムを追加
 *   3. index.html のサイドパネルにチェックボックスを追加
 *
 * 対応 GeoJSON を frontend/layers/administrative/ に配置することも必要。
 *
 * 右上ボタン（boundary-toggle-btn）は都道府県横断のグローバル操作であり、
 * 個別レイヤーではなくこのモジュールが一元管理する。
 * ──────────────────────────────────────────────────────────────────────────
 */

// ── グローバルボタン ID ───────────────────────────────────────────────────
// 右上に表示される行政界の一括 ON/OFF ボタン。
// 将来複数都道府県が増えても、このボタンは1つだけ存在する。
const BOUNDARY_BUTTON_ID = 'boundary-toggle-btn';

// ── 行政界レイヤー定義 ────────────────────────────────────────────────────
const BOUNDARY_LAYERS = {
    tokyo: {
        id: 'TOKYO-BOUNDARY-001',
        key: 'tokyo',
        region: 'kanto',
        name: '行政界（東京都）',
        category: 'administrative',
        sourceType: 'geojson',
        url: '/layers/administrative/tokyo_boundary.geojson',
        style: {
            color: '#5c6bc0',
            weight: 1.5,
            opacity: 0.9,
            fillColor: '#3949ab',
            fillOpacity: 0.06,
            dashArray: null,
        },
        checkboxId: 'showBoundaryTokyo',
        // 表示状態
        visible: false,
        loaded: false,
        layer: null,
        rawData: null,
        // 非同期制御: 同時リクエストの重複防止と stale 完了の検出
        _loadingPromise: null,   // 進行中の fetch Promise をメモ化
        _desiredVisible: false,  // load 完了時点での "意図" を追跡
    },
    kanagawa: {
        id: 'KANAGAWA-BOUNDARY-001',
        key: 'kanagawa',
        region: 'kanto',
        name: '行政界（神奈川県）',
        category: 'administrative',
        sourceType: 'geojson',
        url: '/layers/administrative/kanagawa_boundary.geojson',
        style: {
            color: '#26a69a',
            weight: 1.5,
            opacity: 0.9,
            fillColor: '#00897b',
            fillOpacity: 0.06,
            dashArray: null,
        },
        checkboxId: 'showBoundaryKanagawa',
        visible: false,
        loaded: false,
        layer: null,
        rawData: null,
        _loadingPromise: null,
        _desiredVisible: false,
    },
};

// ── レイヤー読み込み ──────────────────────────────────────────────────────
// 同時に複数回呼ばれた場合は同じ Promise を返す（重複 fetch 防止）。
// キャッシュ済みなら即座に返す。

async function loadBoundaryLayer(layerKey) {
    const boundary = BOUNDARY_LAYERS[layerKey];
    if (!boundary) {
        throw new Error(`未知の行政界レイヤーです: ${layerKey}`);
    }

    // キャッシュ済み
    if (boundary.layer) {
        return boundary.layer;
    }

    // 進行中の fetch があれば同じ Promise を返す（重複 fetch 防止）
    if (boundary._loadingPromise) {
        return boundary._loadingPromise;
    }

    boundary._loadingPromise = (async () => {
        let response;
        try {
            response = await fetch(boundary.url, { cache: 'no-cache' });
        } catch (err) {
            boundary._loadingPromise = null;
            console.error(`[boundary] ${boundary.name} 読み込みに失敗しました:`, err);
            throw err;
        }

        if (!response.ok) {
            boundary._loadingPromise = null;
            const msg = `${boundary.name}データの取得に失敗しました (HTTP ${response.status})`;
            console.error('[boundary]', msg);
            throw new Error(msg);
        }

        const geojson = await response.json();
        boundary.rawData = geojson;
        boundary.layer = L.geoJSON(geojson, {
            style: () => boundary.style,
        });
        boundary.loaded = true;
        boundary._loadingPromise = null;
        return boundary.layer;
    })();

    return boundary._loadingPromise;
}

// ── 表示制御 ─────────────────────────────────────────────────────────────

function showBoundaryLayer(layerKey) {
    const boundary = BOUNDARY_LAYERS[layerKey];
    if (!boundary || !boundary.layer) return;
    if (!map.hasLayer(boundary.layer)) {
        boundary.layer.addTo(map);
    }
    boundary.visible = true;
    syncBoundaryLayerUI(layerKey);
}

function hideBoundaryLayer(layerKey) {
    const boundary = BOUNDARY_LAYERS[layerKey];
    if (!boundary) return;
    if (boundary.layer && map.hasLayer(boundary.layer)) {
        map.removeLayer(boundary.layer);
    }
    boundary.visible = false;
    syncBoundaryLayerUI(layerKey);
}

async function setBoundaryLayerVisibility(layerKey, visible) {
    const boundary = BOUNDARY_LAYERS[layerKey];
    if (!boundary) return;

    // 最終意図を記録する。async 完了後に意図が変わっていれば何もしない。
    boundary._desiredVisible = visible;

    if (!visible) {
        hideBoundaryLayer(layerKey);
        return;
    }

    try {
        await loadBoundaryLayer(layerKey);
    } catch (err) {
        console.error(`[boundary] ${boundary.name} 読み込み失敗:`, err);
        boundary.visible = false;
        syncBoundaryLayerUI(layerKey);
        return;
    }

    // await の間に意図が変わっていたら（例: 高速連打で OFF に戻された）何もしない
    if (!boundary._desiredVisible) {
        return;
    }

    showBoundaryLayer(layerKey);
}

async function toggleBoundaryLayer(layerKey) {
    const boundary = BOUNDARY_LAYERS[layerKey];
    if (!boundary) return;
    await setBoundaryLayerVisibility(layerKey, !boundary.visible);
}

// ── グローバルボタンの ON/OFF ─────────────────────────────────────────────
// 行政界ボタン1クリックで全レイヤーをまとめて制御する。
// いずれか1つでも visible なら全 OFF、全 OFF なら全 ON。

async function toggleAllBoundaryLayers() {
    const anyVisible = Object.values(BOUNDARY_LAYERS).some(b => b.visible);
    await Promise.all(
        Object.keys(BOUNDARY_LAYERS).map(key =>
            setBoundaryLayerVisibility(key, !anyVisible)
        )
    );
}

// ── UI 同期 ───────────────────────────────────────────────────────────────
// 指定レイヤーのチェックボックス＋ステータスを更新し、
// グローバルボタンのアクティブ状態を全レイヤーの集計で決める。

function syncBoundaryLayerUI(layerKey) {
    const boundary = BOUNDARY_LAYERS[layerKey];
    if (!boundary) return;
    const visible = boundary.visible;

    // サイドパネルのチェックボックス
    const checkbox = document.getElementById(boundary.checkboxId);
    if (checkbox && checkbox.checked !== visible) {
        checkbox.checked = visible;
        // レイヤーパネル側のチェックボックスも同期するために change を発火
        checkbox.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // 右上グローバルボタン: 全レイヤーの集計で決める
    const btn = document.getElementById(BOUNDARY_BUTTON_ID);
    if (btn) {
        const anyVisible = Object.values(BOUNDARY_LAYERS).some(b => b.visible);
        btn.classList.toggle('map-overlay-btn--active', anyVisible);
    }

    // サイドパネルのステータステキスト
    const statusEl = document.getElementById('boundaryStatus');
    if (statusEl) {
        const onLayers = Object.values(BOUNDARY_LAYERS)
            .filter(b => b.visible)
            .map(b => b.name);
        statusEl.textContent = onLayers.length > 0
            ? `行政界レイヤー: ON（${onLayers.join(' / ')}）`
            : '行政界レイヤー: OFF';
    }
}

// ── 初期化 ────────────────────────────────────────────────────────────────

function initBoundaryLayers() {
    // 各レイヤーのサイドパネルチェックボックスにバインド
    Object.entries(BOUNDARY_LAYERS).forEach(([layerKey, boundary]) => {
        const checkbox = document.getElementById(boundary.checkboxId);
        if (checkbox) {
            checkbox.checked = boundary.visible;
            checkbox.addEventListener('change', async (e) => {
                // syncBoundaryLayerUI が dispatchEvent した場合は状態一致 → スキップ
                if (e.target.checked === boundary.visible) return;
                await setBoundaryLayerVisibility(layerKey, e.target.checked);
            });
        }
    });

    // グローバルボタンは1回だけバインド
    const btn = document.getElementById(BOUNDARY_BUTTON_ID);
    if (btn) {
        btn.addEventListener('click', () => {
            toggleAllBoundaryLayers();
        });
    }

    console.debug('[boundary-layers] 初期化完了。定義済みレイヤー:', Object.keys(BOUNDARY_LAYERS));
}

// ── 起動 ─────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {
    initBoundaryLayers();
});
