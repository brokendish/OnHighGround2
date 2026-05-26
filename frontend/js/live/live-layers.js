'use strict';
// live-layers.js — /live 専用レイヤー管理（雨雲・キキクル・地震・津波）
// navigation.js / state.js に一切依存しない。

(function () {

    // ─────────────────────────────────────────────────────────────────────────
    // 雨雲レイヤー（JMA 降水ナウキャスト）
    // ─────────────────────────────────────────────────────────────────────────

    // JMA hrpns タイルは偶数ズームにのみデータがある（kikikuru-layer.js と同様の理由）
    const _RainTileLayer = L.TileLayer.extend({
        _clampZoom(zoom) {
            let z = L.TileLayer.prototype._clampZoom.call(this, zoom);
            if (z % 2 !== 0) z = Math.max(z - 1, 2);
            return z;
        },
    });

    let _rainLayer   = null;
    let _rainEnabled = true;

    async function _rainRefresh() {
        const res = await fetch('/api/weather/rain/tile/times');
        if (!res.ok) throw new Error(`[live-rain] HTTP ${res.status}`);
        const data = await res.json();
        if (!data || !Array.isArray(data.times) || !data.times.length) return;

        const current = data.times.find(t => t.offset_minutes === 0) || data.times[0];
        if (!current || !current.tile_url_template) return;

        if (_rainLayer) {
            liveMap.removeLayer(_rainLayer);
            _rainLayer = null;
        }
        if (!_rainEnabled) return;

        _rainLayer = new _RainTileLayer(current.tile_url_template, {
            opacity:       0.65,
            attribution:   '気象庁 降水ナウキャスト',
            minZoom:       1,
            maxNativeZoom: 10,
            maxZoom:       19,
            tileSize:      256,
            zIndex:        450,
        }).addTo(liveMap);
    }

    function _rainSetVisible(visible) {
        _rainEnabled = visible;
        if (visible) {
            _rainRefresh()
                .then(() => window.liveUI?.updateRainStatus?.(true))
                .catch((e) => {
                    console.warn('[live-rain] toggle ON 失敗:', e.message);
                    window.liveUI?.updateRainStatus?.(false);
                });
        } else {
            if (_rainLayer) {
                liveMap.removeLayer(_rainLayer);
                _rainLayer = null;
            }
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // キキクルレイヤー（気象庁 危険度分布タイル）
    // ─────────────────────────────────────────────────────────────────────────

    const _KIKIKURU_TIMES_URL = 'https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json';
    const _KIKIKURU_TILE_BASE = 'https://www.jma.go.jp/bosai/jmatile/data/risk';

    const _KIKIKURU_KINDS = {
        land:  { elem: 'land',       zIndex: 441 },
        flood: { elem: 'flood_mesh', zIndex: 442 },
        inund: { elem: 'inund',      zIndex: 440 },
    };

    const _KikikuruTileLayer = L.TileLayer.extend({
        _clampZoom(zoom) {
            let z = L.TileLayer.prototype._clampZoom.call(this, zoom);
            if (z % 2 !== 0) z = Math.max(z - 1, 4);
            return z;
        },
    });

    let _kikikuruEntry   = null;
    let _kikikuruEnabled = false;
    const _kikikuruLayers = { land: null, flood: null, inund: null };

    async function _kikikuruFetchEntry() {
        const res = await fetch(_KIKIKURU_TIMES_URL);
        if (!res.ok) throw new Error(`kikikuru times HTTP ${res.status}`);
        const arr = await res.json();
        if (!Array.isArray(arr) || !arr.length) throw new Error('kikikuru times empty');
        return arr[0];
    }

    function _kikikuruTileUrl(entry, elem) {
        return `${_KIKIKURU_TILE_BASE}/${entry.basetime}/${entry.member}/${entry.validtime}/surf/${elem}/{z}/{x}/{y}.png`;
    }

    function _kikikuruAddKind(kind) {
        if (!_kikikuruEntry) return;
        const def = _KIKIKURU_KINDS[kind];
        _kikikuruLayers[kind] = new _KikikuruTileLayer(_kikikuruTileUrl(_kikikuruEntry, def.elem), {
            opacity:       0.8,
            attribution:   '気象庁 危険度分布',
            minZoom:       1,
            maxNativeZoom: 10,
            maxZoom:       19,
            tileSize:      256,
            zIndex:        def.zIndex,
        }).addTo(liveMap);
    }

    function _kikikuruRemoveAll() {
        Object.keys(_kikikuruLayers).forEach(kind => {
            if (_kikikuruLayers[kind]) {
                liveMap.removeLayer(_kikikuruLayers[kind]);
                _kikikuruLayers[kind] = null;
            }
        });
    }

    async function _kikikuruSetVisible(visible) {
        _kikikuruEnabled = visible;
        _kikikuruRemoveAll();
        if (!visible) return;
        try {
            _kikikuruEntry = await _kikikuruFetchEntry();
            Object.keys(_KIKIKURU_KINDS).forEach(_kikikuruAddKind);
        } catch (e) {
            console.warn('[live-kikikuru] 取得失敗:', e);
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 地震マーカー
    // ─────────────────────────────────────────────────────────────────────────

    const _eqLayerGroup = L.layerGroup().addTo(liveMap);
    let _eqEnabled = true;
    let _eqData    = [];

    function _eqMagColor(mag) {
        if (mag >= 6.0) return '#cc0000';
        if (mag >= 5.0) return '#ff4444';
        if (mag >= 4.0) return '#ff8800';
        if (mag >= 3.0) return '#e3b341';
        return '#8b949e';
    }

    function _eqMagRadius(mag) {
        if (mag >= 6.0) return 18;
        if (mag >= 5.0) return 13;
        if (mag >= 4.0) return 9;
        if (mag >= 3.0) return 6;
        return 4;
    }

    function _eqRender() {
        _eqLayerGroup.clearLayers();
        if (!_eqEnabled) return;
        _eqData.forEach(eq => {
            const lat = eq.lat;
            const lng = eq.lng;
            if (lat == null || lng == null) return;
            const mag = eq.magnitude || 0;
            const intensity = eq.max_intensity || '-';
            const name = eq.epicenter_name || '不明';
            const at   = eq.occurred_at ? eq.occurred_at.slice(0, 16).replace('T', ' ') : '';

            L.circleMarker([lat, lng], {
                radius:      _eqMagRadius(mag),
                color:       '#fff',
                weight:      1,
                fillColor:   _eqMagColor(mag),
                fillOpacity: 0.85,
            }).bindPopup(
                `<b>${name}</b><br>M ${mag != null ? mag.toFixed(1) : '-'} / 震度 ${intensity}<br><small>${at}</small>`
            ).addTo(_eqLayerGroup);
        });
    }

    async function _eqRefresh() {
        const res = await fetch('/api/earthquakes?days=1');
        if (!res.ok) throw new Error(`[live-eq] HTTP ${res.status}`);
        const data = await res.json();
        _eqData = (data.items || []).slice(0, 50);
        _eqRender();
        return _eqData;
    }

    function _eqSetVisible(visible) {
        _eqEnabled = visible;
        _eqRender();
    }

    function _eqGetData() { return _eqData; }

    // ─────────────────────────────────────────────────────────────────────────
    // 津波情報（マーカーなし、データ取得のみ。表示は live-alert-panel.js が担当）
    // ─────────────────────────────────────────────────────────────────────────

    let _tsunamiData = null;

    async function _tsunamiRefresh() {
        const res = await fetch('/api/tsunami/warnings/current');
        if (!res.ok) throw new Error(`[live-tsunami] HTTP ${res.status}`);
        _tsunamiData = await res.json();
        return _tsunamiData;
    }

    function _tsunamiGetData() { return _tsunamiData; }

    // ─────────────────────────────────────────────────────────────────────────
    // 公開 API
    // ─────────────────────────────────────────────────────────────────────────

    window.liveLayers = {
        rain: {
            setVisible: _rainSetVisible,
            refresh:    _rainRefresh,
        },
        kikikuru: {
            setVisible: _kikikuruSetVisible,
        },
        earthquake: {
            setVisible: _eqSetVisible,
            refresh:    _eqRefresh,
            getData:    _eqGetData,
        },
        tsunami: {
            refresh:    _tsunamiRefresh,
            getData:    _tsunamiGetData,
        },
    };

})();
