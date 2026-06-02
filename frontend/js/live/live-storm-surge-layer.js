'use strict';
// live-storm-surge-layer.js — /live 高潮警報マップレイヤー
// /api/live/storm_surge/warnings のデータを地図上に表示する。
// navigation.js / state.js に一切依存しない。

(function () {

    // ── 定数 ─────────────────────────────────────────────────────────────────

    const _LEVEL_COLOR = {
        emergency: '#7c3aed',
        warning:   '#dc2626',
        advisory:  '#d97706',
    };

    const _LEVEL_LABEL = {
        emergency: '高潮特別警報',
        warning:   '高潮警報',
        advisory:  '高潮注意報',
    };

    const _LEVEL_RADIUS = {
        emergency: 22,
        warning:   18,
        advisory:  14,
    };

    // ── 状態 ─────────────────────────────────────────────────────────────────
    // toggle-storm-surge の初期状態（checked）に合わせて enabled=true で開始する

    let _layerGroup  = null;
    let _enabled     = true;
    let _lastData    = null;

    // ── アイコン生成 ─────────────────────────────────────────────────────────

    function _buildIcon(level) {
        const color = _LEVEL_COLOR[level] || '#dc2626';
        const size  = _LEVEL_RADIUS[level] || 18;
        const r     = size / 2;
        const short = level === 'emergency' ? '特別' : level === 'warning' ? '高潮警' : '高潮注';
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size * 2}" height="${size * 2}" viewBox="0 0 ${size * 2} ${size * 2}">
            <polygon points="${size},2 ${size * 2 - 2},${size * 2 - 2} 2,${size * 2 - 2}"
                     fill="${color}" stroke="white" stroke-width="2"/>
            <text x="${size}" y="${size * 2 - 5}" text-anchor="middle" fill="white"
                  font-size="${Math.max(7, r - 3)}" font-weight="bold" font-family="sans-serif">${short}</text>
        </svg>`;
        return L.divIcon({
            html:        svg,
            className:   '',
            iconSize:    [size * 2, size * 2],
            iconAnchor:  [size, size],
            popupAnchor: [0, -(size + 4)],
        });
    }

    // ── データ取得 ────────────────────────────────────────────────────────────

    async function _fetchData() {
        const res = await fetch('/api/live/storm_surge/warnings');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    // ── レンダリング ─────────────────────────────────────────────────────────

    function _render(data) {
        if (!_layerGroup) _layerGroup = L.layerGroup();
        _layerGroup.clearLayers();

        const areas = (data && data.areas) || [];
        areas.forEach(area => {
            const lat = area.lat;
            const lng = area.lng;
            if (lat == null || lng == null) return;

            const level = area.level === 'danger' ? 'warning' : 'advisory';
            const detail = area.detail || _LEVEL_LABEL[level] || '高潮情報';
            const color = _LEVEL_COLOR[level] || '#dc2626';

            const marker = L.marker([lat, lng], {
                icon:         _buildIcon(level),
                zIndexOffset: 600,
                title:        area.label,
            });
            marker.bindPopup(
                `<div style="min-width:160px">` +
                `<div style="font-weight:bold;color:${color}">${detail}</div>` +
                `<div>${area.label}</div>` +
                `</div>`
            );
            _layerGroup.addLayer(marker);
        });

        if (_enabled) _layerGroup.addTo(liveMap);
    }

    // ── 公開 API ──────────────────────────────────────────────────────────────

    async function refresh() {
        const data = await _fetchData();
        _lastData = data;
        if (_enabled) _render(data);
        const count = (data.areas || []).length;
        console.info(`live storm surge summary: areas=${count}`);
        return data;
    }

    function setData(data) {
        _lastData = data;
        if (_enabled) _render(data);
    }

    function setVisible(visible) {
        _enabled = visible;
        if (!_layerGroup) _layerGroup = L.layerGroup();
        if (visible) {
            if (_lastData) {
                _render(_lastData);
            } else {
                refresh()
                    .then(() => window.liveUI?.updateStormSurgeStatus?.(true))
                    .catch(e => {
                        console.warn('[live-storm-surge] 取得失敗:', e);
                        window.liveUI?.updateStormSurgeStatus?.(false);
                    });
            }
        } else {
            liveMap.removeLayer(_layerGroup);
        }
    }

    window.liveStormSurgeLayer = { setVisible, refresh, setData };

})();
