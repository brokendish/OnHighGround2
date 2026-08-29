'use strict';

const NAV_DEBUG_MAX_EVENTS = 100;
const NAV_DEBUG_EVENT_META = {
    offroute_detected: { emoji: '❌', label: 'ルート逸脱', className: 'offroute' },
    reroute_start: { emoji: '🔁', label: '再ルート開始', className: 'reroute-start' },
    reroute_success: { emoji: '✅', label: '再ルート成功', className: 'reroute-success' },
    arrival_detected: { emoji: '🎯', label: '到着判定', className: 'arrival' }
};

let _navigationDebugEvents = [];
let _navigationDebugVisible = false;
let _navigationDebugLayerGroup = null;

function _navDebugEscapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function _navDebugNowIsoLocal() {
    const date = new Date();
    const pad = (value) => String(value).padStart(2, '0');
    const offsetMinutes = -date.getTimezoneOffset();
    const sign = offsetMinutes >= 0 ? '+' : '-';
    const offsetHours = pad(Math.floor(Math.abs(offsetMinutes) / 60));
    const offsetRemainder = pad(Math.abs(offsetMinutes) % 60);
    return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
        `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
        `${sign}${offsetHours}:${offsetRemainder}`
    );
}

function _navDebugFormatTime(ts) {
    if (!ts) return '—';
    const date = new Date(ts);
    if (Number.isNaN(date.getTime())) return String(ts);
    return date.toLocaleString('ja-JP', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
}

function _navDebugEnsureLayerGroup() {
    if (typeof L === 'undefined' || typeof map === 'undefined' || !map) return null;
    if (!_navigationDebugLayerGroup) {
        _navigationDebugLayerGroup = L.layerGroup();
    }
    return _navigationDebugLayerGroup;
}

function _navDebugBuildIcon(type) {
    const meta = NAV_DEBUG_EVENT_META[type] || {
        emoji: '📍',
        label: type || 'イベント',
        className: 'generic'
    };
    return L.divIcon({
        className: 'nav-debug-marker-wrapper',
        html: `<div class="nav-debug-marker nav-debug-marker--${meta.className}" title="${_navDebugEscapeHtml(meta.label)}">${meta.emoji}</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14]
    });
}

function _navDebugBuildPopup(event) {
    const meta = NAV_DEBUG_EVENT_META[event.type] || {
        label: event.type || 'イベント'
    };
    const contextRows = Object.entries(event.context || {})
        .map(([key, value]) => `<div><strong>${_navDebugEscapeHtml(key)}:</strong> ${_navDebugEscapeHtml(value)}</div>`)
        .join('');
    return `
        <div class="nav-debug-popup">
            <div><strong>種別:</strong> ${_navDebugEscapeHtml(event.type)}</div>
            <div><strong>表示:</strong> ${_navDebugEscapeHtml(meta.label)}</div>
            <div><strong>時刻:</strong> ${_navDebugEscapeHtml(_navDebugFormatTime(event.ts))}</div>
            <div><strong>内容:</strong> ${_navDebugEscapeHtml(event.message || '—')}</div>
            ${contextRows || '<div><strong>context:</strong> —</div>'}
        </div>
    `;
}

function _navDebugRender() {
    const layerGroup = _navDebugEnsureLayerGroup();
    if (!layerGroup) return;

    layerGroup.clearLayers();
    _navigationDebugEvents.forEach((event) => {
        if (!Number.isFinite(event.lat) || !Number.isFinite(event.lon)) return;
        const marker = L.marker([event.lat, event.lon], {
            icon: _navDebugBuildIcon(event.type)
        }).bindPopup(_navDebugBuildPopup(event));
        layerGroup.addLayer(marker);
    });

    if (_navigationDebugVisible) {
        if (!map.hasLayer(layerGroup)) {
            layerGroup.addTo(map);
        }
    } else if (map.hasLayer(layerGroup)) {
        map.removeLayer(layerGroup);
    }
}

function syncNavigationDebugLayerControls() {
    const toggle = document.getElementById('nav-debug-layer-toggle');
    const clearBtn = document.getElementById('nav-debug-layer-clear-btn');
    const status = document.getElementById('nav-debug-layer-status');
    if (toggle) toggle.checked = _navigationDebugVisible;
    if (clearBtn) clearBtn.disabled = _navigationDebugEvents.length === 0;
    if (status) {
        status.textContent = `${_navigationDebugEvents.length} / ${NAV_DEBUG_MAX_EVENTS} events`;
    }
}

function setNavigationDebugLayerVisible(visible) {
    _navigationDebugVisible = !!visible;
    try {
        _navDebugRender();
    } catch (_) {
        // debug layer must never break the main navigation flow
    }
    syncNavigationDebugLayerControls();
    return _navigationDebugVisible;
}

function isNavigationDebugLayerVisible() {
    return _navigationDebugVisible;
}

function clearNavigationDebugEvents() {
    _navigationDebugEvents = [];
    try {
        _navDebugRender();
    } catch (_) {
        // best-effort
    }
    syncNavigationDebugLayerControls();
}

function addNavigationDebugEvent(input) {
    try {
        const lat = Number(input?.lat);
        const lon = Number(input?.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;

        const event = {
            type: String(input?.type || 'unknown'),
            lat,
            lon,
            message: String(input?.message || ''),
            level: String(input?.level || 'INFO').toUpperCase(),
            ts: input?.ts || _navDebugNowIsoLocal(),
            context: input?.context && typeof input.context === 'object' ? input.context : {}
        };

        _navigationDebugEvents.push(event);
        if (_navigationDebugEvents.length > NAV_DEBUG_MAX_EVENTS) {
            _navigationDebugEvents = _navigationDebugEvents.slice(-NAV_DEBUG_MAX_EVENTS);
        }

        _navDebugRender();
        syncNavigationDebugLayerControls();
        return true;
    } catch (_) {
        return false;
    }
}

window.addNavigationDebugEvent = addNavigationDebugEvent;
window.setNavigationDebugLayerVisible = setNavigationDebugLayerVisible;
window.isNavigationDebugLayerVisible = isNavigationDebugLayerVisible;
window.clearNavigationDebugEvents = clearNavigationDebugEvents;
window.syncNavigationDebugLayerControls = syncNavigationDebugLayerControls;
window.__getNavigationDebugState = () => ({
    visible: _navigationDebugVisible,
    count: _navigationDebugEvents.length,
    events: _navigationDebugEvents.slice()
});

window.addEventListener('load', () => {
    syncNavigationDebugLayerControls();
    try {
        _navDebugRender();
    } catch (_) {
        // map may not be ready yet; keep debug layer best-effort only
    }
});
