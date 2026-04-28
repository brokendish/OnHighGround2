/**
 * magnitude-layer.js — 地震情報マーカーレイヤー
 *
 * 依存: Leaflet (map グローバル変数)
 */
(function () {
    const _pins  = [];
    const _rings = []; // 新着ピンの外周リングマーカー

    function _escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        }[ch]));
    }

    function _distanceKm(lat1, lng1, lat2, lng2) {
        const R = 6371;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLng = (lng2 - lng1) * Math.PI / 180;
        const a =
            Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * Math.PI / 180) *
            Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLng / 2) ** 2;
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    function _pinColor(occurredAt) {
        if (!occurredAt) return '#757575';
        const elapsed = Date.now() - new Date(occurredAt).getTime();
        const h = elapsed / 3600000;
        if (h < 1) return '#e53935'; // 赤（1時間以内）
        if (h < 3) return '#f57c00'; // 橙（3時間以内）
        if (h < 6) return '#f9a825'; // 黄（6時間以内）
        return '#757575';             // 灰
    }

    function _pinRadius(magnitude) {
        if (magnitude == null) return 8;
        if (magnitude >= 7)   return 20;
        if (magnitude >= 6)   return 16;
        if (magnitude >= 5)   return 13;
        if (magnitude >= 4)   return 10;
        return 8;
    }

    function _popupHtml(q, userPos) {
        const time = q.occurred_at
            ? new Date(q.occurred_at).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
            : '—';
        const mag  = q.magnitude != null ? `M${q.magnitude.toFixed(1)}` : 'M—';
        const dep  = q.depth_km  != null ? `${q.depth_km}km` : '不明';
        const tsunamiInfo = q.tsunami_info || 'なし';
        const tsun = tsunamiInfo !== 'なし'
            ? `<div style="color:#c62828;font-weight:600;">津波: ${_escapeHtml(tsunamiInfo)}</div>`
            : `<div>津波: ${_escapeHtml(tsunamiInfo)}</div>`;
        const dist = userPos && q.lat != null && q.lng != null
            ? `<div>距離: 約${Math.round(_distanceKm(userPos.lat, userPos.lon, q.lat, q.lng))}km</div>`
            : '<div>距離: 未取得</div>';
        return `<div style="font-size:13px;line-height:1.7;min-width:160px;">
            <strong>${_escapeHtml(q.epicenter_name)}</strong><br>
            発生時刻: ${_escapeHtml(time)}<br>
            震度: ${_escapeHtml(q.max_intensity || '不明')}<br>
            M: ${_escapeHtml(mag.replace(/^M/, ''))}<br>
            深さ: ${_escapeHtml(dep)}<br>
            ${tsun}${dist}
        </div>`;
    }

    window.clearEarthquakePins = function () {
        _pins.forEach(m => map.removeLayer(m));
        _pins.length = 0;
        _rings.forEach(m => map.removeLayer(m));
        _rings.length = 0;
    };

    window.renderEarthquakePins = function (quakes, userPos, newEventIds = new Set()) {
        clearEarthquakePins();
        quakes.forEach(q => {
            if (q.lat == null || q.lng == null) return;
            const color  = _pinColor(q.occurred_at);
            const radius = _pinRadius(q.magnitude);
            const isNew  = newEventIds.has(String(q.event_id));

            const marker = L.circleMarker([q.lat, q.lng], {
                radius,
                color: '#fff',
                weight: 1.5,
                fillColor: color,
                fillOpacity: 0.85,
            }).addTo(map);
            marker.bindPopup(_popupHtml(q, userPos));
            marker._quakeId = String(q.event_id);
            _pins.push(marker);

            // 新着ピンに外周パルスリングを追加
            if (isNew) {
                const ring = L.circleMarker([q.lat, q.lng], {
                    radius: radius + 6,
                    className: 'magnitude-ring-new',
                    fill: false,
                    color: '#ff5a3c',
                    weight: 3,
                    interactive: false,
                }).addTo(map);
                _rings.push(ring);
            }
        });
    };

    window.focusEarthquakePin = function (eventId) {
        const pin = _pins.find(p => p._quakeId === String(eventId));
        if (pin) {
            map.setView(pin.getLatLng(), 8, { animate: true });
            pin.openPopup();
        }
    };

    // 新着ハイライト（リングとリストバッジ）を解除する
    window.clearNewHighlights = function () {
        _rings.forEach(m => map.removeLayer(m));
        _rings.length = 0;
        document.querySelectorAll('.mq-item-new').forEach(el => el.classList.remove('mq-item-new'));
        document.querySelectorAll('.mq-new-badge').forEach(el => el.remove());
    };
})();
