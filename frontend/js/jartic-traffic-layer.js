'use strict';

/**
 * jartic-traffic-layer.js — JARTIC 交通量観測点レイヤー（道路交通量）
 *
 * showJarticTrafficLayer()   → レイヤー表示（現在の地図 BBOX 内の観測点のみ）
 * hideJarticTrafficLayer()   → レイヤー非表示
 * isJarticTrafficLayerVisible() → boolean
 * refreshJarticTrafficLayer() → 現在の BBOX で観測点を再取得・再描画
 *
 * 地図の移動・ズーム後は自動的にデバウンスして再取得する。
 *
 * 色分け・カテゴリ・凡例文言は /live 側 (frontend/js/live/live-road-traffic-layer.js
 * の _STATUS_COLOR、backend/app/models/live_road_traffic.py の STATUS_LABEL) と
 * 同一の意味・値を使用する。通常画面独自の判定基準は追加しない（Phase 7-B.3）。
 */

// ── ステータス色・文言（/live の live-road-traffic-layer.js / live_road_traffic.py と同一値） ──

const _JT_STATUS_COLOR = {
    very_high: '#dc2626',  // 赤
    high:      '#d97706',  // 黄
    normal:    '#22c55e',  // 緑
    low:       '#1f6feb',  // 青
    very_low:  '#7c3aed',  // 紫
    unknown:   '#9ca3af',  // グレー
};

const _JT_STATUS_LABEL = {
    very_high: '交通量非常に多い',
    high:      '交通量多い',
    normal:    '通常',
    low:       '交通量少ない',
    very_low:  '交通量極端に少ない',
    unknown:   '状態不明',
};

// 凡例表示順（交通量が多い側から）
const _JT_STATUS_ORDER = ['very_high', 'high', 'normal', 'low', 'very_low', 'unknown'];

// /live 側 (live-road-traffic-layer.js _buildPopup) と文言を完全一致させる
const _JT_DISCLAIMER = '交通量APIの値から推定した交通影響であり、通行止め・規制を断定するものではありません。';

// 低ズーム閾値・デバウンス間隔は hazard-layers.js の HAZARD_MIN_ZOOM(11) /
// shelters.js の scheduleEmergencyShelterRefresh(250ms) に合わせる（描画負荷対策の既存基準を踏襲）。
const _JT_MIN_ZOOM        = 11;
const _JT_DEBOUNCE_MS     = 250;

let _jtLayer   = null;   // L.LayerGroup
let _jtVisible = false;

function _jtGetMap() {
    if (typeof map !== 'undefined' && map) return map;
    if (typeof window.map !== 'undefined' && window.map) return window.map;
    return null;
}

// ── BBOX 文字列生成 ───────────────────────────────────────────────────────────

function _jtCurrentBbox() {
    const m = _jtGetMap();
    if (!m || typeof m.getBounds !== 'function') return null;
    const b = m.getBounds();
    const sw = b.getSouthWest();
    const ne = b.getNorthEast();
    return `${sw.lng.toFixed(6)},${sw.lat.toFixed(6)},${ne.lng.toFixed(6)},${ne.lat.toFixed(6)}`;
}

// ── 値フォーマット ─────────────────────────────────────────────────────────────

function _jtFmt(v) {
    if (v === null || v === undefined) return '-';
    return `${v}台`;
}

function _jtEsc(v) {
    return String(v ?? '-')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function _jtFmtTime(s) {
    if (!s) return '-';
    try {
        const d = new Date(s);
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        const hh = String(d.getHours()).padStart(2, '0');
        const mi = String(d.getMinutes()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
    } catch (_) {
        return _jtEsc(s);
    }
}

// ── マーカー生成 ──────────────────────────────────────────────────────────────
// 避難所マーカー（丸みのあるSVGアイコン）との誤認を防ぐため、道路交通量マーカーは
// 四角形＋白枠のdivIconで描画する（Phase 7-B.3.1）。L.circleMarkerでは四角化できない
// ため L.marker + L.divIcon へ変更。pane は circleMarker 時代と同じ overlayPane を
// 明示指定し、既存の重なり順（避難経路・現在地等との相対関係）を変えない。
const _JT_MARKER_SIZE = 13; // px（推奨範囲 11〜14px）

function _jtCreateMarker(item) {
    const status = item.status && _JT_STATUS_COLOR[item.status] ? item.status : 'unknown';
    const color  = _JT_STATUS_COLOR[status];
    const size   = _JT_MARKER_SIZE;

    const icon = L.divIcon({
        className:   '',
        html:        `<div class="jartic-traffic-marker jartic-traffic-status-${status}" style="background-color:${color};"></div>`,
        iconSize:    [size, size],
        iconAnchor:  [size / 2, size / 2],
        popupAnchor: [0, -size / 2],
    });

    const marker = L.marker([item.lat, item.lon], {
        icon,
        pane: 'overlayPane', // circleMarker時代と同一paneを維持し重なり順を変えない
    });

    const unitLabel   = item.unit  === '5min' ? '5分値' : (item.unit || '-');
    const typeLabel    = item.type  || '-';
    const extraRows    = (item.unit || item.type)
        ? `<tr><td>集計単位</td><td>${_jtEsc(unitLabel)}</td></tr>
           <tr><td>データ種別</td><td>${_jtEsc(typeLabel)}</td></tr>`
        : '';

    const statusLabel     = item.status_label      || _JT_STATUS_LABEL[status];
    const statusUpLabel   = item.status_up_label   || '-';
    const statusDownLabel = item.status_down_label || '-';

    const popupHtml = `
<div class="jt-popup">
  <div class="jt-popup-title">交通量観測点</div>
  <table class="jt-popup-table">
    <tr><td>状態</td><td><span class="jt-popup-status-dot" style="background:${color}"></span>${_jtEsc(statusLabel)}</td></tr>
    <tr><td>上り</td><td>${_jtFmt(item.up)}</td></tr>
    <tr><td>状態（上り）</td><td>${_jtEsc(statusUpLabel)}</td></tr>
    <tr><td>下り</td><td>${_jtFmt(item.down)}</td></tr>
    <tr><td>状態（下り）</td><td>${_jtEsc(statusDownLabel)}</td></tr>
    <tr><td>合計</td><td>${_jtFmt(item.total)}</td></tr>
    <tr><td>小型</td><td>${_jtFmt(item.small)}</td></tr>
    <tr><td>大型</td><td>${_jtFmt(item.large)}</td></tr>
    <tr><td>観測時刻</td><td>${_jtFmtTime(item.observed_at)}</td></tr>
    <tr><td>観測点コード</td><td>${_jtEsc(item.code)}</td></tr>
    ${extraRows}
  </table>
  <div class="jt-popup-disclaimer">${_jtEsc(_JT_DISCLAIMER)}</div>
  <div class="jt-popup-source">出典: JARTIC / 国土交通省交通量API</div>
</div>`;

    marker.bindPopup(popupHtml, { maxWidth: 240 });
    return marker;
}

// ── ステータス表示（低ズーム・0件・エラー） ─────────────────────────────────────

let _jtLastMessageLogged = false;

function _jtSetStatusText(text) {
    const el = document.getElementById('jartic-traffic-status');
    if (el) el.textContent = text || '';
}

// ── データ取得・描画 ──────────────────────────────────────────────────────────

let _jtAbortController = null;
let _jtFetchToken = 0;

async function _jtFetchAndDraw() {
    if (!_jtVisible) return;

    const m = _jtGetMap();
    const zoom = m && typeof m.getZoom === 'function' ? m.getZoom() : null;
    if (zoom !== null && zoom < _JT_MIN_ZOOM) {
        if (_jtLayer) _jtLayer.clearLayers();
        _jtSetStatusText('地図を拡大すると道路交通量を表示します');
        return;
    }

    const bbox = _jtCurrentBbox();
    const url  = '/api/jartic/traffic' + (bbox ? `?bbox=${encodeURIComponent(bbox)}` : '');

    if (_jtAbortController) _jtAbortController.abort();
    const controller = new AbortController();
    _jtAbortController = controller;
    const token = ++_jtFetchToken;

    let data;
    try {
        const res = await fetch(url, { signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        data = await res.json();
    } catch (err) {
        if (err && err.name === 'AbortError') return;
        if (!_jtLastMessageLogged) {
            console.warn('[jartic-traffic] fetch failed:', err);
            _jtLastMessageLogged = true;
        }
        if (token === _jtFetchToken) {
            _jtSetStatusText('道路交通量：取得できません');
        }
        return;
    }

    // 表示範囲移動・レイヤーOFFなどで既に無効化された古いレスポンスは破棄
    if (token !== _jtFetchToken || !_jtVisible || !_jtLayer) return;

    _jtLayer.clearLayers();
    _jtLastMessageLogged = false;

    if (data.status !== 'ok' || !Array.isArray(data.items)) {
        _jtSetStatusText('道路交通量：取得できません');
        return;
    }

    if (data.items.length === 0) {
        _jtSetStatusText('この範囲に交通量観測点はありません');
        return;
    }

    _jtSetStatusText('');
    data.items.forEach(item => {
        if (item.lat == null || item.lon == null) return;
        const marker = _jtCreateMarker(item);
        _jtLayer.addLayer(marker);
    });
}

// ── デバウンス ────────────────────────────────────────────────────────────────

let _jtDebounceTimer = null;

function _jtScheduleFetch() {
    if (_jtDebounceTimer) clearTimeout(_jtDebounceTimer);
    _jtDebounceTimer = setTimeout(() => {
        _jtDebounceTimer = null;
        _jtFetchAndDraw();
    }, _JT_DEBOUNCE_MS);
}

// ── CSS インジェクション ──────────────────────────────────────────────────────

function _jtInjectStyles() {
    if (document.getElementById('jt-layer-style')) return;
    const style = document.createElement('style');
    style.id = 'jt-layer-style';
    style.textContent = `
.jartic-traffic-marker {
    box-sizing: border-box;
    width: 100%;
    height: 100%;
    border: 2px solid #fff;
    border-radius: 1px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.55);
}
.jt-popup { font-size: 12px; min-width: 180px; }
.jt-popup-title {
    font-weight: 700;
    font-size: 13px;
    margin-bottom: 6px;
    color: #1565c0;
}
.jt-popup-table { border-collapse: collapse; width: 100%; }
.jt-popup-table td {
    padding: 2px 4px;
    border-bottom: 1px solid #e0e0e0;
}
.jt-popup-table td:first-child {
    color: #555;
    white-space: nowrap;
    padding-right: 8px;
}
.jt-popup-status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 4px;
}
.jt-popup-disclaimer {
    margin-top: 6px;
    font-size: 10px;
    color: #8b949e;
}
.jt-popup-source {
    margin-top: 4px;
    font-size: 10px;
    color: #888;
}
`;
    document.head.appendChild(style);
}

// ── 凡例（凡例パネル #jartic-traffic-legend スロットに描画） ─────────────────────

function _jtLegendBuild() {
    const el = document.getElementById('jartic-traffic-legend');
    if (!el || el.dataset.built) return;

    const title = document.createElement('div');
    title.className   = 'jt-legend-title';
    title.textContent = '道路交通量';
    el.appendChild(title);

    const rows = document.createElement('div');
    rows.className = 'jt-legend-rows';
    _JT_STATUS_ORDER.forEach(status => {
        const row = document.createElement('div');
        row.className = 'jt-legend-row';
        row.innerHTML = `<span class="jt-legend-swatch" style="background:${_JT_STATUS_COLOR[status]}"></span>`
                      + `<span class="jt-legend-label">${_jtEsc(_JT_STATUS_LABEL[status])}</span>`;
        rows.appendChild(row);
    });
    el.appendChild(rows);

    const src = document.createElement('div');
    src.className   = 'jt-legend-source';
    src.textContent = '出典: JARTIC / 国土交通省交通量API（/live と共通の分類）';
    el.appendChild(src);

    el.dataset.built = '1';
}

function _jtLegendShow() {
    const el = document.getElementById('jartic-traffic-legend');
    if (!el) return;
    _jtLegendBuild();
    el.style.display = '';
}

function _jtLegendHide() {
    const el = document.getElementById('jartic-traffic-legend');
    if (el) el.style.display = 'none';
}

// ── 地図移動イベント連携 ──────────────────────────────────────────────────────

let _jtMapBound = false;

function _jtBindMapEvents() {
    if (_jtMapBound) return;
    const m = _jtGetMap();
    if (!m || typeof m.on !== 'function') return;
    m.on('moveend zoomend', () => {
        if (_jtVisible) _jtScheduleFetch();
    });
    _jtMapBound = true;
}

// ── 公開API ───────────────────────────────────────────────────────────────────

function showJarticTrafficLayer() {
    if (_jtVisible) return;
    _jtVisible = true;
    _jtInjectStyles();
    _jtLegendShow();

    if (!_jtLayer) {
        _jtLayer = L.layerGroup();
    }
    const m = _jtGetMap();
    if (m && typeof m.addLayer === 'function') {
        m.addLayer(_jtLayer);
    }
    _jtBindMapEvents();
    _jtFetchAndDraw();
}

function hideJarticTrafficLayer() {
    _jtVisible = false;
    if (_jtDebounceTimer) {
        clearTimeout(_jtDebounceTimer);
        _jtDebounceTimer = null;
    }
    if (_jtAbortController) {
        _jtAbortController.abort();
        _jtAbortController = null;
    }
    _jtFetchToken += 1; // 進行中の応答を無効化
    if (_jtLayer) {
        _jtLayer.clearLayers();
        const m = _jtGetMap();
        if (m && typeof m.removeLayer === 'function') {
            m.removeLayer(_jtLayer);
        }
    }
    _jtSetStatusText('');
    _jtLegendHide();
}

function isJarticTrafficLayerVisible() {
    return _jtVisible;
}

async function refreshJarticTrafficLayer() {
    if (!_jtVisible) return;
    await _jtFetchAndDraw();
}

window.showJarticTrafficLayer      = showJarticTrafficLayer;
window.hideJarticTrafficLayer      = hideJarticTrafficLayer;
window.isJarticTrafficLayerVisible = isJarticTrafficLayerVisible;
window.refreshJarticTrafficLayer   = refreshJarticTrafficLayer;
