/**
 * magnitude.js — Magnitude モード コントローラー
 *
 * 依存: magnitude-layer.js, magnitude-ui.js, Leaflet (map)
 */
(function () {
    let _active    = false;
    let _savedView = null;
    let _loadSeq   = 0;

    // 避難所レイヤーの一時退避
    let _savedShelterVisible    = false;
    let _savedEESVisible        = false;
    let _savedBrowseVisible     = false;
    let _shelterTemporarilyHid  = false;

    async function _load() {
        const seq = ++_loadSeq;
        const list = document.getElementById('magnitude-list');
        if (list) list.innerHTML = '<div class="mq-loading">読み込み中…</div>';

        try {
            const resp = await fetch('/api/earthquakes');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data   = await resp.json();
            const quakes = data.items || [];
            if (!_active || seq !== _loadSeq) return;

            const userPos = (typeof currentLocation !== 'undefined' && currentLocation)
                ? { lat: currentLocation.lat, lon: currentLocation.lon }
                : null;

            if (typeof renderEarthquakePins === 'function') renderEarthquakePins(quakes, userPos);
            if (typeof renderEarthquakeList === 'function') renderEarthquakeList(quakes, userPos);
        } catch (err) {
            if (!_active || seq !== _loadSeq) return;
            console.error('地震情報取得失敗:', err);
            const list = document.getElementById('magnitude-list');
            if (list) list.innerHTML = '<div class="mq-error">データを取得できませんでした</div>';
        }
    }

    function _hideShelters() {
        _savedShelterVisible = (typeof isEmergencyShelterVisible !== 'undefined') && isEmergencyShelterVisible;
        _savedEESVisible     = (typeof isEmergencyEvacuationSiteVisible !== 'undefined') && isEmergencyEvacuationSiteVisible;
        _savedBrowseVisible  = (typeof isShelterBrowseLayerVisible !== 'undefined') && isShelterBrowseLayerVisible;

        if (_savedShelterVisible || _savedEESVisible || _savedBrowseVisible) {
            if (typeof clearEmergencyShelterMarkers === 'function') clearEmergencyShelterMarkers();
            if (typeof hideShelterBrowseLayerForMagnitude === 'function') hideShelterBrowseLayerForMagnitude();
            _shelterTemporarilyHid = true;
        } else {
            _shelterTemporarilyHid = false;
        }

        const note = document.getElementById('magnitude-layer-note');
        if (note) note.style.display = 'block';
    }

    function _restoreShelters() {
        const note = document.getElementById('magnitude-layer-note');
        if (note) note.style.display = 'none';

        if (_shelterTemporarilyHid) {
            if (typeof scheduleEmergencyShelterRefresh === 'function') scheduleEmergencyShelterRefresh();
            if (_savedBrowseVisible && typeof restoreShelterBrowseLayerAfterMagnitude === 'function') {
                restoreShelterBrowseLayerAfterMagnitude();
                setTimeout(restoreShelterBrowseLayerAfterMagnitude, 500);
            }
        }
        _savedShelterVisible   = false;
        _savedEESVisible       = false;
        _savedBrowseVisible    = false;
        _shelterTemporarilyHid = false;
    }

    function _enter() {
        if (_active) return;
        _active = true;

        _hideShelters();

        _savedView = { center: map.getCenter(), zoom: map.getZoom() };
        map.setView([36.2048, 138.2529], 5, { animate: true });

        const panel = document.getElementById('magnitude-panel');
        if (panel) panel.style.display = 'flex';

        const btn = document.getElementById('magnitude-btn');
        if (btn) btn.classList.add('map-overlay-btn--active');

        _load();
    }

    function _exit() {
        if (!_active) return;
        _active = false;

        if (_savedView) {
            map.setView(_savedView.center, _savedView.zoom, { animate: true });
            _savedView = null;
        }

        const panel = document.getElementById('magnitude-panel');
        if (panel) panel.style.display = 'none';

        const btn = document.getElementById('magnitude-btn');
        if (btn) btn.classList.remove('map-overlay-btn--active');

        _loadSeq++;
        if (typeof clearEarthquakePins === 'function') clearEarthquakePins();
        if (typeof clearEarthquakeList === 'function') clearEarthquakeList();

        _restoreShelters();
    }

    window.toggleMagnitudeMode = function () {
        if (_active) _exit(); else _enter();
    };

    window.isMagnitudeModeActive = function () {
        return _active;
    };
})();
