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
            { checkboxId: 'showBoundaryTokyo',    layerKey: 'tokyo',    label: '東京都',   enabled: true },
            { checkboxId: 'showBoundaryKanagawa', layerKey: 'kanagawa', label: '神奈川県', enabled: true },
            // 将来追加: { checkboxId: 'showBoundaryChiba', layerKey: 'chiba', label: '千葉県', enabled: false },
        ],
        legend: [],
    },
];

// ── ハザードレイヤーメニュー定義 ──────────────────────────────────────────
// 将来の都道府県拡張を見越した宣言的データ構造。
// enabled: false にすると disabled 表示（将来未実装レイヤー向け）。
const hazardLayerMenu = typeof getHazardLayerMenuConfig === 'function'
    ? getHazardLayerMenuConfig()
    : [];

function getHazardMenuConfigSafe() {
    return typeof getHazardLayerMenuConfig === 'function'
        ? getHazardLayerMenuConfig()
        : hazardLayerMenu;
}

function applyHazardPanelItemState(labelEl, checkboxEl, item) {
    const uiState = typeof getHazardLayerUiState === 'function'
        ? getHazardLayerUiState(item.layerKey)
        : {
            enabled: item.enabled,
            badgeText: item.badgeText || '',
            title: item.title || '',
        };
    labelEl.className = 'layer-panel-item' + (uiState.enabled ? '' : ' disabled');
    labelEl.title = uiState.title || '';
    checkboxEl.disabled = !uiState.enabled;
    checkboxEl.title = uiState.title || '';

    let noteEl = labelEl.querySelector('.layer-panel-item-note');
    if (!noteEl) {
        noteEl = document.createElement('span');
        noteEl.className = 'layer-panel-item-note';
        labelEl.appendChild(noteEl);
    }
    noteEl.textContent = uiState.badgeText || '';
    noteEl.style.display = uiState.badgeText ? 'inline-flex' : 'none';
}

function syncHazardLayerPanelState() {
    document.querySelectorAll('#layer-panel [data-layer-key]').forEach((labelEl) => {
        const layerKey = labelEl.dataset.layerKey;
        const checkboxEl = labelEl.querySelector('input[type="checkbox"]');
        if (!checkboxEl) {
            return;
        }
        applyHazardPanelItemState(labelEl, checkboxEl, { layerKey, enabled: !checkboxEl.disabled });
        const sourceEl = document.getElementById(checkboxEl.dataset.sourceCheckboxId || '');
        if (sourceEl) {
            checkboxEl.checked = sourceEl.checked;
            checkboxEl.disabled = sourceEl.disabled;
            labelEl.classList.toggle('disabled', sourceEl.disabled);
        }
    });
}

function dispatchMirroredCheckboxChange(sourceEl, newVal) {
    if (!sourceEl) {
        return;
    }
    sourceEl.checked = newVal;
    sourceEl.dispatchEvent(new Event('change', { bubbles: true }));
}

// ── 初期化エントリポイント ─────────────────────────────────────────────────
function initMapOverlayUI() {
    buildLayerPanel();
    buildLegendPanel();
    bindLocateMapButton();
    bindSearchButton();
    bindDistanceSlider();
    bindElevationSlider();
    bindLayerPanelToggle();
    bindLegendPanelToggle();
    bindClearButton();
    initShelterControls();
    bindBottomPanelToggle();
    bindBrandBadgeTooltip();
    bindDetailToggle();
    bindOutsideClick();
    syncSlidersFromInputs();
    preventMapPanOnOverlay();
}

// ── 詳細設定（スライダー）の折りたたみトグル ──────────────────────────────
function bindDetailToggle() {
    const toggle = document.getElementById('mbc-detail-toggle');
    const body   = document.getElementById('mbc-sliders-body');
    if (!toggle || !body) return;

    toggle.addEventListener('click', () => {
        const isOpen = body.classList.toggle('open');
        toggle.classList.toggle('open', isOpen);
    });
}

// ── STEP 状態管理 ──────────────────────────────────────────────────────────
// map.js の updateCurrentLocation 完了後に呼ばれる。
// 現在地取得済み → STEP 1 完了表示 + STEP 2 を有効化。
function markStep1Done() {
    const step1 = document.getElementById('mbc-step1');
    const step2 = document.getElementById('mbc-step2');
    const btn2  = document.getElementById('search-overlay-btn');

    if (step1) {
        step1.classList.remove('mbc-step--active');
        step1.classList.add('mbc-step--done');
    }
    if (step2) {
        step2.classList.remove('mbc-step--pending');
        step2.classList.add('mbc-step--active');
    }
    if (btn2) btn2.disabled = false;
}

// ── ブランドバッジ ツールチップ ───────────────────────────────────────────
function bindBrandBadgeTooltip() {
    const badge = document.getElementById('map-brand-badge');
    if (!badge) return;

    let hideTimer = null;

    const show = () => {
        clearTimeout(hideTimer);
        badge.classList.add('tooltip-visible');
        hideTimer = setTimeout(() => badge.classList.remove('tooltip-visible'), 3000);
    };

    badge.addEventListener('click', show);
    badge.addEventListener('touchstart', show, { passive: true });
}

// ── 下部パネル折りたたみ + スワイプジェスチャー ──────────────────────────
function bindBottomPanelToggle() {
    const handle   = document.getElementById('map-bottom-handle');
    const controls = document.getElementById('map-bottom-controls');
    if (!handle || !controls) return;

    function _isEarthquakeMode() {
        return controls.classList.contains('mbc-earthquake-active');
    }

    // 地震モードの3段階: 'collapsed' | 'normal' | 'expanded'
    function _getEqState() {
        if (controls.classList.contains('mbc-collapsed')) return 'collapsed';
        if (controls.classList.contains('mbc-earthquake-expanded')) return 'expanded';
        return 'normal';
    }

    function _setEqState(state) {
        controls.classList.remove('mbc-collapsed');
        controls.classList.remove('mbc-earthquake-expanded');
        if (state === 'collapsed') controls.classList.add('mbc-collapsed');
        else if (state === 'expanded') controls.classList.add('mbc-earthquake-expanded');
        _updateExpandHint();
    }

    function _updateExpandHint() {
        const hint = document.getElementById('mbc-expand-hint');
        if (!hint) return;
        const labels = { collapsed: '一覧を開く', normal: '一覧を広げる', expanded: '一覧を縮める' };
        hint.textContent = labels[_getEqState()] || '';
    }

    // クリック（デスクトップ / 短タップ）
    // 地震モード: collapsed → normal → expanded → collapsed のサイクル
    handle.addEventListener('click', () => {
        if (_isEarthquakeMode()) {
            const state = _getEqState();
            if (state === 'collapsed') _setEqState('normal');
            else if (state === 'normal')   _setEqState('expanded');
            else                           _setEqState('collapsed');
        } else {
            controls.classList.toggle('mbc-collapsed');
        }
    });

    // スワイプジェスチャー（上 = 拡張方向、下 = 縮小方向）
    const SWIPE_THRESHOLD = 50; // px
    let touchStartY = null;

    handle.addEventListener('touchstart', (e) => {
        touchStartY = e.touches[0].clientY;
    }, { passive: true });

    handle.addEventListener('touchmove', (e) => {
        e.stopPropagation();
    }, { passive: true });

    handle.addEventListener('touchend', (e) => {
        if (touchStartY === null) return;
        const dy = touchStartY - e.changedTouches[0].clientY;
        if (Math.abs(dy) >= SWIPE_THRESHOLD) {
            if (_isEarthquakeMode()) {
                const state = _getEqState();
                if (dy > 0) {
                    // 上スワイプ → より大きく
                    if (state === 'collapsed') _setEqState('normal');
                    else if (state === 'normal') _setEqState('expanded');
                } else {
                    // 下スワイプ → より小さく
                    if (state === 'expanded') _setEqState('normal');
                    else if (state === 'normal') _setEqState('collapsed');
                }
            } else {
                if (dy > 0) {
                    controls.classList.remove('mbc-collapsed');
                } else {
                    controls.classList.add('mbc-collapsed');
                }
            }
        }
        touchStartY = null;
    }, { passive: true });
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

// ── 現在地ボタン（右上）: 地図を現在地にセンタリング ────────────────────────
function bindLocateMapButton() {
    const btn = document.getElementById('locate-map-btn');
    if (!btn) return;
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        // 手動選択モードをクリアして watchPosition に制御を戻す
        if (typeof exitManualLocationMode === 'function') exitManualLocationMode();
        if (typeof currentLocation !== 'undefined' && currentLocation) {
            map.setView([currentLocation.lat, currentLocation.lon], 15, { animate: true });
            // 非ナビ情報パネルを現在地データで更新
            if (typeof fetchCurrentLocInfo === 'function') {
                fetchCurrentLocInfo(
                    currentLocation.lat,
                    currentLocation.lon,
                    currentLocation.elevation ?? null
                );
            }
        }
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

// ── 都道府県チェックボックスの DOM 生成 + バインド ────────────────────────
// SHELTER_REGION_CONFIGS (config.js) からオーバーレイパネルとサイドバー両方に
// チェックボックスを生成し、双方向同期 + 表示フラグ更新をバインドする。
// 新しいリージョンは config.js への1行追加で自動反映される。
function _buildAndBindRegionToggles() {
    const panelList   = document.getElementById('shelterPanel_regionList');
    const sideList    = document.getElementById('shelterSidebar_regionList');

    SHELTER_REGION_CONFIGS.forEach(r => {
        // ── パネル側 ──
        if (panelList) {
            const label = document.createElement('label');
            label.className = 'shelter-panel-item';
            label.innerHTML = `
                <input type="checkbox" id="${r.panelId}"${r.defaultOn ? ' checked' : ''}>
                <span class="shelter-panel-dot" style="background:${r.dotColor};"></span>
                ${r.label}`;
            panelList.appendChild(label);
        }

        // ── サイドバー側 ──
        if (sideList) {
            const label = document.createElement('label');
            label.className = 'manual-location-toggle';
            label.setAttribute('for', r.sidebarId);
            label.innerHTML = `<input type="checkbox" id="${r.sidebarId}"${r.defaultOn ? ' checked' : ''}> ${r.label}`;
            sideList.appendChild(label);
        }
    });

    // DOM 生成後にバインド
    SHELTER_REGION_CONFIGS.forEach(r => _syncRegionBinding(r.key, r.panelId, r.sidebarId));
}

// 個別リージョンのバインド（_syncRegion から改名して外部化）
function _syncRegionBinding(regionKey, panelId, sideId) {
    const panelEl = document.getElementById(panelId);
    const sideEl  = document.getElementById(sideId);
    const _update = (checked) => {
        shelterRegionVisible[regionKey] = checked;
        scheduleEmergencyShelterRefresh();
        if (typeof onBrowseRegionFilterChanged === 'function') onBrowseRegionFilterChanged();
    };
    if (panelEl) {
        panelEl.addEventListener('change', () => {
            if (sideEl) sideEl.checked = panelEl.checked;
            _update(panelEl.checked);
        });
    }
    if (sideEl) {
        sideEl.addEventListener('change', () => {
            if (panelEl) panelEl.checked = sideEl.checked;
            _update(sideEl.checked);
        });
    }
}

// ── 避難場所チェックボックス初期化（レイヤーパネルに統合済み） ─────────────
function initShelterControls() {
    const panelEl1 = document.getElementById('shelterPanel_evacuation');
    const panelEl2 = document.getElementById('shelterPanel_emergency');
    const sideEl1  = document.getElementById('showEmergencyShelters');
    const sideEl2  = document.getElementById('showEmergencyEvacuationSites');

    // パネル内 ↔ サイドバー側を双方向同期
    const _syncToSide = (panelEl, sideEl) => {
        if (!panelEl || !sideEl) return;
        panelEl.addEventListener('change', () => {
            sideEl.checked = panelEl.checked;
            sideEl.dispatchEvent(new Event('change'));
        });
        sideEl.addEventListener('change', () => {
            panelEl.checked = sideEl.checked;
        });
    };
    _syncToSide(panelEl1, sideEl1);
    _syncToSide(panelEl2, sideEl2);

    // 都道府県フィルター：SHELTER_REGION_CONFIGS から DOM 生成 + バインドを自動実行
    _buildAndBindRegionToggles();

    // 広域ブラウズレイヤートグル：パネル ↔ サイドバー双方向同期
    const panelBrowse = document.getElementById('shelterPanel_browse');
    const sideBrowse  = document.getElementById('showShelterBrowse');
    if (panelBrowse) {
        panelBrowse.addEventListener('change', () => {
            if (sideBrowse) sideBrowse.checked = panelBrowse.checked;
            if (typeof setShelterBrowseLayerVisible === 'function') setShelterBrowseLayerVisible(panelBrowse.checked);
        });
    }
    if (sideBrowse) {
        sideBrowse.addEventListener('change', () => {
            if (panelBrowse) panelBrowse.checked = sideBrowse.checked;
            if (typeof setShelterBrowseLayerVisible === 'function') setShelterBrowseLayerVisible(sideBrowse.checked);
        });
    }
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

    getHazardMenuConfigSafe().forEach(cat => {
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
            labelEl.dataset.layerKey = item.layerKey;

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.disabled = !item.enabled;
            cb.dataset.sourceCheckboxId = item.checkboxId;

            // 既存チェックボックスと双方向同期
            const sourceEl = document.getElementById(item.checkboxId);
            if (sourceEl) {
                cb.checked = sourceEl.checked;
                cb.disabled = sourceEl.disabled;
                // overlay 側もサイドバー側の canonical な change ハンドラを通す
                // ことで、実レイヤー切替・ステータス更新・エラー処理を一本化する。
                cb.addEventListener('change', () => {
                    if (cb.disabled) return;
                    dispatchMirroredCheckboxChange(sourceEl, cb.checked);
                });
                // サイドバー側が変わったときはオーバーレイにも反映
                sourceEl.addEventListener('change', () => {
                    cb.checked = sourceEl.checked;
                    cb.disabled = sourceEl.disabled;
                    labelEl.classList.toggle('disabled', sourceEl.disabled);
                });
            }

            labelEl.appendChild(cb);
            labelEl.appendChild(document.createTextNode(item.label));
            applyHazardPanelItemState(labelEl, cb, item);
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
                    if (cb.disabled) return;
                    dispatchMirroredCheckboxChange(sourceEl, cb.checked);
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

    // ── 避難場所セクション（元・右上パネルから移管） ──────────────────────
    const shelterSep = document.createElement('hr');
    shelterSep.style.cssText = 'margin:6px 0; border:none; border-top:1px solid rgba(0,0,0,0.12);';
    container.appendChild(shelterSep);

    const shelterHeader = document.createElement('div');
    shelterHeader.className = 'mou-panel-section-label';
    shelterHeader.textContent = '避難場所';
    shelterHeader.style.fontWeight = '700';
    container.appendChild(shelterHeader);

    const routingLabel = document.createElement('div');
    routingLabel.className = 'mou-panel-section-label';
    routingLabel.textContent = '避難候補（近傍ルーティング）';
    container.appendChild(routingLabel);

    [
        { id: 'shelterPanel_evacuation', color: '#2e7d32', label: '指定避難所',     checked: true },
        { id: 'shelterPanel_emergency',  color: '#c62828', label: '指定緊急避難場所', checked: true },
    ].forEach(item => {
        const lbl = document.createElement('label');
        lbl.className = 'shelter-panel-item';
        const cb  = document.createElement('input');
        cb.type = 'checkbox'; cb.id = item.id; cb.checked = item.checked;
        const dot = document.createElement('span');
        dot.className = 'shelter-panel-dot';
        dot.style.background = item.color;
        lbl.appendChild(cb); lbl.appendChild(dot);
        lbl.appendChild(document.createTextNode(' ' + item.label));
        container.appendChild(lbl);
    });

    const regionSep = document.createElement('hr');
    regionSep.style.cssText = 'margin:6px 0; border:none; border-top:1px solid rgba(0,0,0,0.12);';
    container.appendChild(regionSep);

    const regionLabel = document.createElement('div');
    regionLabel.className = 'mou-panel-section-label';
    regionLabel.textContent = '都道府県';
    container.appendChild(regionLabel);

    const regionList = document.createElement('div');
    regionList.id = 'shelterPanel_regionList';
    container.appendChild(regionList);

    const browseSep = document.createElement('hr');
    browseSep.style.cssText = 'margin:6px 0; border:none; border-top:1px solid rgba(0,0,0,0.12);';
    container.appendChild(browseSep);

    const browseLabel = document.createElement('div');
    browseLabel.className = 'mou-panel-section-label';
    browseLabel.textContent = '広域ブラウズ（zoom≥11）';
    container.appendChild(browseLabel);

    const browseLbl = document.createElement('label');
    browseLbl.className = 'shelter-panel-item';
    const browseCb = document.createElement('input');
    browseCb.type = 'checkbox'; browseCb.id = 'shelterPanel_browse'; browseCb.checked = true;
    const browseDot = document.createElement('span');
    browseDot.className = 'shelter-panel-dot';
    browseDot.style.cssText = 'background:#5c6bc0;border:1px solid rgba(0,0,0,0.15);';
    browseLbl.appendChild(browseCb); browseLbl.appendChild(browseDot);
    browseLbl.appendChild(document.createTextNode(' 全地域を一覧表示'));
    container.appendChild(browseLbl);

    const browseStatus = document.createElement('div');
    browseStatus.id = 'shelterBrowseStatus';
    browseStatus.className = 'shelter-browse-status';
    container.appendChild(browseStatus);

    const navDebugSep = document.createElement('hr');
    navDebugSep.style.cssText = 'margin:6px 0; border:none; border-top:1px solid rgba(0,0,0,0.12);';
    container.appendChild(navDebugSep);

    const navDebugLabel = document.createElement('div');
    navDebugLabel.className = 'mou-panel-section-label';
    navDebugLabel.textContent = 'ナビイベント';
    container.appendChild(navDebugLabel);

    const navDebugToggleLabel = document.createElement('label');
    navDebugToggleLabel.className = 'shelter-panel-item';
    const navDebugToggle = document.createElement('input');
    navDebugToggle.type = 'checkbox';
    navDebugToggle.id = 'nav-debug-layer-toggle';
    navDebugToggle.checked = typeof window.isNavigationDebugLayerVisible === 'function'
        ? !!window.isNavigationDebugLayerVisible()
        : false;
    navDebugToggle.addEventListener('change', () => {
        try {
            window.setNavigationDebugLayerVisible?.(navDebugToggle.checked);
        } catch (_) {
            // debug layer toggle must remain best-effort
        }
    });
    navDebugToggleLabel.appendChild(navDebugToggle);
    navDebugToggleLabel.appendChild(document.createTextNode(' ナビイベント表示'));
    container.appendChild(navDebugToggleLabel);

    const navDebugActions = document.createElement('div');
    navDebugActions.className = 'nav-debug-layer-actions';
    const navDebugClearBtn = document.createElement('button');
    navDebugClearBtn.type = 'button';
    navDebugClearBtn.id = 'nav-debug-layer-clear-btn';
    navDebugClearBtn.className = 'nav-debug-layer-btn';
    navDebugClearBtn.textContent = 'クリア';
    navDebugClearBtn.addEventListener('click', () => {
        try {
            window.clearNavigationDebugEvents?.();
        } catch (_) {
            // best-effort
        }
    });
    navDebugActions.appendChild(navDebugClearBtn);
    container.appendChild(navDebugActions);

    const navDebugStatus = document.createElement('div');
    navDebugStatus.id = 'nav-debug-layer-status';
    navDebugStatus.className = 'nav-debug-layer-status';
    navDebugStatus.textContent = '0 / 100 events';
    container.appendChild(navDebugStatus);

    panel.appendChild(container);
    syncHazardLayerPanelState();
    if (typeof window.syncNavigationDebugLayerControls === 'function') {
        window.syncNavigationDebugLayerControls();
    }
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

    // 地震震度凡例セクションを追加
    const intensityEntries = [
        ['#3c9be8', '震度1'],
        ['#39c468', '震度2'],
        ['#f9c74f', '震度3'],
        ['#f8961e', '震度4'],
        ['#f3722c', '震度5弱'],
        ['#e53935', '震度5強'],
        ['#b71c1c', '震度6弱'],
        ['#880e4f', '震度6強'],
        ['#4a148c', '震度7'],
        ['#9e9e9e', '震度不明'],
    ];
    const eqSection = document.createElement('div');
    eqSection.innerHTML = `
        <hr class="legend-section-sep">
        <div class="legend-section-title">地震マーカー（震度）</div>
        ${intensityEntries.map(([color, label]) => `
            <div class="legend-item">
                <div class="legend-color" style="background:${color};"></div>
                <span>${label}</span>
            </div>`).join('')}
    `;
    panel.appendChild(eqSection);

    // 雨量レーダー凡例スロット（rain-layer.js が内容を管理）
    const rainSep = document.createElement('hr');
    rainSep.className = 'legend-section-sep';
    panel.appendChild(rainSep);

    const rainLegendEl = document.createElement('div');
    rainLegendEl.id = 'rain-legend';
    rainLegendEl.style.display = 'none';
    panel.appendChild(rainLegendEl);
}

// ── レイヤーパネル トグル ─────────────────────────────────────────────────
function bindLayerPanelToggle() {
    const btn        = document.getElementById('layer-toggle-btn');
    if (!btn) return;
    const panel      = document.getElementById('layer-panel');
    const legendBtn  = document.getElementById('legend-toggle-btn');
    const legendPanel = document.getElementById('legend-panel');

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        mapUiState.layerPanelOpen = !mapUiState.layerPanelOpen;
        panel.style.display = mapUiState.layerPanelOpen ? 'block' : 'none';
        btn.classList.toggle('map-overlay-btn--active', mapUiState.layerPanelOpen);

        // 凡例パネルを閉じる
        if (mapUiState.layerPanelOpen) {
            if (mapUiState.legendPanelOpen) {
                mapUiState.legendPanelOpen = false;
                legendPanel.style.display = 'none';
                legendBtn.classList.remove('map-overlay-btn--active');
            }
        }
    });
}

// ── 凡例パネル トグル ─────────────────────────────────────────────────────
function bindLegendPanelToggle() {
    const btn        = document.getElementById('legend-toggle-btn');
    if (!btn) return;
    const panel      = document.getElementById('legend-panel');
    const layerBtn   = document.getElementById('layer-toggle-btn');
    const layerPanel = document.getElementById('layer-panel');

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        mapUiState.legendPanelOpen = !mapUiState.legendPanelOpen;
        panel.style.display = mapUiState.legendPanelOpen ? 'block' : 'none';
        btn.classList.toggle('map-overlay-btn--active', mapUiState.legendPanelOpen);

        // レイヤーパネルを閉じる
        if (mapUiState.legendPanelOpen) {
            if (mapUiState.layerPanelOpen) {
                mapUiState.layerPanelOpen = false;
                layerPanel.style.display = 'none';
                layerBtn.classList.remove('map-overlay-btn--active');
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
            const lp = document.getElementById('layer-panel');
            const lb = document.getElementById('layer-toggle-btn');
            if (lp) lp.style.display = 'none';
            if (lb) lb.classList.remove('map-overlay-btn--active');
        }
        if (mapUiState.legendPanelOpen) {
            mapUiState.legendPanelOpen = false;
            const lgp = document.getElementById('legend-panel');
            const lgb = document.getElementById('legend-toggle-btn');
            if (lgp) lgp.style.display = 'none';
            if (lgb) lgb.classList.remove('map-overlay-btn--active');
        }
    });
}

// ── 起動 ─────────────────────────────────────────────────────────────────
// app.js より後にロードされる前提。DOM は既に準備済み。
window.addEventListener('load', () => {
    initMapOverlayUI();
});

window.addEventListener('hazard-layer-state-change', () => {
    syncHazardLayerPanelState();
});
