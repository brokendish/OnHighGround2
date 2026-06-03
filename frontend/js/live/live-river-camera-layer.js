'use strict';
// live-river-camera-layer.js — 河川ライブカメラ公式リンクレイヤー (Phase 6-A)
// navigation.js / state.js に一切依存しない。
// 動画埋め込み・スクレイピングは行わず、公式ページへの導線のみ提供する。

(function () {

    const _DATA_URL = '/data/live/river_cameras.json';

    const _layerGroup = L.layerGroup().addTo(liveMap);
    let _enabled = false;
    let _cameras = [];

    // ─────────────────────────────────────────────────────────────────────────
    // アイコン
    // ─────────────────────────────────────────────────────────────────────────

    function _makeIcon() {
        return L.divIcon({
            html: '<span style="font-size:18px;line-height:1;cursor:pointer;" title="河川ライブカメラ">📷</span>',
            className: '',
            iconSize:    [22, 22],
            iconAnchor:  [11, 11],
            popupAnchor: [0, -14],
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // ポップアップ HTML
    // ─────────────────────────────────────────────────────────────────────────

    function _esc(str) {
        return String(str == null ? '' : str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _popupHtml(cam) {
        const link = cam.url
            ? `<a href="${_esc(cam.url)}" target="_blank" rel="noopener noreferrer">[公式ライブカメラを開く]</a>`
            : '';
        return [
            `<b>${_esc(cam.name || '不明')}</b>`,
            `河川: ${_esc(cam.river || '-')}`,
            `管理者: ${_esc(cam.agency || '-')}`,
            link,
        ].filter(Boolean).join('<br>');
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 描画
    // ─────────────────────────────────────────────────────────────────────────

    function _render() {
        _layerGroup.clearLayers();
        if (!_enabled) return;
        const icon = _makeIcon();
        _cameras.forEach(cam => {
            if (cam.lat == null || cam.lng == null) return;
            L.marker([cam.lat, cam.lng], { icon })
                .bindPopup(_popupHtml(cam))
                .addTo(_layerGroup);
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 公開 API
    // ─────────────────────────────────────────────────────────────────────────

    async function init() {
        try {
            const res = await fetch(_DATA_URL);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            _cameras = Array.isArray(data) ? data : [];
            console.info(`live river cameras loaded: count=${_cameras.length}`);
            if (_enabled) _render();
            return true;
        } catch (e) {
            console.warn('live river cameras load failed', e.message);
            _cameras = [];
            return false;
        }
    }

    function setVisible(visible) {
        _enabled = visible;
        _render();
    }

    window.liveRiverCameraLayer = { init, setVisible };

})();
