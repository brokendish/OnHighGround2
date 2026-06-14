'use strict';
// live-train-layer.js — 鉄道運行影響 地図レイヤー
// MVPでは都道府県代表点にCircleMarkerを描画し、最悪ステータスで色分けする。
// 精密な路線GISは将来フェーズで実装予定。

(function () {

    // ── 状態定数 ─────────────────────────────────────────────────────────────

    const _STATUS_COLOR = {
        normal:             '#6b7280',
        delay:              '#d97706',
        partial_suspension: '#ea580c',
        suspended:          '#dc2626',
        unknown:            '#9ca3af',
        unavailable:        '#6b7280',
    };

    const _STATUS_SEVERITY = {
        normal:             0,
        unknown:            1,
        delay:              2,
        partial_suspension: 3,
        suspended:          4,
        unavailable:        9,
    };

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    const _layerGroup = L.layerGroup();
    const _renderer   = L.svg();
    let   _enabled    = false;
    let   _lastItems  = [];
    let   _matchedIds = new Set(); // OSMレイヤーでマッチ済みの railway_id

    // ── 描画 ─────────────────────────────────────────────────────────────────

    // 都道府県ごとに最悪ステータスを集約
    function _aggregateByScope(items) {
        const scope = {};
        items.forEach(item => {
            const key = item.operator_id || item.railway_id;
            if (!scope[item.railway_id]) {
                scope[item.railway_id] = item;
            }
        });
        return Object.values(scope);
    }

    function _markerOptions(status) {
        const color = _STATUS_COLOR[status] || _STATUS_COLOR.unknown;
        const options = {
            radius:      10,
            color:       '#fff',
            weight:      1.5,
            fillColor:   color,
            fillOpacity: 0.75,
            zIndex:      420,
            renderer:    _renderer,
            className:   `train-line-${String(status || 'unknown').replaceAll('_', '-')}`,
        };
        if (status === 'unavailable') {
            options.color = '#6b7280';
            options.fillOpacity = 0.15;
            options.dashArray = '4 4';
        }
        return options;
    }

    function _escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    function _buildPopup(item) {
        const operator = _escapeHtml(item.operator_name || '事業者不明');
        const line     = _escapeHtml(item.railway_name || '路線名不明');
        const badge    = _escapeHtml(item.status_label || item.status || '状態不明');
        const desc     = _escapeHtml(item.description || '');
        const updated  = _escapeHtml(item.updated_at || '更新時刻不明');
        const source   = _escapeHtml(item.source || 'ODPT');
        return `
            <b>${line}</b><br>
            事業者: ${operator}<br>
            状態: ${badge}<br>
            ${desc ? `説明: <small>${desc}</small><br>` : ''}
            更新時刻: ${updated}<br>
            出典: ${source}
        `;
    }

    function _render() {
        _layerGroup.clearLayers();
        if (!_enabled || !_lastItems.length) return;

        // 同一路線の重複を除去し severity 順に並べる
        const seen = new Set();
        const sorted = [..._lastItems].sort((a, b) => b.severity - a.severity);

        sorted.forEach(item => {
            if (seen.has(item.railway_id)) return;
            seen.add(item.railway_id);

            // OSMレイヤーで路線形状を表示済みならマーカー不要
            if (_matchedIds.has(item.railway_id)) return;

            // 座標なし → スキップ（未対応事業者のフォールバック）
            if (item.lat == null || item.lng == null) return;

            L.circleMarker([item.lat, item.lng], _markerOptions(item.status))
                .bindPopup(_buildPopup(item))
                .addTo(_layerGroup);
        });
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    function setData(items) {
        _lastItems = Array.isArray(items) ? items : [];
        // OSMレイヤーに障害データを渡し、マッチした路線IDを同期取得
        const matched = window.liveTrainOsmLayer?.setDisruptions?.(_lastItems);
        _matchedIds = matched instanceof Set ? matched : new Set();
        _render();
    }

    // OSMレイヤーがデータ取得後に呼び出す（マーカー表示の同期）
    function updateMatched(matched) {
        _matchedIds = matched instanceof Set ? matched : new Set();
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

    // パネルから「地図表示」ボタン押下時に使う
    function focusItem(item) {
        if (item.lat == null || item.lng == null) return;
        const zoom = Math.max(liveMap.getZoom(), 9);
        liveMap.flyTo([item.lat, item.lng], zoom);
        L.popup()
            .setLatLng([item.lat, item.lng])
            .setContent(_buildPopup(item))
            .openOn(liveMap);
    }

    window.liveTrainLayer = { setData, setVisible, focusItem, updateMatched };

})();
