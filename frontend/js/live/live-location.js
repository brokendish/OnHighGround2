'use strict';
// live-location.js — 現在地パルス表示 + 現在地ボタン
// liveMap に依存。navigation.js / state.js には依存しない。

(function () {

    let _marker        = null;
    let _accCircle     = null;

    const _icon = L.divIcon({
        className:  '',
        html:       '<div class="live-location-dot"></div>',
        iconSize:   [18, 18],
        iconAnchor: [9, 9],
    });

    function _update(pos) {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const acc = pos.coords.accuracy;

        if (!_marker) {
            _marker = L.marker([lat, lng], {
                icon:          _icon,
                zIndexOffset:  1000,
                interactive:   false,
            }).addTo(liveMap);
        } else {
            _marker.setLatLng([lat, lng]);
        }

        if (acc > 0) {
            if (!_accCircle) {
                _accCircle = L.circle([lat, lng], {
                    radius:      acc,
                    color:       '#58a6ff',
                    weight:      1,
                    fillColor:   '#58a6ff',
                    fillOpacity: 0.07,
                    interactive: false,
                }).addTo(liveMap);
            } else {
                _accCircle.setLatLng([lat, lng]);
                _accCircle.setRadius(acc);
            }
        }
    }

    function _noop() {}

    // ── 現在地ボタン（マップ右下コントロール）────────────────────────────────

    const LocateControl = L.Control.extend({
        options: { position: 'bottomright' },

        onAdd() {
            const btn = L.DomUtil.create('button', 'live-locate-btn');
            btn.title = '現在地を表示';
            btn.setAttribute('aria-label', '現在地を表示');
            btn.innerHTML =
                '<svg viewBox="0 0 24 24" width="17" height="17" fill="none"' +
                ' stroke="currentColor" stroke-width="2"' +
                ' stroke-linecap="round" stroke-linejoin="round">' +
                '<circle cx="12" cy="12" r="3"/>' +
                '<path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>' +
                '<circle cx="12" cy="12" r="8" stroke-opacity="0.35"/>' +
                '</svg>';

            L.DomEvent.on(btn, 'click', (e) => {
                L.DomEvent.stopPropagation(e);
                if (_marker) {
                    liveMap.setView(_marker.getLatLng(), Math.max(liveMap.getZoom(), 11));
                    return;
                }
                navigator.geolocation?.getCurrentPosition((pos) => {
                    _update(pos);
                    liveMap.setView([pos.coords.latitude, pos.coords.longitude], 12);
                }, _noop, { enableHighAccuracy: true, timeout: 10000 });
            });

            return btn;
        },
    });

    new LocateControl().addTo(liveMap);

    // 自動開始（許可済みの場合は即パルス表示）
    if ('geolocation' in navigator) {
        navigator.geolocation.watchPosition(_update, _noop, {
            enableHighAccuracy: true,
            timeout:            15000,
            maximumAge:         30000,
        });
    }

})();
