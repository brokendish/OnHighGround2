'use strict';
// live-train-label-layer.js — 鉄道路線名・駅名ラベル表示
// 鉄道運行影響レイヤーON時のみ表示。live-train-osm-layer.js から路線フィーチャーを受け取る。

(function () {

    const _STATION_URL = '/layers/railways/kanto_stations.geojson';
    const _DEBOUNCE_MS = 300;

    // ズームレベル別の表示上限
    const _ROUTE_LIMITS   = [
        [15, 80], [13, 60], [11, 40], [8, 20],
    ];
    const _STATION_LIMITS = [
        [15, 80], [13, 40], [11, 10], [8, 0],
    ];

    // zoom 13〜14 で優先表示する主要駅
    const _MAJOR_STATIONS = new Set([
        '東京', '新宿', '渋谷', '池袋', '品川', '上野', '秋葉原', '有楽町', '新橋',
        '横浜', '川崎', '武蔵小杉', '溝の口',
        '大宮', '浦和', '川口', '越谷',
        '千葉', '船橋', '柏', '松戸', '我孫子',
        '立川', '八王子', '町田', '調布', '吉祥寺', '中野', '三鷹',
        '北千住', '押上', '錦糸町', '亀戸',
        '府中', '聖蹟桜ヶ丘', '高尾',
        '西船橋', '津田沼', '本八幡',
        '蒲田', '大森', '大井町', '五反田',
        '流山おおたかの森', 'つくば',
    ]);

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    let _enabled        = false;
    let _routeFeatures  = [];   // live-train-osm-layer.js からの集約済み路線フィーチャー
    let _lastItems      = [];   // ODPT障害データ
    let _allStations    = null; // 全駅フィーチャー（キャッシュ）
    let _stationPromise = null;
    let _labelGroup     = L.layerGroup();
    let _refreshTimer   = null;
    let _listenersAdded = false;

    // ── ユーティリティ ────────────────────────────────────────────────────────

    function _esc(v) {
        return String(v ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function _limitFor(table, zoom) {
        for (const [minZoom, count] of table) {
            if (zoom >= minZoom) return count;
        }
        return 0;
    }

    // ── 駅データ読み込み ──────────────────────────────────────────────────────

    function _loadStations() {
        if (_stationPromise) return _stationPromise;
        _stationPromise = fetch(_STATION_URL)
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then(fc => {
                _allStations = fc.features || [];
                return _allStations;
            })
            .catch(e => {
                _stationPromise = null;
                throw e;
            });
        return _stationPromise;
    }

    // ── 路線名解決 ────────────────────────────────────────────────────────────

    function _routeDisplayName(props) {
        return (props._live_route_name || props.name_ja || props.name || props.route_name || props.ref || '').trim();
    }

    // ── 路線の代表点（表示範囲中心に最も近い座標）────────────────────────────

    function _routeLabelPoint(feat, bounds) {
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
        return best; // [lon, lat] or null
    }

    function _routeVisiblePoints(feat, bounds) {
        const geom = feat.geometry;
        if (!geom) return [];
        const s = bounds.getSouth(), w = bounds.getWest();
        const n = bounds.getNorth(), e = bounds.getEast();
        const lines = geom.type === 'MultiLineString'
            ? (geom.coordinates || [])
            : [geom.coordinates || []];
        const points = [];
        lines.forEach(line => {
            (Array.isArray(line) ? line : []).forEach(pt => {
                if (!pt || pt.length < 2) return;
                const [lon, lat] = pt;
                if (lat < s || lat > n || lon < w || lon > e) return;
                points.push([lon, lat]);
            });
        });
        return points;
    }

    // ── 障害マッチング（路線名ベース簡易一致）────────────────────────────────

    function _findDisruption(props) {
        const routeName = _routeDisplayName(props).toLowerCase();
        if (!routeName) return null;
        for (const item of _lastItems) {
            const dn = (item.railway_name || '').toLowerCase();
            if (!dn) continue;
            if (routeName.includes(dn) || dn.includes(routeName)) return item;
        }
        return null;
    }

    function _disruptedRoutePoints(bounds) {
        const points = [];
        _routeFeatures.forEach(feat => {
            if (!_findDisruption(feat.properties || {})) return;
            points.push(..._routeVisiblePoints(feat, bounds));
        });
        return points;
    }

    function _nearestDist2ToPoints(lon, lat, points) {
        let best = Infinity;
        points.forEach(([plon, plat]) => {
            const d = (lon - plon) ** 2 + (lat - plat) ** 2;
            if (d < best) best = d;
        });
        return best;
    }

    function _stationPriority(feat, disruptedPoints) {
        const props = feat.properties || {};
        const coords = feat.geometry?.coordinates || [];
        const [lon, lat] = coords;
        const name = props.name || '';
        const dist2 = disruptedPoints.length
            ? _nearestDist2ToPoints(lon, lat, disruptedPoints)
            : Infinity;
        const nearDisrupted = dist2 <= 0.000225; // roughly within 1-1.5km around Tokyo.
        let score = 0;
        if (nearDisrupted) score += 1000;
        if (_MAJOR_STATIONS.has(name)) score += 300;
        if (props.train === 'yes') score += 80;
        if (props.station === 'subway' || props.subway === 'yes') score += 40;
        return { score, nearDisrupted, dist2 };
    }

    // ── ラベル HTML ───────────────────────────────────────────────────────────

    const _STATUS_ABBR = {
        delay:              '遅延',
        partial_suspension: '一部運休',
        suspended:          '見合わせ',
    };

    function _routeLabelHtml(displayName, lineColor, disruption) {
        const abbr  = disruption ? (_STATUS_ABBR[disruption.status] || disruption.status_label || '') : '';
        const bw    = disruption ? '2px' : '1px';
        const badge = abbr
            ? `<span class="tll-status-badge">${_esc(abbr)}</span>`
            : '';
        const cls = disruption ? 'tll-route-label tll-disrupted' : 'tll-route-label';
        return `<div class="${cls}" style="border:${bw} solid ${_esc(lineColor)}">`
            + `${_esc(displayName)}${badge}`
            + `</div>`;
    }

    function _stationLabelHtml(name) {
        return `<div class="tll-station-label">${_esc(name)}</div>`;
    }

    // ── マーカー生成 ──────────────────────────────────────────────────────────

    function _makeLabelMarker(lat, lon, html) {
        const icon = L.divIcon({
            html,
            className: 'tll-marker',
            iconSize:   null,
            iconAnchor: [0, 8],
        });
        return L.marker([lat, lon], { icon, interactive: false, keyboard: false });
    }

    // ── 路線ラベルレンダリング ─────────────────────────────────────────────────

    function _renderRouteLabels(zoom, bounds) {
        const max = _limitFor(_ROUTE_LIMITS, zoom);
        if (max <= 0 || !_routeFeatures.length) return;

        // 障害路線を先頭に
        const disrupted = [], normal = [];
        for (const feat of _routeFeatures) {
            const d = _findDisruption(feat.properties || {});
            (d ? disrupted : normal).push({ feat, disruption: d });
        }

        let count = 0;
        for (const { feat, disruption } of [...disrupted, ...normal]) {
            if (count >= max) break;
            const pt = _routeLabelPoint(feat, bounds);
            if (!pt) continue;

            const props     = feat.properties || {};
            const name      = _routeDisplayName(props);
            if (!name) continue;

            const lineColor = props._live_route_color || '#8FA3B0';
            const html      = _routeLabelHtml(name, lineColor, disruption);
            _makeLabelMarker(pt[1], pt[0], html).addTo(_labelGroup);
            count++;
        }
    }

    // ── 駅ラベルレンダリング ──────────────────────────────────────────────────

    function _renderStationLabels(zoom, bounds) {
        if (!_allStations) return;
        const max = _limitFor(_STATION_LIMITS, zoom);
        if (max <= 0) return;

        const s = bounds.getSouth(), w = bounds.getWest();
        const n = bounds.getNorth(), e = bounds.getEast();

        let candidates = _allStations.filter(feat => {
            const coords = feat.geometry?.coordinates;
            if (!coords || coords.length < 2) return false;
            const [lon, lat] = coords;
            return lat >= s && lat <= n && lon >= w && lon <= e;
        });

        const disruptedPoints = _disruptedRoutePoints(bounds);

        // zoom 11〜14 は主要駅 + 障害路線周辺駅のみ
        if (zoom < 15) {
            candidates = candidates.filter(feat => {
                const priority = _stationPriority(feat, disruptedPoints);
                return _MAJOR_STATIONS.has(feat.properties?.name || '') || priority.nearDisrupted;
            });
        }

        candidates.sort((a, b) => {
            const pa = _stationPriority(a, disruptedPoints);
            const pb = _stationPriority(b, disruptedPoints);
            if (pb.score !== pa.score) return pb.score - pa.score;
            return pa.dist2 - pb.dist2;
        });

        // 同名駅の重複を除去（最初の1件のみ）
        const seen = new Set();
        const limited = [];
        for (const feat of candidates) {
            if (limited.length >= max) break;
            const name = feat.properties?.name || '';
            if (!name || seen.has(name)) continue;
            seen.add(name);
            limited.push(feat);
        }

        for (const feat of limited) {
            const name = feat.properties?.name;
            if (!name) continue;
            const [lon, lat] = feat.geometry.coordinates;
            _makeLabelMarker(lat, lon, _stationLabelHtml(name)).addTo(_labelGroup);
        }
    }

    // ── 更新メインフロー ──────────────────────────────────────────────────────

    async function _refresh() {
        if (!_enabled || !window.liveMap) return;
        const map    = window.liveMap;
        const zoom   = map.getZoom();
        const bounds = map.getBounds();

        _labelGroup.clearLayers();
        if (zoom < 8) return;

        _renderRouteLabels(zoom, bounds);

        if (zoom >= 11) {
            try {
                await _loadStations();
                _renderStationLabels(zoom, bounds);
            } catch (_) { /* 駅データ取得失敗は無視 */ }
        }
    }

    function _scheduleRefresh() {
        clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(_refresh, _DEBOUNCE_MS);
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

    // live-train-osm-layer.js の _refresh() から呼ばれる（集約済み路線フィーチャーを受け取る）
    function setRouteFeatures(features) {
        _routeFeatures = Array.isArray(features) ? features : [];
        if (_enabled) _scheduleRefresh();
    }

    // live-train-osm-layer.js の setDisruptions() から呼ばれる
    function setDisruptions(items) {
        _lastItems = Array.isArray(items) ? items : [];
        if (_enabled) _scheduleRefresh();
    }

    window.liveTrainLabelLayer = { setVisible, setRouteFeatures, setDisruptions };

})();
