/**
 * shelter-browse-layer.js — 避難場所広域ブラウズレイヤー（業務表示）
 *
 * ── 目的 ──────────────────────────────────────────────────────────────────
 * 地図上で避難場所の分布を広域に確認するための業務表示レイヤー。
 * ルーティング・避難候補選定を担う shelters.js（避難候補レイヤー）とは独立した
 * 別レイヤーとして実装する。
 *
 * ── ズームレベル別表示モード ──────────────────────────────────────────────
 *   zoom ≤ 10  : 非表示（広すぎて情報として意味をなさない）
 *   zoom 11-13 : MarkerCluster によるクラスター表示
 *   zoom ≥ 14  : MarkerCluster が自動的に個別マーカーを展開（disableClusteringAtZoom）
 *
 * ── 将来のリージョン追加 ──────────────────────────────────────────────────
 *   1. state.js の shelterRegionVisible にキーを追加する（例: saitama: true）
 *   2. 対応する避難所データを data_runtime/backend/shelters/ に配備する
 *   3. このファイルの変更は不要 — フィルターは shelterRegionVisible を自動参照する
 *
 * ── 設計判断 ──────────────────────────────────────────────────────────────
 *   - 全件を起動時に一括フェッチしてキャッシュする（bbox 無し）。
 *     理由: 広域ブラウズ目的では「どこに何件あるか」を見るためパン/ズームのたびに
 *           再フェッチする必要がない。バックエンドへの負荷も最小化できる。
 *   - shelters.js（避難候補レイヤー）は変更しない。
 *     理由: 避難候補 → ルーティングの既存ワークフローを破壊しないため。
 *   - zoom ≥ 14 で両レイヤーが重なる場合、ブラウズレイヤーのマーカーは
 *     低 opacity の細い線で描画し、避難候補マーカーが視覚的に前面に来るようにする。
 */

// ── 設定（変更する場合はここだけ編集） ───────────────────────────────────
const SHELTER_BROWSE_CONFIG = {
    // ズームモード閾値
    ZOOM_SHOW_MIN:            11,    // これ未満は非表示
    DISABLE_CLUSTERING_ZOOM:  14,    // このズーム以上で個別マーカーに展開

    // MarkerCluster チューニング
    MAX_CLUSTER_RADIUS:       55,    // クラスタリング半径 (px)
    CHUNK_INTERVAL_MS:        100,   // chunkedLoading のチャンク間隔

    // フェッチ設定
    FETCH_LIMIT:           15000,    // 全件取得上限（バックエンド max 20000）
    DEBOUNCE_MS:             300,

    // マーカー色
    COLOR_EES:          '#c62828',   // 指定緊急避難場所（赤系）
    COLOR_EVS:          '#2e7d32',   // 指定避難所（緑系）

    // ブラウズ層のマーカーは避難候補層より控えめに描画する
    MARKER_RADIUS:              5,
    MARKER_FILL_OPACITY:      0.55,
    MARKER_WEIGHT:              1,
};

// ── モジュール内部状態 ────────────────────────────────────────────────────
let _browseClusterGroup  = null;   // L.MarkerClusterGroup
let _browseAllData       = null;   // フェッチ済み全データキャッシュ (Array)
let _browseFetchState    = 'idle'; // 'idle' | 'loading' | 'loaded' | 'error'
let _browseDebounceTimer = null;

// ── ハザードラベル ────────────────────────────────────────────────────────
const _BROWSE_HAZARD_LABEL = {
    flood:        '洪水',
    landslide:    '崖崩れ・土石流',
    storm_surge:  '高潮',
    earthquake:   '地震',
    tsunami:      '津波',
    fire:         '大規模火事',
    inland_flood: '内水氾濫',
    volcano:      '火山現象',
};

// ── MarkerClusterGroup 初期化 ─────────────────────────────────────────────
function _initBrowseClusterGroup() {
    if (_browseClusterGroup) return true;

    if (typeof L.markerClusterGroup !== 'function') {
        console.warn('[shelter-browse] Leaflet.MarkerCluster が読み込まれていません。広域ブラウズレイヤーは無効です。');
        return false;
    }

    _browseClusterGroup = L.markerClusterGroup({
        maxClusterRadius:       SHELTER_BROWSE_CONFIG.MAX_CLUSTER_RADIUS,
        disableClusteringAtZoom: SHELTER_BROWSE_CONFIG.DISABLE_CLUSTERING_ZOOM,
        chunkedLoading:          true,
        chunkInterval:           SHELTER_BROWSE_CONFIG.CHUNK_INTERVAL_MS,
        animate:                 true,
        showCoverageOnHover:     false,
        // カスタムクラスターアイコン
        iconCreateFunction: (cluster) => {
            const count = cluster.getChildCount();
            const size  = count > 100 ? 'lg' : count > 20 ? 'md' : 'sm';
            const dim   = { sm: 30, md: 36, lg: 44 }[size];
            return L.divIcon({
                html:       `<div class="shelter-cluster shelter-cluster--${size}">${count}</div>`,
                className:  '',
                iconSize:   [dim, dim],
                iconAnchor: [dim / 2, dim / 2],
            });
        },
    });
    return true;
}

// ── ズーム可視判定 ────────────────────────────────────────────────────────
function _isBrowseZoomVisible() {
    return map.getZoom() >= SHELTER_BROWSE_CONFIG.ZOOM_SHOW_MIN;
}

// ── 地図上のレイヤー表示切り替え ──────────────────────────────────────────
function _applyBrowseMapVisibility() {
    if (!_browseClusterGroup) return;
    const shouldShow = isShelterBrowseLayerVisible && _isBrowseZoomVisible();
    if (shouldShow && !map.hasLayer(_browseClusterGroup)) {
        _browseClusterGroup.addTo(map);
    } else if (!shouldShow && map.hasLayer(_browseClusterGroup)) {
        map.removeLayer(_browseClusterGroup);
    }
}

// ── ポップアップ HTML ─────────────────────────────────────────────────────
function _buildBrowsePopupHtml(site) {
    const isEES  = site.category === 'emergency_evacuation_site';
    const color  = isEES ? SHELTER_BROWSE_CONFIG.COLOR_EES : SHELTER_BROWSE_CONFIG.COLOR_EVS;
    const label  = isEES ? '指定緊急避難場所' : '指定避難所';
    const icon   = isEES ? '🚨' : '🏠';
    const addr   = site.address
        ? `<div style="font-size:11px;color:#555;margin-bottom:4px;">📍 ${site.address}</div>`
        : '';
    const hazards = (site.hazard_types || [])
        .map(h => _BROWSE_HAZARD_LABEL[h] || h).join(' / ');
    const hazardHtml = hazards
        ? `<div style="font-size:11px;color:#555;margin-bottom:5px;">対応: ${hazards}</div>`
        : '';
    return `
        <div style="font-size:13px;font-weight:700;color:${color};margin-bottom:2px;">
            ${icon} ${site.name || label}
        </div>
        <div style="font-size:11px;color:#888;margin-bottom:4px;">${label}（広域ブラウズ）</div>
        ${addr}${hazardHtml}
        <div style="font-size:10px;color:#bbb;">
            ${Number(site.lat).toFixed(5)}, ${Number(site.lon).toFixed(5)}
        </div>`;
}

// ── クラスターグループへのマーカー充填 ───────────────────────────────────
function _populateBrowseCluster(data) {
    if (!_browseClusterGroup) return;
    _browseClusterGroup.clearLayers();

    // 都道府県フィルターを適用（_resolveShelterRegion は shelters.js で定義）
    const filtered = data.filter(site => {
        const region = typeof _resolveShelterRegion === 'function'
            ? _resolveShelterRegion(site)
            : (site.region || 'unknown');
        // shelterRegionVisible に登録されていないリージョンは常に表示する
        return shelterRegionVisible[region] !== false;
    });

    // マーカーを一括生成してバルク追加（パフォーマンス最適化）
    const markers = filtered.map(site => {
        const isEES  = site.category === 'emergency_evacuation_site';
        const color  = isEES ? SHELTER_BROWSE_CONFIG.COLOR_EES : SHELTER_BROWSE_CONFIG.COLOR_EVS;
        const m = L.circleMarker([site.lat, site.lon], {
            radius:      SHELTER_BROWSE_CONFIG.MARKER_RADIUS,
            color:       color,
            fillColor:   color,
            fillOpacity: SHELTER_BROWSE_CONFIG.MARKER_FILL_OPACITY,
            weight:      SHELTER_BROWSE_CONFIG.MARKER_WEIGHT,
            interactive: true,
        });
        m.bindPopup(_buildBrowsePopupHtml(site), { maxWidth: 240 });
        return m;
    });

    _browseClusterGroup.addLayers(markers);
    _setBrowseStatus(`${filtered.length.toLocaleString()} 件表示中`);
}

// ── ステータス表示 ────────────────────────────────────────────────────────
function _setBrowseStatus(msg, isError = false) {
    const ids = ['shelterBrowseStatus', 'shelterBrowseStatusSide'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (isError) {
            el.innerHTML = `${msg} <a href="#" style="color:#1565c0;text-decoration:underline;" onclick="event.preventDefault();_retryBrowseFetch()">再試行</a>`;
        } else {
            el.textContent = msg;
        }
    });
}

// ── リトライ（ステータスの「再試行」リンクから呼ばれる） ──────────────────
async function _retryBrowseFetch() {
    if (_browseFetchState === 'loading') return;
    _browseFetchState = 'idle'; // error → idle に戻してフェッチを許可
    _browseAllData = null;
    await refreshShelterBrowseLayer();
}

// ── データフェッチ ────────────────────────────────────────────────────────
async function _fetchAllBrowseShelters() {
    if (_browseFetchState === 'loading') return null;
    _browseFetchState = 'loading';
    _setBrowseStatus('読み込み中...');
    try {
        const params   = new URLSearchParams({ limit: String(SHELTER_BROWSE_CONFIG.FETCH_LIMIT) });
        const response = await apiFetch(`/emergency-shelters?${params}`);
        const data     = await response.json();
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

        _browseAllData   = data.data || [];
        _browseFetchState = 'loaded';
        return _browseAllData;
    } catch (err) {
        _browseFetchState = 'error';
        console.warn('[shelter-browse] データ取得失敗:', err);
        _setBrowseStatus('取得失敗', true);
        return null;
    }
}

// ── 公開: リフレッシュ ────────────────────────────────────────────────────
async function refreshShelterBrowseLayer() {
    if (!isShelterBrowseLayerVisible) return;
    if (!_browseClusterGroup) return;

    if (_browseFetchState !== 'loaded') {
        const data = await _fetchAllBrowseShelters();
        if (!data) return;
    }

    _populateBrowseCluster(_browseAllData);
    _applyBrowseMapVisibility();
}

function scheduleShelterBrowseRefresh() {
    if (_browseDebounceTimer) clearTimeout(_browseDebounceTimer);
    _browseDebounceTimer = setTimeout(refreshShelterBrowseLayer, SHELTER_BROWSE_CONFIG.DEBOUNCE_MS);
}

// ── 公開: レイヤー表示 ON/OFF ─────────────────────────────────────────────
async function setShelterBrowseLayerVisible(visible) {
    isShelterBrowseLayerVisible = visible;
    if (!visible) {
        if (_browseClusterGroup && map.hasLayer(_browseClusterGroup)) {
            map.removeLayer(_browseClusterGroup);
        }
        _setBrowseStatus('広域ブラウズ: OFF');
        return;
    }
    // error 状態でトグルONした場合は自動リトライ
    if (_browseFetchState === 'error') {
        _browseFetchState = 'idle';
        _browseAllData = null;
    }
    await refreshShelterBrowseLayer();
}

// ── 公開: 都道府県フィルター変更時の再描画 ───────────────────────────────
// map-overlay-ui.js の _syncRegion から呼ばれる
function onBrowseRegionFilterChanged() {
    if (!isShelterBrowseLayerVisible || _browseFetchState !== 'loaded') return;
    _populateBrowseCluster(_browseAllData);
    _applyBrowseMapVisibility();
}

// ── 初期化 ────────────────────────────────────────────────────────────────
function initShelterBrowseLayer() {
    if (!_initBrowseClusterGroup()) return; // MarkerCluster 未ロード時は中断

    // ズーム変化で表示/非表示を切り替え
    map.on('zoomend', _applyBrowseMapVisibility);

    // 初回データ取得 + 表示
    if (isShelterBrowseLayerVisible) {
        refreshShelterBrowseLayer();
    }

    console.debug('[shelter-browse] 初期化完了。設定:', SHELTER_BROWSE_CONFIG);
}

window.addEventListener('load', () => {
    initShelterBrowseLayer();
});
