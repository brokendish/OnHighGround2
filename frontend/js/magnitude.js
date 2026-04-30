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

    // マスターアイテムリスト（ポーリング＋SSEのupsert先）
    let _currentItems   = [];
    // 累積NEWバッジ用ID（ポーリング＋SSE共通）
    let _pendingNewIds  = new Set();

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

    // ── SSE状態 ───────────────────────────────────────────────────────────────
    let _magnitudeEventSource = null;

    function _updateSseStatus(status) {
        const el = document.getElementById('magnitude-sse-status');
        if (!el) return;
        const pollSec = Math.round(_pollIntervalMs() / 1000);
        const labels = {
            connected:    'リアルタイム: 接続中',
            reconnecting: `リアルタイム: 再接続中（${pollSec}秒ごとに自動更新で継続）`,
            disconnected: `リアルタイム: 切断中（${pollSec}秒ごとに自動更新）`,
        };
        el.textContent = labels[status] || '';
        el.className = 'mq-sse-status mq-sse-' + status;
    }

    function _handleRealtimeStatus(data) {
        if (!_active) return;
        const state = data && data.state;
        if (state === 'connected') {
            _updateSseStatus('connected');
        } else if (state === 'reconnecting' || state === 'connecting') {
            _updateSseStatus('reconnecting');
        } else if (state === 'disconnected' || state === 'failed') {
            _updateSseStatus('disconnected');
        }
    }

    function _startMagnitudeStream() {
        _stopMagnitudeStream();
        let es;
        try {
            es = new EventSource('/api/earthquakes/stream');
        } catch (_e) {
            _updateSseStatus('disconnected');
            return;
        }
        _magnitudeEventSource = es;
        es.onopen = () => {
            if (_magnitudeEventSource !== es || !_active) return;
            _updateSseStatus('connected');
        };
        es.addEventListener('earthquake', (event) => {
            if (_magnitudeEventSource !== es || !_active) return;
            try {
                const item = JSON.parse(event.data);
                _handleRealtimeEarthquake(item);
            } catch (_e) {
                // 不正JSONは無視
            }
        });
        es.addEventListener('status', (event) => {
            if (_magnitudeEventSource !== es || !_active) return;
            try {
                const data = JSON.parse(event.data);
                _handleRealtimeStatus(data);
            } catch (_e) {
                // 不正JSONは無視
            }
        });
        es.onerror = () => {
            if (_magnitudeEventSource !== es || !_active) return;
            _updateSseStatus('reconnecting');
        };
    }

    function _stopMagnitudeStream() {
        if (_magnitudeEventSource) {
            _magnitudeEventSource.close();
            _magnitudeEventSource = null;
        }
        _updateSseStatus('disconnected');
    }

    // ── SSEイベント受信処理 ───────────────────────────────────────────────────
    function _handleRealtimeEarthquake(item) {
        if (!item || !item.event_id) return;
        if (!_active) return;

        // lat/lng の検証
        if (item.lat != null && !Number.isFinite(Number(item.lat))) item.lat = null;
        if (item.lng != null && !Number.isFinite(Number(item.lng))) item.lng = null;

        const id = String(item.event_id);

        // _currentItems へ upsert
        const existingIdx = _currentItems.findIndex(q => String(q.event_id) === id);
        if (existingIdx >= 0) {
            _currentItems[existingIdx] = item;
        } else {
            _currentItems.unshift(item);
            // 初回ロード完了後かつ未知のIDのみ NEW扱い
            if (_firstLoadCompleted && !_knownEventIds.has(id)) {
                _pendingNewIds.add(id);
            }
            _knownEventIds.add(id);
        }

        const userPos = (typeof currentLocation !== 'undefined' && currentLocation)
            ? { lat: currentLocation.lat, lon: currentLocation.lon }
            : null;

        _clearHighlightTimers();

        const visibleNewCount = (typeof renderEarthquakeList === 'function')
            ? renderEarthquakeList(_currentItems, userPos, _pendingNewIds)
            : _pendingNewIds.size;

        _showNewCount(Number.isFinite(visibleNewCount) ? visibleNewCount : _pendingNewIds.size);

        if (_pendingNewIds.size > 0) {
            const t = setTimeout(() => {
                if (!_active) return;
                _pendingNewIds.clear();
                if (typeof clearNewHighlights === 'function') clearNewHighlights();
            }, 60000);
            _highlightTimers.push(t);
        }
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

    // ── フィールド正規化 ──────────────────────────────────────────────────────
    // Phase2C (JMA) と既存P2P の両フォーマットを統一する。
    // 既存UIは occurred_at / epicenter_name / lng / tsunami_info を参照するため、
    // Phase2C フィールド (origin_time / hypocenter_name / lon / domestic_tsunami) を補完する。
    function _normalizeEvent(e) {
        const n = Object.assign({}, e);
        if (!n.occurred_at) n.occurred_at = n.origin_time || n.report_time || null;
        if (!n.epicenter_name) n.epicenter_name = n.hypocenter_name || '不明';
        if (n.lng == null && n.lon != null) n.lng = n.lon;
        if (!n.tsunami_info) n.tsunami_info = n.domestic_tsunami || '不明';
        return n;
    }

    // ── データ取得（フォールバック付き） ──────────────────────────────────────
    // 1. /api/earthquakes/recent (JMA Phase2C) を試みる
    //    - events[] が返れば正規化して使用
    //    - items[] が返れば（テストモック等）そのまま使用（フォールバックなし）
    // 2. 失敗時のみ /api/earthquakes (既存P2P) へフォールバック
    // 3. 両方失敗した場合は例外を投げる
    async function _fetchEarthquakes() {
        try {
            const resp = await fetch('/api/earthquakes/recent');
            if (resp.ok) {
                const data = await resp.json();
                if (Array.isArray(data.events)) {
                    return data.events.map(_normalizeEvent);
                }
                if (Array.isArray(data.items)) {
                    return data.items;
                }
            }
        } catch (_e) { /* fall through to legacy endpoint */ }

        const resp = await fetch('/api/earthquakes');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        return Array.isArray(data.items) ? data.items : [];
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
            const quakes = await _fetchEarthquakes();
            if (!_active || seq !== _loadSeq) return;

            _pollFailureCount = 0;
            _lastUpdatedAt    = new Date();
            _updateStatusBar('ok');

            // ポーリング結果を _currentItems へ upsert（SSE先着分を保持）
            const idMap = new Map(_currentItems.map(q => [String(q.event_id), q]));
            for (const q of quakes) {
                if (q.event_id) idMap.set(String(q.event_id), q);
            }
            _currentItems = Array.from(idMap.values());

            // 新着判定して _pendingNewIds に累積
            const newIds  = _detectNewQuakes(quakes);
            newIds.forEach(id => _pendingNewIds.add(id));

            const userPos = (typeof currentLocation !== 'undefined' && currentLocation)
                ? { lat: currentLocation.lat, lon: currentLocation.lon }
                : null;

            _clearHighlightTimers();

            const visibleNewCount = (typeof renderEarthquakeList === 'function')
                ? renderEarthquakeList(_currentItems, userPos, _pendingNewIds)
                : _pendingNewIds.size;

            _showNewCount(Number.isFinite(visibleNewCount) ? visibleNewCount : _pendingNewIds.size);

            if (_pendingNewIds.size > 0) {
                const t = setTimeout(() => {
                    if (!_active) return;
                    _pendingNewIds.clear();
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
                if (typeof showMapToast === 'function') {
                    showMapToast('地震情報取得不可', { warn: true });
                }
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

        _load().then(() => {
            if (_active) {
                _startPolling();
                _startMagnitudeStream();
            }
        });
    }

    function _exit() {
        if (!_active) return;
        _active = false;

        _stopPolling();
        _stopMagnitudeStream();

        if (_savedView) {
            map.setView(_savedView.center, _savedView.zoom, { animate: true });
            _savedView = null;
        }

        if (typeof switchMbcTab === 'function') switchMbcTab('action');

        const btn = document.getElementById('magnitude-btn');
        if (btn) btn.classList.remove('map-overlay-btn--active');

        _loadSeq++;
        _clearHighlightTimers();

        _currentItems  = [];
        _pendingNewIds.clear();

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
