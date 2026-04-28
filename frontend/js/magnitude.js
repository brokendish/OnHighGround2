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

    // 差分ハイライト管理
    let _knownEventIds         = new Set(); // 同一セッション中維持
    let _firstLoadCompleted    = false;     // 初回取得済みフラグ
    let _highlightTimers       = [];        // setTimeout ハンドル

    // ── 差分判定 ──────────────────────────────────────────────────────────────
    function _detectNewQuakes(items) {
        const newIds = new Set();

        if (!_firstLoadCompleted) {
            // 初回は全件を既知として登録し NEW は返さない
            items.forEach(item => { if (item.event_id) _knownEventIds.add(String(item.event_id)); });
            _firstLoadCompleted = true;
            return newIds;
        }

        items.forEach(item => {
            if (!item.event_id) return;
            const id = String(item.event_id);
            if (!_knownEventIds.has(id)) newIds.add(id);
            _knownEventIds.add(id);
        });

        return newIds;
    }

    function _clearHighlightTimers() {
        _highlightTimers.forEach(t => clearTimeout(t));
        _highlightTimers = [];
    }

    function _showNewCount(count) {
        const el = document.getElementById('magnitude-new-count');
        if (!el) return;
        if (count > 0) {
            el.textContent = `新着地震 ${count}件`;
            el.style.display = 'block';
            const t = setTimeout(() => { el.style.display = 'none'; }, 20000);
            _highlightTimers.push(t);
        } else {
            el.style.display = 'none';
        }
    }

    // ── 取得・描画 ────────────────────────────────────────────────────────────
    async function _load() {
        const seq = ++_loadSeq;
        const list = document.getElementById('magnitude-list');
        if (list) list.innerHTML = '<div class="mq-loading">読み込み中…</div>';

        const refreshBtn = document.getElementById('magnitude-refresh-btn');
        if (refreshBtn) refreshBtn.disabled = true;

        try {
            const resp = await fetch('/api/earthquakes');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data   = await resp.json();
            const quakes = data.items || [];
            if (!_active || seq !== _loadSeq) return;

            const newIds  = _detectNewQuakes(quakes);
            const userPos = (typeof currentLocation !== 'undefined' && currentLocation)
                ? { lat: currentLocation.lat, lon: currentLocation.lon }
                : null;

            _clearHighlightTimers();

            if (typeof renderEarthquakePins === 'function') renderEarthquakePins(quakes, userPos, newIds);
            if (typeof renderEarthquakeList === 'function') renderEarthquakeList(quakes, userPos, newIds);

            _showNewCount(newIds.size);

            // 60秒後にピンのハイライトリングを解除
            if (newIds.size > 0) {
                const t = setTimeout(() => {
                    if (!_active) return;
                    if (typeof clearNewHighlights === 'function') clearNewHighlights();
                }, 60000);
                _highlightTimers.push(t);
            }
        } catch (err) {
            if (!_active || seq !== _loadSeq) return;
            console.error('地震情報取得失敗:', err);
            const list2 = document.getElementById('magnitude-list');
            if (list2) list2.innerHTML = '<div class="mq-error">データを取得できませんでした</div>';
        } finally {
            if (_active && refreshBtn) refreshBtn.disabled = false;
        }
    }

    // ── 避難所制御 ────────────────────────────────────────────────────────────
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

    // ── モード切替 ────────────────────────────────────────────────────────────
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
        _clearHighlightTimers();

        const newCount = document.getElementById('magnitude-new-count');
        if (newCount) newCount.style.display = 'none';

        if (typeof clearEarthquakePins === 'function') clearEarthquakePins();
        if (typeof clearEarthquakeList === 'function') clearEarthquakeList();

        _restoreShelters();
        // _knownEventIds と _firstLoadCompleted はセッション中維持
    }

    window.toggleMagnitudeMode = function () {
        if (_active) _exit(); else _enter();
    };

    window.isMagnitudeModeActive = function () {
        return _active;
    };

    // 更新ボタンから呼び出す
    window.magnitudeReload = function () {
        if (!_active) return;
        _load();
    };
})();
