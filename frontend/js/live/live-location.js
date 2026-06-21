'use strict';
// live-location.js — 現在地パルス表示 + 現在地ボタン
// liveMap に依存。navigation.js / state.js には依存しない。

(function () {

    let _marker        = null;
    let _accCircle     = null;
    let _btn           = null;

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
                zIndexOffset:  100000,  // 道路ラベル等の前面に確実に表示
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

        // ボタンのエラー表示を解除
        if (_btn) {
            _btn.classList.remove('live-locate-btn--error');
            _btn.title = '現在地に移動';
        }
    }

    function _onError(err) {
        if (!_btn) return;
        // GeolocationPositionError: 1=PERMISSION_DENIED, 2=POSITION_UNAVAILABLE, 3=TIMEOUT
        const msg = err.code === 1 ? '位置情報の許可が必要です'
                  : err.code === 2 ? '位置情報を取得できません'
                  : '位置情報の取得がタイムアウトしました';
        _btn.classList.add('live-locate-btn--error');
        _btn.title = msg;
    }

    // ── 現在地ボタン（レイヤーパネル下部）──────────────────────────────────

    const _panel = document.getElementById('live-layer-panel');
    if (_panel) {
        const sep = document.createElement('hr');
        sep.className = 'live-panel-sep';

        _btn = document.createElement('button');
        _btn.className = 'live-locate-btn';
        _btn.title = '現在地を表示';
        _btn.setAttribute('aria-label', '現在地を表示');
        _btn.innerHTML =
            '<svg viewBox="0 0 24 24" width="15" height="15" fill="none"' +
            ' stroke="currentColor" stroke-width="2"' +
            ' stroke-linecap="round" stroke-linejoin="round">' +
            '<circle cx="12" cy="12" r="3"/>' +
            '<path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>' +
            '<circle cx="12" cy="12" r="8" stroke-opacity="0.35"/>' +
            '</svg>' +
            '<span>現在地</span>';

        _btn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (_marker) {
                liveMap.setView(_marker.getLatLng(), Math.max(liveMap.getZoom(), 11));
                return;
            }
            if (!navigator.geolocation) {
                _btn.classList.add('live-locate-btn--error');
                _btn.title = 'このブラウザは位置情報に対応していません';
                return;
            }
            navigator.geolocation.getCurrentPosition((pos) => {
                _update(pos);
                liveMap.setView([pos.coords.latitude, pos.coords.longitude], 12);
            }, _onError, { enableHighAccuracy: true, timeout: 10000 });
        });

        _panel.appendChild(sep);
        _panel.appendChild(_btn);
    }

    // 自動開始（許可済みの場合は即パルス表示）
    if ('geolocation' in navigator) {
        navigator.geolocation.watchPosition(_update, _onError, {
            enableHighAccuracy: true,
            timeout:            15000,
            maximumAge:         30000,
        });
    }

})();
