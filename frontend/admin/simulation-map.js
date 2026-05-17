'use strict';

/**
 * simulation-map.js — Simulation Mode v1.5 Leaflet Map Module
 *
 * 公開 API:
 *   SimMap.init(containerId, { onMarkerUpdate, onInspect })
 *   SimMap.setClickMode('start'|'goal'|'inspect'|null)
 *   SimMap.placeMarker(type, lat, lon)
 *   SimMap.drawRoutes(routes, recIdx)
 *   SimMap.clearRoutes()
 *   SimMap.clearInspect()
 *   SimMap.flyTo(lat, lon, zoom)
 *   SimMap.fitToMarkers()
 *   SimMap.invalidateSize()
 *   SimMap.getMarker(type)  → {lat, lon} | null
 */
const SimMap = (() => {

    // ── 設定 ──────────────────────────────────────────────────────────────────
    const DEFAULT_CENTER = [35.6812, 139.7671]; // 東京駅
    const DEFAULT_ZOOM   = 14;

    const RISK_COLOR = {
        none:      '#3b82f6',
        advisory:  '#f59e0b',
        warning:   '#ef4444',
        emergency: '#991b1b',
        unknown:   '#64748b',
    };

    const RISK_LABEL = {
        none:      'リスクなし',
        advisory:  '注意',
        warning:   '警戒',
        emergency: '危険',
        unknown:   '判定不能',
    };

    // ── 内部状態 ──────────────────────────────────────────────────────────────
    let _map = null;
    let _clickMode = null;
    let _markers = { start: null, goal: null, inspect: null };
    let _routeLayers = [];
    let _badgeLayers = [];
    let _inspectCircle = null;
    let _onMarkerUpdate = null;
    let _onInspect = null;

    // ── マーカーアイコン ───────────────────────────────────────────────────────
    function _makeIcon(type) {
        const colors = { start: '#16a34a', goal: '#dc2626', inspect: '#64748b' };
        const labels = { start: 'S', goal: 'G', inspect: '?' };
        const color = colors[type] || '#475569';
        const label = labels[type] || '•';
        return L.divIcon({
            className: '',
            html: `<div class="sim-map-marker sim-map-marker--${type}" style="background:${color}">${label}</div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14],
            popupAnchor: [0, -16],
        });
    }

    // ── 公開: 初期化 ──────────────────────────────────────────────────────────
    function init(containerId, callbacks = {}) {
        _onMarkerUpdate = callbacks.onMarkerUpdate || null;
        _onInspect      = callbacks.onInspect      || null;

        _map = L.map(containerId, { zoomControl: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19,
        }).addTo(_map);

        _map.on('click', _onMapClick);
    }

    // ── 地図クリック ──────────────────────────────────────────────────────────
    function _onMapClick(e) {
        if (!_clickMode) return;
        const { lat, lng } = e.latlng;

        if (_clickMode === 'inspect') {
            placeMarker('inspect', lat, lng);
            if (typeof _onInspect === 'function') _onInspect(lat, lng);
        } else {
            placeMarker(_clickMode, lat, lng);
            if (typeof _onMarkerUpdate === 'function') _onMarkerUpdate(_clickMode, lat, lng);
        }
        // クリック後はモードを解除
        setClickMode(null);
    }

    // ── 公開: クリックモード ──────────────────────────────────────────────────
    function setClickMode(mode) {
        _clickMode = mode;
        if (_map) {
            _map.getContainer().style.cursor = mode ? 'crosshair' : '';
        }
    }

    // ── 公開: マーカー配置 ────────────────────────────────────────────────────
    function placeMarker(type, lat, lon) {
        if (!_map) return;
        if (_markers[type]) {
            _markers[type].setLatLng([lat, lon]);
            return;
        }
        const m = L.marker([lat, lon], {
            icon: _makeIcon(type),
            draggable: (type === 'start' || type === 'goal'),
        }).addTo(_map);

        if (type === 'start' || type === 'goal') {
            m.on('dragend', () => {
                const p = m.getLatLng();
                if (typeof _onMarkerUpdate === 'function') _onMarkerUpdate(type, p.lat, p.lng);
            });
        }
        _markers[type] = m;
    }

    // ── 公開: マーカー取得 ────────────────────────────────────────────────────
    function getMarker(type) {
        const m = _markers[type];
        if (!m) return null;
        const p = m.getLatLng();
        return { lat: p.lat, lon: p.lng };
    }

    // ── 公開: ルート描画 ──────────────────────────────────────────────────────
    function drawRoutes(routes, recIdx) {
        clearRoutes();
        if (!_map || !routes || !routes.length) return;

        // 推奨ルートを最後（前面）に描画するため並び替え
        const sorted = [...routes].sort((a, b) => {
            if (a.index === recIdx) return 1;
            if (b.index === recIdx) return -1;
            return 0;
        });

        for (const route of sorted) {
            if (!route.coordinates || !route.coordinates.length) continue;
            const isRec  = route.index === recIdx;
            const color  = RISK_COLOR[route.risk_level] || RISK_COLOR.unknown;
            const latlngs = route.coordinates; // [[lat, lon], ...]

            const polyline = L.polyline(latlngs, {
                color,
                weight:  isRec ? 6 : 3,
                opacity: isRec ? 0.9 : 0.45,
            }).addTo(_map);

            const distKm  = (route.distance_m / 1000).toFixed(1);
            const mins    = Math.round(route.duration_s / 60);
            const riskLbl = RISK_LABEL[route.risk_level] || route.risk_level;
            const summaryText = (route.risk_summary || []).slice(0, 2).join(' / ') || '--';
            const recMark = isRec ? ' (recommended)' : (route.is_shortest ? ' (shortest)' : '');
            const penaltyLines = (route.penalties || [])
                .filter(p => p.points > 0)
                .map(p => `+${p.points} ${p.reason}`)
                .join('<br>');

            polyline.bindTooltip(
                `<strong>${route.label}${recMark}</strong><br>` +
                `risk: <strong>${riskLbl}</strong> (score ${route.safety_score})<br>` +
                `${distKm} km / ${mins} min<br>` +
                `${summaryText}` +
                (penaltyLines ? `<br><small>${penaltyLines}</small>` : ''),
                { sticky: true }
            );
            _routeLayers.push(polyline);

            // risk != none: segment-level visualization with dots at 1/4, 1/2, 3/4 points
            if (route.risk_level !== 'none' && latlngs.length >= 2) {
                const segIndices = [
                    Math.floor(latlngs.length * 0.25),
                    Math.floor(latlngs.length * 0.5),
                    Math.floor(latlngs.length * 0.75),
                ].filter((v, i, arr) => arr.indexOf(v) === i);

                for (const si of segIndices) {
                    const dot = L.circleMarker(latlngs[si], {
                        radius:      isRec ? 5 : 4,
                        color:       '#fff',
                        weight:      1.5,
                        fillColor:   color,
                        fillOpacity: 0.85,
                        interactive: false,
                    }).addTo(_map);
                    _routeLayers.push(dot);
                }

                const mid = latlngs[Math.floor(latlngs.length / 2)];
                const badge = L.marker(mid, {
                    icon: L.divIcon({
                        className: '',
                        html: `<div class="sim-segment-badge sim-segment-badge--${route.risk_level}">${riskLbl}</div>`,
                        iconSize: [60, 20],
                        iconAnchor: [30, 10],
                    }),
                    interactive: false,
                }).addTo(_map);
                _badgeLayers.push(badge);
            }
        }
    }

    // ── 公開: ルートクリア ────────────────────────────────────────────────────
    function clearRoutes() {
        for (const l of _routeLayers) _map && _map.removeLayer(l);
        for (const b of _badgeLayers) _map && _map.removeLayer(b);
        _routeLayers = [];
        _badgeLayers = [];
    }

    // ── 公開: 検査マーカークリア ───────────────────────────────────────────────
    function clearInspect() {
        if (_markers.inspect) {
            _map && _map.removeLayer(_markers.inspect);
            _markers.inspect = null;
        }
        if (_inspectCircle) {
            _map && _map.removeLayer(_inspectCircle);
            _inspectCircle = null;
        }
    }

    // ── 公開: フライ・フィット ────────────────────────────────────────────────
    function flyTo(lat, lon, zoom) {
        _map && _map.flyTo([lat, lon], zoom || DEFAULT_ZOOM, { duration: 0.8 });
    }

    function fitToMarkers() {
        if (!_map) return;
        const pts = Object.values(_markers)
            .filter(Boolean)
            .map(m => m.getLatLng());
        if (pts.length === 0) return;
        if (pts.length === 1) { _map.setView(pts[0], DEFAULT_ZOOM); return; }
        _map.fitBounds(L.latLngBounds(pts), { padding: [48, 48] });
    }

    function invalidateSize() {
        _map && _map.invalidateSize();
    }

    // ── 公開 API ──────────────────────────────────────────────────────────────
    return {
        init,
        setClickMode,
        placeMarker,
        getMarker,
        drawRoutes,
        clearRoutes,
        clearInspect,
        flyTo,
        fitToMarkers,
        invalidateSize,
    };
})();
