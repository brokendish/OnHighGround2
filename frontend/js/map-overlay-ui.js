/**
 * map-overlay-ui.js — 地図上オーバーレイUI
 *
 * 地図エリア上に重ねたフローティングUIの初期化・イベントバインディング・
 * 状態管理を担当する。既存のサイドパネル機能とは独立して追加される。
 *
 * 依存: state.js, app.js, hazard-layers.js（より後にロードされる）
 */

// ── 内部状態 ──────────────────────────────────────────────────────────────
const mapUiState = {
    layerPanelOpen: false,
    legendPanelOpen: false,
    shelterPanelOpen: false,
};

// ── 行政界レイヤーメニュー定義 ────────────────────────────────────────────
// ハザードレイヤーとは独立したカテゴリ。
// 将来の都道府県追加は BOUNDARY_LAYERS (boundary-layers.js) と
// このリストに 1 エントリ追加するだけでよい。
const administrativeLayerMenu = [
    {
        key: 'administrative',
        label: '行政界',
        items: [
            { checkboxId: 'showBoundaryTokyo', layerKey: 'tokyo', label: '東京都', enabled: true },
            // 将来追加: { checkboxId: 'showBoundaryKanagawa', layerKey: 'kanagawa', label: '神奈川県', enabled: false },
            // 将来追加: { checkboxId: 'showBoundaryChiba',    layerKey: 'chiba',    label: '千葉県',   enabled: false },
        ],
        legend: [],
    },
];

// ── ハザードレイヤーメニュー定義 ──────────────────────────────────────────
// 将来の都道府県拡張を見越した宣言的データ構造。
// enabled: false にすると disabled 表示（将来未実装レイヤー向け）。
const hazardLayerMenu = [
    {
        key: 'tsunami',
        label: '津波浸水想定',
        items: [
            { checkboxId: 'showTsunamiHazardTokyo',    layerKey: 'tsunami_tokyo',    label: '東京都',   enabled: true },
            { checkboxId: 'showTsunamiHazardKanagawa', layerKey: 'tsunami_kanagawa', label: '神奈川県', enabled: true },
            { checkboxId: 'showTsunamiHazardChiba',    layerKey: 'tsunami_chiba',    label: '千葉県',   enabled: true },
        ],
        legend: [
            { color: '#ffe082', label: '〜0.5m' },
            { color: '#ffca28', label: '0.5〜1m' },
            { color: '#ff8f00', label: '1〜3m' },
            { color: '#f4511e', label: '3〜5m' },
            { color: '#b71c1c', label: '5m超' },
        ]
    },
    {
        key: 'flood',
        label: '洪水浸水想定',
        items: [
            { checkboxId: 'showFloodTokyoMax', layerKey: 'flood_tokyo_max', label: '東京都（想定最大規模）', enabled: true },
        ],
        legend: [
            { color: '#ffe082', label: '0.5m未満' },
            { color: '#ffca28', label: '0.5〜3m' },
            { color: '#ff8f00', label: '3〜5m' },
            { color: '#f4511e', label: '5〜10m' },
            { color: '#b71c1c', label: '10m以上' },
        ]
    },
    {
        key: 'storm_surge',
        label: '高潮浸水想定',
        items: [
            { checkboxId: 'showStormSurgeTokyo', layerKey: 'storm_surge_tokyo', label: '東京都', enabled: true },
        ],
        legend: [
            { color: '#b3e5fc', label: '0.3m未満' },
            { color: '#4fc3f7', label: '0.3〜0.5m' },
            { color: '#0288d1', label: '0.5〜1m' },
            { color: '#01579b', label: '1〜3m' },
            { color: '#7b1fa2', label: '3〜5m' },
            { color: '#4a148c', label: '5m超' },
        ]
    },
    {
        key: 'inland_flood',
        label: '内水氾濫',
        items: [
            { checkboxId: 'showInlandFloodTokyo', layerKey: 'inland_flood_tokyo', label: '東京都', enabled: true },
        ],
        legend: [
            { color: '#b3e5fc', label: '不明・安全' },
            { color: '#29b6f6', label: '0〜1m' },
            { color: '#f4511e', label: '1〜3m' },
            { color: '#b71c1c', label: '3m以上' },
        ]
    },
    {
        key: 'landslide',
        label: '土砂災害',
        items: [
            { checkboxId: 'showLandslideTokyo', layerKey: 'landslide_tokyo', label: '東京都', enabled: true },
        ],
        legend: [
            { color: '#b71c1c', label: '特別警戒区域' },
            { color: '#e65100', label: '警戒区域' },
        ]
    },
];

// ── 初期化エントリポイント ─────────────────────────────────────────────────
function initMapOverlayUI() {
    buildLayerPanel();
    buildLegendPanel();
    bindLocateButton();
    bindSearchButton();
    bindDistanceSlider();
    bindElevationSlider();
    bindLayerPanelToggle();
    bindLegendPanelToggle();
    bindClearButton();
    bindShelterButton();
    bindBottomPanelToggle();
    bindOutsideClick();
    syncSlidersFromInputs();
    preventMapPanOnOverlay();
}

// ── 下部パネル折りたたみ ──────────────────────────────────────────────────
function bindBottomPanelToggle() {
    const handle   = document.getElementById('map-bottom-handle');
    const controls = document.getElementById('map-bottom-controls');
    if (!handle || !controls) return;

    handle.addEventListener('click', () => {
        controls.classList.toggle('mbc-collapsed');
    });
}

// ── Leaflet へのイベント伝播を防止 ────────────────────────────────────────
// Leaflet は #map 上の touchstart/mousedown をキャプチャして地図パンを起動する。
// オーバーレイ要素上での操作がパンに化けないよう伝播を遮断する。
function preventMapPanOnOverlay() {
    const targets = [
        document.getElementById('map-bottom-controls'),
        document.getElementById('map-top-right-controls'),
    ].filter(Boolean);

    targets.forEach(el => {
        // Leaflet ユーティリティで click/dblclick/scroll 伝播を止める
        if (typeof L !== 'undefined') {
            L.DomEvent.disableClickPropagation(el);
            L.DomEvent.disableScrollPropagation(el);
        }
        // touchstart/mousedown は Leaflet のパン開始トリガー → 止める
        el.addEventListener('touchstart', e => e.stopPropagation(), { passive: true });
        el.addEventListener('mousedown',  e => e.stopPropagation());
        // touchmove も止めてスライダ操作中に地図が動かないようにする
        el.addEventListener('touchmove',  e => e.stopPropagation(), { passive: true });
    });
}

// ── 現在地取得ボタン ──────────────────────────────────────────────────────
function bindLocateButton() {
    document.getElementById('locate-overlay-btn').addEventListener('click', () => {
        document.getElementById('getCurrentLocation').click();
    });
}

// ── 避難先検索ボタン ──────────────────────────────────────────────────────
function bindSearchButton() {
    document.getElementById('search-overlay-btn').addEventListener('click', () => {
        const btn = document.getElementById('searchDestinations');
        if (!btn.disabled) btn.click();
    });
}

// ── 地図クリアボタン ──────────────────────────────────────────────────────
function bindClearButton() {
    document.getElementById('map-clear-overlay-btn').addEventListener('click', () => {
        document.getElementById('clearMap').click();
    });
}

// ── 避難場所ボタン：パネル開閉 + チェックボックス制御 ────────────────────
function bindShelterButton() {
    const btn     = document.getElementById('shelter-toggle-btn');
    const panel   = document.getElementById('shelter-panel');
    // パネル内チェックボックス（右上パネル）
    const panelEl1 = document.getElementById('shelterPanel_evacuation');
    const panelEl2 = document.getElementById('shelterPanel_emergency');
    // サイドバー側チェックボックス（既存）
    const sideEl1  = document.getElementById('showEmergencyShelters');
    const sideEl2  = document.getElementById('showEmergencyEvacuationSites');
    if (!btn || !panel) return;

    // ボタンのアクティブ状態：どちらかのカテゴリが ON なら active
    const _syncBtnActive = () => {
        const anyOn = (sideEl1 && sideEl1.checked) || (sideEl2 && sideEl2.checked);
        btn.classList.toggle('map-overlay-btn--active', anyOn || mapUiState.shelterPanelOpen);
    };

    // パネル内 ↔ サイドバー側を双方向同期
    const _syncToSide = (panelEl, sideEl) => {
        if (!panelEl || !sideEl) return;
        panelEl.addEventListener('change', () => {
            sideEl.checked = panelEl.checked;
            sideEl.dispatchEvent(new Event('change'));
        });
        sideEl.addEventListener('change', () => {
            panelEl.checked = sideEl.checked;
            _syncBtnActive();
        });
    };
    _syncToSide(panelEl1, sideEl1);
    _syncToSide(panelEl2, sideEl2);

    // ボタンクリック：パネル開閉（他パネルは閉じる）
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        mapUiState.shelterPanelOpen = !mapUiState.shelterPanelOpen;
        panel.style.display = mapUiState.shelterPanelOpen ? 'block' : 'none';
        _syncBtnActive();

        // 他パネルを閉じる
        if (mapUiState.shelterPanelOpen) {
            if (mapUiState.layerPanelOpen) {
                mapUiState.layerPanelOpen = false;
                document.getElementById('layer-panel').style.display = 'none';
                document.getElementById('layer-toggle-btn').classList.remove('map-overlay-btn--active');
            }
            if (mapUiState.legendPanelOpen) {
                mapUiState.legendPanelOpen = false;
                document.getElementById('legend-panel').style.display = 'none';
                document.getElementById('legend-toggle-btn').classList.remove('map-overlay-btn--active');
            }
        }
    });

    // 初期状態を反映
    _syncBtnActive();
}

// ── 距離スライダ ──────────────────────────────────────────────────────────
function bindDistanceSlider() {
    const slider = document.getElementById('distance-slider-overlay');
    const label  = document.getElementById('distance-value-overlay');
    const input  = document.getElementById('maxDistance');

    function fmt(v) {
        const n = parseInt(v, 10);
        return n >= 1000
            ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'km'
            : n + 'm';
    }

    slider.addEventListener('input', () => {
        label.textContent = fmt(slider.value);
        input.value = slider.value;
    });

    // サイドパネル側の input が変更されたときに同期
    input.addEventListener('input', () => {
        const v = Math.max(100, Math.min(10000, parseInt(input.value, 10) || 2000));
        slider.value = v;
        label.textContent = fmt(v);
    });
}

// ── 高低差スライダ ────────────────────────────────────────────────────────
function bindElevationSlider() {
    const slider = document.getElementById('elevation-slider-overlay');
    const label  = document.getElementById('elevation-value-overlay');
    const input  = document.getElementById('minElevationGain');

    slider.addEventListener('input', () => {
        label.textContent = slider.value + 'm';
        input.value = slider.value;
    });

    input.addEventListener('input', () => {
        const v = Math.max(1, Math.min(100, parseInt(input.value, 10) || 10));
        slider.value = v;
        label.textContent = v + 'm';
    });
}

// ── スライダを既存インプットの初期値に合わせる ────────────────────────────
function syncSlidersFromInputs() {
    const distInput  = document.getElementById('maxDistance');
    const elevInput  = document.getElementById('minElevationGain');
    const distSlider = document.getElementById('distance-slider-overlay');
    const elevSlider = document.getElementById('elevation-slider-overlay');
    const distLabel  = document.getElementById('distance-value-overlay');
    const elevLabel  = document.getElementById('elevation-value-overlay');

    const dv = parseInt(distInput.value, 10) || 2000;
    distSlider.value = dv;
    distLabel.textContent = dv >= 1000
        ? (dv / 1000).toFixed(1).replace(/\.0$/, '') + 'km'
        : dv + 'm';

    const ev = parseInt(elevInput.value, 10) || 10;
    elevSlider.value = ev;
    elevLabel.textContent = ev + 'm';
}

// ── レイヤーパネル構築 ────────────────────────────────────────────────────
function buildLayerPanel() {
    const panel = document.getElementById('layer-panel');
    // タイトルは HTML に書いてあるので category 以降だけ追記
    const container = document.createElement('div');

    hazardLayerMenu.forEach(cat => {
        const catEl = document.createElement('div');
        catEl.className = 'layer-panel-category';
        catEl.dataset.catKey = cat.key;

        // カテゴリヘッダ
        const header = document.createElement('div');
        header.className = 'layer-panel-category-header';
        header.innerHTML = `<span class="lpc-arrow">▶</span><span>${cat.label}</span>`;
        header.addEventListener('click', () => catEl.classList.toggle('open'));

        // 都道府県リスト
        const prefs = document.createElement('div');
        prefs.className = 'layer-panel-prefectures';

        cat.items.forEach(item => {
            const labelEl = document.createElement('label');
            labelEl.className = 'layer-panel-item' + (item.enabled ? '' : ' disabled');

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.disabled = !item.enabled;

            // 既存チェックボックスと双方向同期
            const sourceEl = document.getElementById(item.checkboxId);
            if (sourceEl) {
                cb.checked = sourceEl.checked;
                // overlay → レイヤー表示切替を直接実行 + サイドバーと同期
                cb.addEventListener('change', () => {
                    const newVal = cb.checked;
                    sourceEl.checked = newVal;
                    if (typeof setHazardLayerVisibility === 'function') {
                        setHazardLayerVisibility(item.layerKey, newVal).catch(err => {
                            console.error('[overlay] レイヤー切替エラー:', err);
                            cb.checked = !newVal;
                            sourceEl.checked = !newVal;
                        });
                    }
                });
                // サイドバー側が変わったときはオーバーレイにも反映
                sourceEl.addEventListener('change', () => {
                    cb.checked = sourceEl.checked;
                });
            }

            labelEl.appendChild(cb);
            labelEl.appendChild(document.createTextNode(item.label));
            prefs.appendChild(labelEl);
        });

        // 凡例
        if (Array.isArray(cat.legend) && cat.legend.length > 0) {
            const legendEl = document.createElement('div');
            legendEl.className = 'lpc-legend';
            cat.legend.forEach(entry => {
                const row = document.createElement('div');
                row.className = 'lpc-legend-entry';
                row.innerHTML = `<span class="lpc-legend-swatch" style="background:${entry.color};"></span>${entry.label}`;
                legendEl.appendChild(row);
            });
            prefs.appendChild(legendEl);
        }

        catEl.appendChild(header);
        catEl.appendChild(prefs);
        container.appendChild(catEl);
    });

    // ── 行政界セクション（ハザードとは独立） ─────────────────────────────
    const adminSep = document.createElement('hr');
    adminSep.style.cssText = 'margin:6px 0; border:none; border-top:1px solid rgba(0,0,0,0.12);';
    container.appendChild(adminSep);

    administrativeLayerMenu.forEach(cat => {
        const catEl = document.createElement('div');
        catEl.className = 'layer-panel-category';
        catEl.dataset.catKey = cat.key;

        const header = document.createElement('div');
        header.className = 'layer-panel-category-header';
        header.innerHTML = `<span class="lpc-arrow">▶</span><span>${cat.label}</span>`;
        header.addEventListener('click', () => catEl.classList.toggle('open'));

        const prefs = document.createElement('div');
        prefs.className = 'layer-panel-prefectures';

        cat.items.forEach(item => {
            const labelEl = document.createElement('label');
            labelEl.className = 'layer-panel-item' + (item.enabled ? '' : ' disabled');

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.disabled = !item.enabled;

            const sourceEl = document.getElementById(item.checkboxId);
            if (sourceEl) {
                cb.checked = sourceEl.checked;
                cb.addEventListener('change', () => {
                    const newVal = cb.checked;
                    sourceEl.checked = newVal;
                    if (typeof setBoundaryLayerVisibility === 'function') {
                        setBoundaryLayerVisibility(item.layerKey, newVal).catch(err => {
                            console.error('[overlay] 行政界切替エラー:', err);
                            cb.checked = !newVal;
                            sourceEl.checked = !newVal;
                        });
                    }
                });
                sourceEl.addEventListener('change', () => {
                    cb.checked = sourceEl.checked;
                });
            }

            labelEl.appendChild(cb);
            labelEl.appendChild(document.createTextNode(item.label));
            prefs.appendChild(labelEl);
        });

        catEl.appendChild(header);
        catEl.appendChild(prefs);
        container.appendChild(catEl);
    });

    panel.appendChild(container);
}

// ── 凡例パネル構築 ────────────────────────────────────────────────────────
function buildLegendPanel() {
    const panel = document.getElementById('legend-panel');
    // 既存の #mapLegend .legend-body の内容をクローンして流用
    const src = document.querySelector('#mapLegend .legend-body');
    if (src) {
        const clone = src.cloneNode(true);
        panel.appendChild(clone);
    }
}

// ── レイヤーパネル トグル ─────────────────────────────────────────────────
function bindLayerPanelToggle() {
    const btn        = document.getElementById('layer-toggle-btn');
    const panel      = document.getElementById('layer-panel');
    const legendBtn  = document.getElementById('legend-toggle-btn');
    const legendPanel = document.getElementById('legend-panel');

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        mapUiState.layerPanelOpen = !mapUiState.layerPanelOpen;
        panel.style.display = mapUiState.layerPanelOpen ? 'block' : 'none';
        btn.classList.toggle('map-overlay-btn--active', mapUiState.layerPanelOpen);

        // 凡例・避難場所パネルを閉じる
        if (mapUiState.layerPanelOpen) {
            if (mapUiState.legendPanelOpen) {
                mapUiState.legendPanelOpen = false;
                legendPanel.style.display = 'none';
                legendBtn.classList.remove('map-overlay-btn--active');
            }
            if (mapUiState.shelterPanelOpen) {
                mapUiState.shelterPanelOpen = false;
                document.getElementById('shelter-panel').style.display = 'none';
            }
        }
    });
}

// ── 凡例パネル トグル ─────────────────────────────────────────────────────
function bindLegendPanelToggle() {
    const btn        = document.getElementById('legend-toggle-btn');
    const panel      = document.getElementById('legend-panel');
    const layerBtn   = document.getElementById('layer-toggle-btn');
    const layerPanel = document.getElementById('layer-panel');

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        mapUiState.legendPanelOpen = !mapUiState.legendPanelOpen;
        panel.style.display = mapUiState.legendPanelOpen ? 'block' : 'none';
        btn.classList.toggle('map-overlay-btn--active', mapUiState.legendPanelOpen);

        // レイヤー・避難場所パネルを閉じる
        if (mapUiState.legendPanelOpen) {
            if (mapUiState.layerPanelOpen) {
                mapUiState.layerPanelOpen = false;
                layerPanel.style.display = 'none';
                layerBtn.classList.remove('map-overlay-btn--active');
            }
            if (mapUiState.shelterPanelOpen) {
                mapUiState.shelterPanelOpen = false;
                document.getElementById('shelter-panel').style.display = 'none';
            }
        }
    });
}

// ── パネル外クリックで閉じる ──────────────────────────────────────────────
function bindOutsideClick() {
    document.addEventListener('click', (e) => {
        const topRight = document.getElementById('map-top-right-controls');
        if (!topRight || topRight.contains(e.target)) return;

        if (mapUiState.layerPanelOpen) {
            mapUiState.layerPanelOpen = false;
            document.getElementById('layer-panel').style.display = 'none';
            document.getElementById('layer-toggle-btn').classList.remove('map-overlay-btn--active');
        }
        if (mapUiState.legendPanelOpen) {
            mapUiState.legendPanelOpen = false;
            document.getElementById('legend-panel').style.display = 'none';
            document.getElementById('legend-toggle-btn').classList.remove('map-overlay-btn--active');
        }
        if (mapUiState.shelterPanelOpen) {
            mapUiState.shelterPanelOpen = false;
            document.getElementById('shelter-panel').style.display = 'none';
            const sideEl1 = document.getElementById('showEmergencyShelters');
            const sideEl2 = document.getElementById('showEmergencyEvacuationSites');
            const anyOn = (sideEl1 && sideEl1.checked) || (sideEl2 && sideEl2.checked);
            document.getElementById('shelter-toggle-btn').classList.toggle('map-overlay-btn--active', anyOn);
        }
    });
}

// ── 起動 ─────────────────────────────────────────────────────────────────
// app.js より後にロードされる前提。DOM は既に準備済み。
window.addEventListener('load', () => {
    initMapOverlayUI();
});
