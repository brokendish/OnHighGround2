'use strict';
// live-road-traffic-layer.js — 道路交通影響 地図レイヤー
// 観測点マーカーを状態別に色分けして表示する。
// 赤=交通量非常に多い（通行止めではない）を凡例で明示する。

(function () {

    // ── ステータス色定義 ─────────────────────────────────────────────────────

    const _STATUS_COLOR = {
        normal:      '#22c55e',  // 緑
        high:        '#d97706',  // 黄
        very_high:   '#dc2626',  // 赤
        low:         '#1f6feb',  // 青
        very_low:    '#7c3aed',  // 紫
        unknown:     '#9ca3af',  // グレー
        unavailable: '#6b7280',  // グレー
    };

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    const _layerGroup = L.layerGroup();
    const _renderer   = L.svg();
    let   _enabled    = false;
    let   _lastItems  = [];

    // ── エスケープ ────────────────────────────────────────────────────────────

    function _esc(v) {
        return String(v ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    // ── マーカーオプション ────────────────────────────────────────────────────

    function _markerOptions(status) {
        return {
            radius:      9,
            color:       '#fff',
            weight:      1.5,
            fillColor:   _STATUS_COLOR[status] || _STATUS_COLOR.unknown,
            fillOpacity: 0.85,
            renderer:    _renderer,
            className:   `road-traffic-${String(status || 'unknown').replaceAll('_', '-')}`,
        };
    }

    // ── ポップアップ ──────────────────────────────────────────────────────────

    function _buildPopup(item) {
        const road    = _esc(item.road_name || '不明');
        const dir     = _esc(item.direction || '');
        const label   = _esc(item.status_label || item.status || '状態不明');
        const v5      = item.volume_5min != null ? `${item.volume_5min} 台/5分` : '—';
        const v1h     = item.volume_1h   != null ? `${item.volume_1h} 台/時` : '—';
        const obs     = _esc(item.observed_at ? item.observed_at.replace('T', ' ').slice(0, 16) : '不明');
        const src     = _esc(item.source || '国土交通省 交通量API（JARTIC提供）');
        const dirHtml = dir ? `<br>方向: ${dir}` : '';

        return `
            <b>${road}</b>${dirHtml}<br>
            交通量 (5分値): ${v5}<br>
            交通量 (1時間値): ${v1h}<br>
            状態: <b>${label}</b><br>
            観測時刻: ${obs}<br>
            出典: <small>${src}</small><br>
            <small style="color:#8b949e">交通量APIの値から推定した交通影響であり、通行止め・規制を断定するものではありません。</small>
        `;
    }

    // ── 描画 ─────────────────────────────────────────────────────────────────

    function _render() {
        _layerGroup.clearLayers();
        if (!_enabled || !_lastItems.length) return;

        const seen = new Set();
        const sorted = [..._lastItems].sort((a, b) => b.severity - a.severity);

        sorted.forEach(item => {
            if (seen.has(item.station_id)) return;
            seen.add(item.station_id);

            if (item.lat == null || item.lng == null) return;

            L.circleMarker([item.lat, item.lng], _markerOptions(item.status))
                .bindPopup(_buildPopup(item))
                .addTo(_layerGroup);
        });
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    function setData(items) {
        _lastItems = Array.isArray(items) ? items : [];
        _render();
    }

    function setVisible(visible) {
        _enabled = visible;
        if (visible) {
            _layerGroup.addTo(liveMap);
            _render();
        } else {
            liveMap.removeLayer(_layerGroup);
        }
    }

    window.liveRoadTrafficLayer = { setData, setVisible };

})();
