/**
 * magnitude-ui.js — 地震情報リストパネル
 *
 * 依存: magnitude-layer.js (focusEarthquakePin)
 */
(function () {
    let _sortMode    = 'newest';
    let _lastQuakes  = [];
    let _lastUserPos = null;
    let _lastNewIds  = new Set();

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

    function _hasUsableLocation(userPos) {
        if (userPos?.lat == null || userPos?.lon == null) return false;
        return !!userPos && Number.isFinite(Number(userPos.lat)) && Number.isFinite(Number(userPos.lon));
    }

    function _hasUsableQuakeLocation(q) {
        if (q?.lat == null || q?.lng == null) return false;
        return Number.isFinite(Number(q?.lat)) && Number.isFinite(Number(q?.lng));
    }

    function _getQuakeDistance(q, userPos) {
        if (!_hasUsableLocation(userPos) || !_hasUsableQuakeLocation(q)) return null;
        return _distanceKm(userPos.lat, userPos.lon, q.lat, q.lng);
    }

    function _compareByNewest(a, b) {
        const ta = new Date(a?.occurred_at || 0).getTime();
        const tb = new Date(b?.occurred_at || 0).getTime();
        const va = Number.isFinite(ta) ? ta : 0;
        const vb = Number.isFinite(tb) ? tb : 0;
        return vb - va;
    }

    function _sortItems(items, mode, userPos) {
        const arr = [...items];
        if (mode === 'nearest' && userPos) {
            return arr.sort((a, b) => {
                const da = _getQuakeDistance(a, userPos);
                const db = _getQuakeDistance(b, userPos);
                if (da == null && db == null) return _compareByNewest(a, b);
                if (da == null) return 1;
                if (db == null) return -1;
                if (da !== db) return da - db;
                return _compareByNewest(a, b);
            });
        }
        return arr.sort(_compareByNewest);
    }

    function _formatTime(isoStr) {
        if (!isoStr) return '—';
        try {
            const d = new Date(isoStr);
            return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
        } catch { return '—'; }
    }

    function _formatDate(isoStr) {
        if (!isoStr) return '';
        try {
            const d = new Date(isoStr);
            const today = new Date();
            if (d.toDateString() === today.toDateString()) return '';
            return `${d.getMonth() + 1}/${d.getDate()} `;
        } catch { return ''; }
    }

    function _ageClass(isoStr) {
        if (!isoStr) return '';
        const h = (Date.now() - new Date(isoStr).getTime()) / 3600000;
        if (h < 1) return 'mq-item--1h';
        if (h < 3) return 'mq-item--3h';
        if (h < 6) return 'mq-item--6h';
        return '';
    }

    function _updateSortBar(userPos) {
        const bar = document.getElementById('magnitude-sort-bar');
        if (!bar) return;
        const hasLoc = _hasUsableLocation(userPos);
        const hint = !hasLoc
            ? '<div class="mq-sort-hint">現在地を取得すると、近い順で並び替えできます。</div>'
            : '';
        bar.innerHTML =
            `<div class="mq-sort-tabs">` +
            `<button class="mq-sort-button${_sortMode === 'newest' ? ' active' : ''}" onclick="magnitudeSortSet('newest')">新しい順</button>` +
            `<button class="mq-sort-button${_sortMode === 'nearest' ? ' active' : ''}"${hasLoc ? '' : ' disabled'} onclick="magnitudeSortSet('nearest')">近い順</button>` +
            `</div>${hint}`;
    }

    function _renderList() {
        const panel = document.getElementById('magnitude-list');
        if (!panel) return;

        _updateSortBar(_lastUserPos);

        if (!_lastQuakes.length) {
            panel.innerHTML = '<div class="mq-empty">地震情報なし</div>';
            return;
        }

        if (_sortMode === 'nearest' && !_hasUsableLocation(_lastUserPos)) {
            _sortMode = 'newest';
            _updateSortBar(_lastUserPos);
        }

        const sorted = _sortItems(_lastQuakes, _sortMode, _lastUserPos);

        const html = sorted.map(q => {
            const isNew    = _lastNewIds.has(String(q.event_id));
            const ageClass = _ageClass(q.occurred_at);
            const newClass = isNew ? ' mq-item-new' : '';
            const timeStr  = _formatDate(q.occurred_at) + _formatTime(q.occurred_at);
            const magValue = Number(q.magnitude);
            const mag      = Number.isFinite(magValue) ? `M${magValue.toFixed(1)}` : 'M—';
            const eventId  = _escapeHtml(q.event_id);
            const badge    = isNew ? '<span class="mq-new-badge">NEW</span>' : '';
            let distHtml   = '';
            if (_hasUsableLocation(_lastUserPos) && _hasUsableQuakeLocation(q)) {
                const d = _distanceKm(_lastUserPos.lat, _lastUserPos.lon, q.lat, q.lng);
                distHtml = `<span class="mq-dist">約${Math.round(d)}km</span>`;
            }
            return `<div class="mq-item ${ageClass}${newClass}" data-event-id="${eventId}">
                <div class="mq-main">
                    ${badge}<span class="mq-time">${_escapeHtml(timeStr)}</span>
                    <span class="mq-name">${_escapeHtml(q.epicenter_name)}</span>
                    <span class="mq-scale">震度${_escapeHtml(q.max_intensity || '不明')}</span>
                    <span class="mq-mag">${_escapeHtml(mag)}</span>
                </div>
                ${distHtml ? `<div class="mq-sub">${distHtml}</div>` : ''}
            </div>`;
        }).join('');

        panel.innerHTML = html;

        panel.querySelectorAll('.mq-item').forEach(el => {
            el.addEventListener('click', () => {
                const id = el.dataset.eventId;
                panel.querySelectorAll('.mq-item--selected').forEach(item => {
                    item.classList.remove('mq-item--selected');
                });
                el.classList.add('mq-item--selected');
                if (typeof focusEarthquakePin === 'function') focusEarthquakePin(id);
            });
        });
    }

    window.renderEarthquakeList = function (quakes, userPos, newEventIds = new Set()) {
        _lastQuakes  = quakes;
        _lastUserPos = userPos;
        _lastNewIds  = newEventIds;
        _renderList();
    };

    window.magnitudeSortSet = function (mode) {
        if (mode === 'nearest' && !_hasUsableLocation(_lastUserPos)) return;
        if (mode !== 'newest' && mode !== 'nearest') return;
        _sortMode = mode;
        _renderList();
    };

    window.clearEarthquakeList = function () {
        const panel = document.getElementById('magnitude-list');
        if (panel) panel.innerHTML = '';
        const bar = document.getElementById('magnitude-sort-bar');
        if (bar) bar.innerHTML = '';
    };

})();
