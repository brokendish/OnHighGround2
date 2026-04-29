/**
 * magnitude.js — Magnitude モード コントローラー
 *
 * 依存: magnitude-layer.js, magnitude-ui.js, Leaflet (map)
 */
(function () {
    const DEFAULT_MAGNITUDE_POLL_INTERVAL_MS = 60_000;

    let _active    = false;
    let _savedView = null;
    let _loadSeq   = 0;

    // 避難所レイヤーの一時退避
    let _savedShelterVisible    = false;
    let _savedEESVisible        = false;
    let _savedBrowseVisible     = false;
    let _shelterTemporarilyHid  = false;

    // 差分ハイライト管理
    let _knownEventIds       = new Set(); // 同一セッション中維持
    let _firstLoadCompleted  = false;
    let _highlightTimers     = [];

    // ── ポーリング状態 ────────────────────────────────────────────────────────
    let _pollTimer        = null;
    let _polling          = false;
    let _pollInFlight     = false;
    let _loadInFlight     = false;
    let _pollFailureCount = 0;
    let _lastUpdatedAt    = null;

    function _pollIntervalMs() {
        const override = Number(window.__MAGNITUDE_POLL_INTERVAL_MS);
        return Number.isFinite(override) && override >= 100
            ? override
            : DEFAULT_MAGNITUDE_POLL_INTERVAL_MS;
    }

    // ── ステータスバー ────────────────────────────────────────────────────────
    function _updateStatusBar(state) {
        const el = document.getElementById('magnitude-status-bar');
        if (!el) return;
        if (state === 'loading') {
            el.textContent = '更新中...';
            el.className = 'mq-status-bar mq-status-loading';
        } else if (state === 'ok') {
            const t = _lastUpdatedAt
                ? _lastUpdatedAt.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
                : '—';
            const sec = Math.round(_pollIntervalMs() / 1000);
            el.textContent = `最終更新: ${t} · ${sec}秒ごとに自動更新`;
            el.className = 'mq-status-bar mq-status-ok';
        } else if (state === 'error') {
            el.textContent = '更新に失敗しました。次回自動更新で再試行します。';
            el.className = 'mq-status-bar mq-status-error';
        } else {
            el.textContent = '';
            el.className = 'mq-status-bar';
        }
    }

    // ── 差分判定 ──────────────────────────────────────────────────────────────
    function _detectNewQuakes(items) {
        const newIds = new Set();

        if (!_firstLoadCompleted) {
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

    function _showNewCount(count, scheduleHide = true) {
        const el = document.getElementById('magnitude-new-count');
        if (!el) return;
        if (count > 0) {
            el.textContent = `新着地震 ${count}件`;
            el.style.display = 'block';
            if (scheduleHide) {
                const t = setTimeout(() => { el.style.display = 'none'; }, 20000);
                _highlightTimers.push(t);
            }
        } else {
            el.style.display = 'none';
            el.textContent = '';
        }
    }

    // ── 取得・描画 ────────────────────────────────────────────────────────────
    // silent=true: バックグラウンドポーリング（リストをクリアしない）
    // silent=false: 初回/手動（読み込み中スピナーを表示）
    async function _load({ silent = false } = {}) {
        if (_loadInFlight) return null;
        _loadInFlight = true;
        const seq = ++_loadSeq;

        if (!silent) {
            const list = document.getElementById('magnitude-list');
            if (list) list.innerHTML = '<div class="mq-loading">読み込み中…</div>';
        }

        _updateStatusBar('loading');

        const refreshBtn = document.getElementById('magnitude-refresh-btn');
        if (refreshBtn) refreshBtn.disabled = true;

        try {
            const resp = await fetch('/api/earthquakes');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data   = await resp.json();
            const quakes = data.items || [];
            if (!_active || seq !== _loadSeq) return;

            _pollFailureCount = 0;
            _lastUpdatedAt    = new Date();
            _updateStatusBar('ok');

            const newIds  = _detectNewQuakes(quakes);
            const userPos = (typeof currentLocation !== 'undefined' && currentLocation)
                ? { lat: currentLocation.lat, lon: currentLocation.lon }
                : null;

            _clearHighlightTimers();

            const visibleNewCount = (typeof renderEarthquakeList === 'function')
                ? renderEarthquakeList(quakes, userPos, newIds)
                : newIds.size;

            _showNewCount(Number.isFinite(visibleNewCount) ? visibleNewCount : newIds.size);

            if (newIds.size > 0) {
                const t = setTimeout(() => {
                    if (!_active) return;
                    if (typeof clearNewHighlights === 'function') clearNewHighlights();
                }, 60000);
                _highlightTimers.push(t);
            }
        } catch (err) {
            if (!_active || seq !== _loadSeq) return;
            _pollFailureCount++;
            console.error('地震情報取得失敗:', err);
            _updateStatusBar('error');
            if (!silent) {
                const list2 = document.getElementById('magnitude-list');
                if (list2) list2.innerHTML = '<div class="mq-error">データを取得できませんでした</div>';
            }
        } finally {
            _loadInFlight = false;
            if (_active && refreshBtn) refreshBtn.disabled = false;
        }
    }

    // ── ポーリング ────────────────────────────────────────────────────────────
    function _startPolling() {
        _stopPolling();
        _polling = true;
        _scheduleNextPoll();
    }

    function _stopPolling() {
        _polling = false;
        if (_pollTimer) {
            clearTimeout(_pollTimer);
            _pollTimer = null;
        }
    }

    function _scheduleNextPoll(delayMs = _pollIntervalMs()) {
        if (!_polling) return;
        if (_pollTimer) clearTimeout(_pollTimer);
        _pollTimer = setTimeout(async () => {
            _pollTimer = null;
            await _runPoll();
            _scheduleNextPoll();
        }, delayMs);
    }

    async function _runPoll() {
        if (!_polling || !_active) return;
        if (_pollInFlight) return;
        if (document.visibilityState === 'hidden') return;

        _pollInFlight = true;
        try {
            await _load({ silent: true });
        } finally {
            _pollInFlight = false;
        }
    }

    // ページ再表示時に即時更新
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && _active && !_pollInFlight) {
            _stopPolling();
            _load({ silent: true }).then(() => { if (_active) _startPolling(); });
        }
    });

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

        if (typeof switchMbcTab === 'function') switchMbcTab('earthquake');

        const btn = document.getElementById('magnitude-btn');
        if (btn) btn.classList.add('map-overlay-btn--active');

        _load().then(() => { if (_active) _startPolling(); });
    }

    function _exit() {
        if (!_active) return;
        _active = false;

        _stopPolling();

        if (_savedView) {
            map.setView(_savedView.center, _savedView.zoom, { animate: true });
            _savedView = null;
        }

        if (typeof switchMbcTab === 'function') switchMbcTab('action');

        const btn = document.getElementById('magnitude-btn');
        if (btn) btn.classList.remove('map-overlay-btn--active');

        _loadSeq++;
        _clearHighlightTimers();

        const newCount = document.getElementById('magnitude-new-count');
        if (newCount) {
            newCount.style.display = 'none';
            newCount.textContent = '';
        }

        _updateStatusBar('clear');

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

    // 手動更新ボタン：ポーリングサイクルをリセットして即時取得
    window.magnitudeReload = function () {
        if (!_active) return;
        if (_pollInFlight || _loadInFlight) return;
        _stopPolling();
        _load().then(() => { if (_active) _startPolling(); });
    };

    window.updateMagnitudeNewCount = function (count) {
        _showNewCount(count, false);
    };
})();
