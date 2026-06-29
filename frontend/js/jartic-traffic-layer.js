'use strict';

/**
 * jartic-traffic-layer.js — JARTIC 交通量観測点レイヤー
 *
 * showJarticTrafficLayer()   → レイヤー表示（現在の地図 BBOX 内の観測点のみ）
 * hideJarticTrafficLayer()   → レイヤー非表示
 * isJarticTrafficLayerVisible() → boolean
 * refreshJarticTrafficLayer() → 現在の BBOX で観測点を再取得・再描画
 *
 * 地図の移動・ズーム後は refreshJarticTrafficLayer() を呼ぶと
 * 新しい表示範囲に合わせて再描画する。
 */

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

function _jtCreateMarker(item) {
    const marker = L.circleMarker([item.lat, item.lon], {
        radius:      7,
        color:       '#1565c0',
        weight:      1.5,
        fillColor:   '#42a5f5',
        fillOpacity: 0.75,
        opacity:     0.9,
        className:   'jartic-traffic-marker',
    });

    const unitLabel  = item.unit  === '5min' ? '5分値' : (item.unit || '-');
    const typeLabel  = item.type  || '-';
    const extraRows  = (item.unit || item.type)
        ? `<tr><td>集計単位</td><td>${_jtEsc(unitLabel)}</td></tr>
           <tr><td>データ種別</td><td>${_jtEsc(typeLabel)}</td></tr>`
        : '';

    const popupHtml = `
<div class="jt-popup">
  <div class="jt-popup-title">交通量観測点</div>
  <table class="jt-popup-table">
    <tr><td>上り</td><td>${_jtFmt(item.up)}</td></tr>
    <tr><td>下り</td><td>${_jtFmt(item.down)}</td></tr>
    <tr><td>合計</td><td>${_jtFmt(item.total)}</td></tr>
    <tr><td>小型</td><td>${_jtFmt(item.small)}</td></tr>
    <tr><td>大型</td><td>${_jtFmt(item.large)}</td></tr>
    <tr><td>観測時刻</td><td>${_jtFmtTime(item.observed_at)}</td></tr>
    <tr><td>観測点コード</td><td>${_jtEsc(item.code)}</td></tr>
    ${extraRows}
  </table>
  <div class="jt-popup-source">出典: JARTIC / 国土交通省交通量API</div>
</div>`;

    marker.bindPopup(popupHtml, { maxWidth: 220 });
    return marker;
}

// ── データ取得・描画 ──────────────────────────────────────────────────────────

async function _jtFetchAndDraw() {
    if (!_jtVisible) return;

    const bbox = _jtCurrentBbox();
    const url  = '/api/jartic/traffic' + (bbox ? `?bbox=${encodeURIComponent(bbox)}` : '');

    let data;
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        data = await res.json();
    } catch (err) {
        console.warn('[jartic-traffic] fetch failed:', err);
        return;
    }

    if (!_jtLayer) return;
    _jtLayer.clearLayers();

    if (data.status !== 'ok' || !Array.isArray(data.items)) return;

    data.items.forEach(item => {
        if (item.lat == null || item.lon == null) return;
        const marker = _jtCreateMarker(item);
        _jtLayer.addLayer(marker);
    });
}

// ── CSS インジェクション ──────────────────────────────────────────────────────

function _jtInjectStyles() {
    if (document.getElementById('jt-layer-style')) return;
    const style = document.createElement('style');
    style.id = 'jt-layer-style';
    style.textContent = `
.jt-popup { font-size: 12px; min-width: 160px; }
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
.jt-popup-source {
    margin-top: 6px;
    font-size: 10px;
    color: #888;
}
`;
    document.head.appendChild(style);
}

// ── 地図移動イベント連携 ──────────────────────────────────────────────────────

let _jtMapBound = false;

function _jtBindMapEvents() {
    if (_jtMapBound) return;
    const m = _jtGetMap();
    if (!m || typeof m.on !== 'function') return;
    m.on('moveend zoomend', () => {
        if (_jtVisible) _jtFetchAndDraw();
    });
    _jtMapBound = true;
}

// ── 公開API ───────────────────────────────────────────────────────────────────

function showJarticTrafficLayer() {
    if (_jtVisible) return;
    _jtVisible = true;
    _jtInjectStyles();

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
    if (_jtLayer) {
        _jtLayer.clearLayers();
        const m = _jtGetMap();
        if (m && typeof m.removeLayer === 'function') {
            m.removeLayer(_jtLayer);
        }
    }
}

function isJarticTrafficLayerVisible() {
    return _jtVisible;
}

async function refreshJarticTrafficLayer() {
    if (!_jtVisible) return;
    await _jtFetchAndDraw();
}

window.showJarticTrafficLayer    = showJarticTrafficLayer;
window.hideJarticTrafficLayer    = hideJarticTrafficLayer;
window.isJarticTrafficLayerVisible = isJarticTrafficLayerVisible;
window.refreshJarticTrafficLayer = refreshJarticTrafficLayer;
