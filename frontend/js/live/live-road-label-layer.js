'use strict';
// live-road-label-layer.js — 道路名ラベル表示
// 道路交通影響レイヤーON時のみ表示。live-road-osm-layer.js から集約済みフィーチャーを受け取る。

(function () {

    const _DEBOUNCE_MS = 300;

    // ズーム別表示上限（デスクトップ基準）
    const _LABEL_LIMITS = [
        [13, 25],
        [11, 15],
        [8,  8],
    ];

    // モバイルのラベル上限（デスクトップの半分）
    const _LABEL_LIMITS_MOBILE = [
        [13, 12],
        [11, 8],
        [8,  5],
    ];

    // ズーム別表示クラス（ラベル対象。secondary は道路線と同様に除外）
    const _LABEL_CLASSES = [
        [8, new Set(['motorway', 'trunk', 'primary'])],
    ];

    // 道路種別優先度（高いほど先に表示）
    const _CLASS_PRIORITY = {
        motorway:  5,
        trunk:     4,
        primary:   3,
        secondary: 2,
        tertiary:  1,
        unknown:   0,
    };

    const _ROAD_COLOR = {
        motorway:  '#43A047',
        trunk:     '#66BB6A',
        primary:   '#1E88E5',
        secondary: '#FB8C00',
        tertiary:  '#B0BEC5',
        unknown:   '#78909C',
    };

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    let _enabled        = false;
    let _roadFeatures   = [];
    let _labelGroup     = L.layerGroup();
    let _refreshTimer   = null;
    let _listenersAdded = false;

    // ── ユーティリティ ────────────────────────────────────────────────────────

    function _esc(v) {
        return String(v ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function _isMobile() {
        return window.innerWidth <= 600;
    }

    function _limitFor(zoom) {
        const table = _isMobile() ? _LABEL_LIMITS_MOBILE : _LABEL_LIMITS;
        for (const [minZoom, count] of table) {
            if (zoom >= minZoom) return count;
        }
        return 0;
    }

    // 純粋な数字のみ・橋・トンネル名などは品質が低いのでラベル除外
    const _RE_REF_ONLY = /^[\d\s\-\/A-Za-z]+$/;
    function _isGoodLabel(name) {
        if (!name || name.length < 2) return false;
        // 数字・英字のみは除外（例: "246", "3", "R16"）
        if (_RE_REF_ONLY.test(name)) return false;
        return true;
    }

    // ── 画面スペース衝突回避（グリッドベース）─────────────────────────────────

    // マップコンテナの実ピクセル座標を管理してラベル重複を防ぐ
    function _makeCollisionGrid(cellPx) {
        const occupied = new Set();
        return {
            canPlace(map, lat, lon) {
                const pt = map.latLngToContainerPoint([lat, lon]);
                const cx = Math.floor(pt.x / cellPx);
                const cy = Math.floor(pt.y / cellPx);
                const key = `${cx},${cy}`;
                if (occupied.has(key)) return false;
                // 隣接セルも確認（label はだいたい cellPx×1 程度の幅）
                for (let dx = -1; dx <= 1; dx++) {
                    for (let dy = -1; dy <= 1; dy++) {
                        if (occupied.has(`${cx+dx},${cy+dy}`)) return false;
                    }
                }
                occupied.add(key);
                return true;
            },
        };
    }

    function _allowedClasses(zoom) {
        for (const [minZoom, classes] of _LABEL_CLASSES) {
            if (zoom >= minZoom) return classes;
        }
        return new Set();
    }

    // ── 代表点計算（表示範囲の中心に最も近い点）────────────────────────────

    function _labelPoint(feat, bounds) {
        const geom = feat.geometry;
        if (!geom) return null;
        const s = bounds.getSouth(), w = bounds.getWest();
        const n = bounds.getNorth(), e = bounds.getEast();
        const cx = (w + e) / 2, cy = (s + n) / 2;

        const lines = geom.type === 'MultiLineString'
            ? (geom.coordinates || [])
            : [geom.coordinates || []];

        let best = null, bestDist = Infinity;
        lines.forEach(line => {
            (Array.isArray(line) ? line : []).forEach(pt => {
                if (!pt || pt.length < 2) return;
                const [lon, lat] = pt;
                if (lat < s || lat > n || lon < w || lon > e) return;
                const d = (lon - cx) ** 2 + (lat - cy) ** 2;
                if (d < bestDist) { bestDist = d; best = [lon, lat]; }
            });
        });
        return best;
    }

    // ── ラベル HTML ───────────────────────────────────────────────────────────

    function _labelHtml(name, roadClass) {
        const color = _ROAD_COLOR[roadClass] || _ROAD_COLOR.unknown;
        return `<div class="rll-road-label" style="border:1px solid ${_esc(color)}">`
            + `${_esc(name)}</div>`;
    }

    // ── マーカー生成 ──────────────────────────────────────────────────────────

    function _makeLabelMarker(lat, lon, html) {
        const icon = L.divIcon({
            html,
            className: 'rll-marker',
            iconSize:   null,
            iconAnchor: [0, 8],
        });
        return L.marker([lat, lon], { icon, interactive: false, keyboard: false });
    }

    // ── ラベルレンダリング ─────────────────────────────────────────────────────

    function _render(zoom, bounds) {
        _labelGroup.clearLayers();
        if (!_roadFeatures.length) return;

        const max = _limitFor(zoom);
        if (max <= 0) return;

        const allowed = _allowedClasses(zoom);

        // 対象フィーチャーを優先度順にソート
        const candidates = _roadFeatures
            .filter(feat => {
                const props = feat.properties || {};
                const name  = props._live_road_name || '';
                const cls   = props._live_road_class || 'unknown';
                return _isGoodLabel(name) && allowed.has(cls);
            })
            .sort((a, b) => {
                const pa = _CLASS_PRIORITY[a.properties._live_road_class] || 0;
                const pb = _CLASS_PRIORITY[b.properties._live_road_class] || 0;
                return pb - pa;
            });

        // グリッドベース衝突回避（120px × 24px セル）
        const grid = _makeCollisionGrid(120);
        const map  = window.liveMap;

        // 同一道路名は1個のみ
        const seenNames = new Set();
        let count = 0;

        for (const feat of candidates) {
            if (count >= max) break;

            const props = feat.properties || {};
            const name  = props._live_road_name || '';
            if (seenNames.has(name)) continue;

            const pt = _labelPoint(feat, bounds);
            if (!pt) continue;

            // 画面スペース衝突チェック
            if (!grid.canPlace(map, pt[1], pt[0])) continue;

            seenNames.add(name);
            const cls  = props._live_road_class || 'unknown';
            const html = _labelHtml(name, cls);
            _makeLabelMarker(pt[1], pt[0], html).addTo(_labelGroup);
            count++;
        }
    }

    function _scheduleRefresh() {
        clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(() => {
            if (!_enabled || !window.liveMap) return;
            const map  = window.liveMap;
            const zoom = map.getZoom();
            if (zoom < 8) { _labelGroup.clearLayers(); return; }
            _render(zoom, map.getBounds());
        }, _DEBOUNCE_MS);
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    function setVisible(visible) {
        _enabled = visible;
        const map = window.liveMap;
        if (!map) return;
        if (visible) {
            if (!map.hasLayer(_labelGroup)) _labelGroup.addTo(map);
            if (!_listenersAdded) {
                map.on('moveend zoomend', _scheduleRefresh);
                _listenersAdded = true;
            }
            _scheduleRefresh();
        } else {
            _labelGroup.clearLayers();
            if (map.hasLayer(_labelGroup)) map.removeLayer(_labelGroup);
        }
    }

    function clearLabels() {
        _labelGroup.clearLayers();
    }

    // live-road-osm-layer.js から集約済みフィーチャーと表示状態を受け取る
    function setRoadFeatures(features, zoom, bounds) {
        _roadFeatures = Array.isArray(features) ? features : [];
        if (_enabled) _render(zoom, bounds);
    }

    window.liveRoadLabelLayer = { setVisible, setRoadFeatures, clearLabels };

})();
