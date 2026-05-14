'use strict';

/**
 * tide-markers.js — 全国潮位観測地点マーカーレイヤー
 *
 * showTideMarkers()          → 全国マーカーを地図に追加・ズームアウト
 * hideTideMarkers()          → マーカー非表示・selectedTideStation をリセット
 * isTideMarkersVisible()     → boolean
 * tideMarkersSetSelected(id) → 選択中マーカーを強調・他を通常に戻す
 */

let _tmLayer    = null;   // L.LayerGroup
let _tmVisible  = false;
let _tmStations = null;   // [{id, name, lat, lon, prefecture, has_data}]
let _tmMarkers  = {};     // station_id → L.Marker
let _tmSelectedId = null;
let _tmSavedView  = null; // { center, zoom } — showTideMarkers 前の地図状態

// ── アイコン ──────────────────────────────────────────────────────────

function _tmBuildIcon(selected) {
    const size  = selected ? 32 : 22;
    const fill  = selected ? '#1e40af' : '#2563eb';
    const ring  = selected
        ? 'stroke="#ffffff" stroke-width="2.5"'
        : 'stroke="#93c5fd" stroke-width="1"';
    const wave1 = 'M3 15 Q5.5 11.5 8 15 Q10.5 18.5 13 15 Q15.5 11.5 18 15 Q20.5 18.5 23 15';
    const wave2 = 'M3 11 Q5.5 7.5 8 11 Q10.5 14.5 13 11 Q15.5 7.5 18 11 Q20.5 14.5 23 11';
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 26 26">
        <circle cx="13" cy="13" r="12" fill="${fill}" ${ring}/>
        <path d="${wave1}" stroke="white" stroke-width="2.2" fill="none" stroke-linecap="round"/>
        <path d="${wave2}" stroke="white" stroke-width="1.4" fill="none" stroke-linecap="round" opacity="0.55"/>
    </svg>`;
    return L.divIcon({
        html: svg,
        className: '',
        iconSize:   [size, size],
        iconAnchor: [size / 2, size / 2],
        popupAnchor:[0, -(size / 2 + 2)],
    });
}

// ── データ取得 ────────────────────────────────────────────────────────

async function _tmFetchStations() {
    if (_tmStations !== null) return _tmStations;
    try {
        const res = await fetch('/api/tide/stations');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _tmStations = (data.stations || []).filter(s => s.has_data);
    } catch (err) {
        console.warn('[tide-markers] stations fetch failed:', err);
        _tmStations = [];
    }
    return _tmStations;
}

// ── マーカー生成 ──────────────────────────────────────────────────────

function _tmCreateMarker(station) {
    const marker = L.marker([station.lat, station.lon], {
        icon: _tmBuildIcon(station.id === _tmSelectedId),
        title: station.name,
        zIndexOffset: 200,
    });
    marker.bindTooltip(station.name, {
        permanent: false,
        direction: 'top',
        offset: [0, -14],
    });
    marker.on('click', () => {
        tideMarkersSetSelected(station.id);
        if (typeof _tideSetStation === 'function') {
            _tideSetStation(station);
        }
    });
    return marker;
}

// ── 公開 API ─────────────────────────────────────────────────────────

async function showTideMarkers() {
    if (_tmVisible) return;

    // 現在の地図ビューを保存
    if (typeof map !== 'undefined') {
        _tmSavedView = { center: map.getCenter(), zoom: map.getZoom() };
    }

    const stations = await _tmFetchStations();

    if (!_tmLayer) _tmLayer = L.layerGroup();
    _tmLayer.clearLayers();
    _tmMarkers = {};

    stations.forEach(station => {
        const marker = _tmCreateMarker(station);
        _tmMarkers[station.id] = marker;
        _tmLayer.addLayer(marker);
    });

    if (typeof map !== 'undefined') {
        _tmLayer.addTo(map);
        map.setView([36.5, 136.0], 5, { animate: true });
    }
    _tmVisible = true;
}

function hideTideMarkers() {
    if (!_tmVisible) return;
    if (typeof map !== 'undefined') {
        if (_tmLayer) map.removeLayer(_tmLayer);
        // ON 前の地図ビューを復元
        if (_tmSavedView) {
            map.setView(_tmSavedView.center, _tmSavedView.zoom, { animate: true });
        }
    }
    _tmSavedView  = null;
    _tmSelectedId = null;
    _tmVisible    = false;
    if (typeof _tideResetToNearest === 'function') {
        _tideResetToNearest();
    }
}

function isTideMarkersVisible() {
    return _tmVisible;
}

function tideMarkersSetSelected(id) {
    const prev = _tmSelectedId;
    _tmSelectedId = id;

    if (prev && _tmMarkers[prev]) {
        _tmMarkers[prev].setIcon(_tmBuildIcon(false));
    }
    if (id && _tmMarkers[id]) {
        _tmMarkers[id].setIcon(_tmBuildIcon(true));
    }
}
