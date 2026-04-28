/**
 * magnitude-ui.js — 地震情報リストパネル
 *
 * 依存: magnitude-layer.js (focusEarthquakePin)
 */
(function () {
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

    window.renderEarthquakeList = function (quakes, userPos, newEventIds = new Set()) {
        const panel = document.getElementById('magnitude-list');
        if (!panel) return;

        if (!quakes.length) {
            panel.innerHTML = '<div class="mq-empty">地震情報なし</div>';
            return;
        }

        const html = quakes.map(q => {
            const isNew    = newEventIds.has(String(q.event_id));
            const ageClass = _ageClass(q.occurred_at);
            const newClass = isNew ? ' mq-item-new' : '';
            const timeStr  = _formatDate(q.occurred_at) + _formatTime(q.occurred_at);
            const mag      = q.magnitude != null ? `M${q.magnitude.toFixed(1)}` : 'M—';
            const eventId  = _escapeHtml(q.event_id);
            const badge    = isNew ? '<span class="mq-new-badge">NEW</span>' : '';
            let distHtml   = '';
            if (userPos && q.lat != null && q.lng != null) {
                const d = _distanceKm(userPos.lat, userPos.lon, q.lat, q.lng);
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
    };

    window.clearEarthquakeList = function () {
        const panel = document.getElementById('magnitude-list');
        if (panel) panel.innerHTML = '';
    };

})();
