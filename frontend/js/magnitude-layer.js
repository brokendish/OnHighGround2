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
        lat1 = Number(lat1);
        lng1 = Number(lng1);
        lat2 = Number(lat2);
        lng2 = Number(lng2);
        if (![lat1, lng1, lat2, lng2].every(Number.isFinite)) return null;

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

    function _hasUsableLocation(pos) {
        if (pos?.lat == null || pos?.lon == null) return false;
        return !!pos && Number.isFinite(Number(pos.lat)) && Number.isFinite(Number(pos.lon));
    }

    function _hasUsableQuakeLocation(q) {
        if (q?.lat == null || q?.lng == null) return false;
        return Number.isFinite(Number(q?.lat)) && Number.isFinite(Number(q?.lng));
    }

    // 震度ベースの色分け（気象庁カラーに準拠）
    const _INTENSITY_COLORS = {
        '1':   '#3c9be8',  // 青
        '2':   '#39c468',  // 緑
        '3':   '#f9c74f',  // 黄
        '4':   '#f8961e',  // 橙
        '5弱': '#f3722c',  // 濃橙
        '5強': '#e53935',  // 赤
        '6弱': '#b71c1c',  // 濃赤
        '6強': '#880e4f',  // 赤紫
        '7':   '#4a148c',  // 紫
    };

    function _pinColor(maxIntensity) {
        return _INTENSITY_COLORS[maxIntensity] || '#9e9e9e'; // 不明=灰
    }

    function _pinRadius(magnitude) {
        const value = Number(magnitude);
        if (!Number.isFinite(value)) return 8;
        if (value >= 7)   return 20;
        if (value >= 6)   return 16;
        if (value >= 5)   return 13;
        if (value >= 4)   return 10;
        return 8;
    }

    function _popupHtml(q, userPos) {
        const time = q.occurred_at
            ? new Date(q.occurred_at).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
            : '—';
        const magValue = Number(q.magnitude);
        const mag  = Number.isFinite(magValue) ? `M${magValue.toFixed(1)}` : 'M—';
        const dep  = q.depth_km  != null ? `${q.depth_km}km` : '不明';
        const tsunamiInfo = q.tsunami_info || 'なし';
        const tsun = tsunamiInfo !== 'なし'
            ? `<div style="color:#c62828;font-weight:600;">津波: ${_escapeHtml(tsunamiInfo)}</div>`
            : `<div>津波: ${_escapeHtml(tsunamiInfo)}</div>`;
        const dist = _hasUsableLocation(userPos) && _hasUsableQuakeLocation(q)
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
            if (!_hasUsableQuakeLocation(q)) return;
            const color  = _pinColor(q.max_intensity);
            const radius = _pinRadius(q.magnitude);
            const isNew  = newEventIds.has(String(q.event_id));

            const marker = L.circleMarker([Number(q.lat), Number(q.lng)], {
                radius,
                color: '#fff',
                weight: 1.5,
                fillColor: color,
                fillOpacity: 0.85,
            }).addTo(map);
            marker.bindPopup(_popupHtml(q, userPos));
            marker._quakeId = String(q.event_id);
            marker.on('click', () => {
                if (typeof selectEarthquakeListItem === 'function') {
                    selectEarthquakeListItem(q.event_id);
                }
            });
            _pins.push(marker);

            // 新着ピンに外周パルスリングを追加
            if (isNew) {
                const ring = L.circleMarker([Number(q.lat), Number(q.lng)], {
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
