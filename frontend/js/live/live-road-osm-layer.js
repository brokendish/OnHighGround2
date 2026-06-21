'use strict';
// live-road-osm-layer.js — 道路交通影響レイヤー: 主要道路ネットワーク表示
// 静的GeoJSON（OSM PBFから事前生成・道路名単位マージ済み）を使用。
// 道路交通影響レイヤーON時のみ表示される。
//
// ファイル:
//   /layers/roads/kanto_roads_main.geojson      motorway/trunk/primary/secondary
//   /layers/roads/kanto_roads_tertiary.geojson  tertiary（名前付きのみ、zoom13+で遅延ロード）

(function () {

    const _MAIN_URL     = '/layers/roads/kanto_roads_main.geojson';
    const _MIN_ZOOM     = 8;
    const _DEBOUNCE_MS  = 300;

    // ── 道路クラス設定 ────────────────────────────────────────────────────────

    const _ROAD_COLOR = {
        motorway:  '#43A047',
        trunk:     '#66BB6A',
        primary:   '#1E88E5',
        secondary: '#FB8C00',
        tertiary:  '#B0BEC5',
        unknown:   '#78909C',
    };

    const _ROAD_WEIGHT = {
        motorway:  3.0,
        trunk:     2.8,
        primary:   2.5,
        secondary: 2.0,
        tertiary:  1.5,
        unknown:   1.5,
    };

    // ズーム別表示クラス
    // secondary は除外: _merge_by_name による非隣接断片の混入で
    // 地図と一致しない矩形ループ・ジグザグが発生するため
    const _ZOOM_CLASS_INCLUDE = [
        [8, new Set(['motorway', 'trunk', 'primary'])],
    ];

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    const _svgRenderer = L.svg();

    let _enabled        = false;
    let _baseLayer      = null;
    let _fetchTimer     = null;
    let _lastBoundsKey  = null;
    let _listenersAdded = false;

    // 静的GeoJSONキャッシュ
    let _mainFeatures = null;
    let _mainPromise  = null;

    // ── ユーティリティ ────────────────────────────────────────────────────────

    function _roadClass(props) {
        const hw = props._live_road_class || props.highway || 'unknown';
        return _ROAD_COLOR[hw] ? hw : 'unknown';
    }

    function _coordinatesAsLines(geometry) {
        if (!geometry) return [];
        if (geometry.type === 'LineString')      return [geometry.coordinates || []];
        if (geometry.type === 'MultiLineString') return geometry.coordinates || [];
        return [];
    }

    function _featureIntersectsBounds(feat, bounds) {
        const s = bounds.getSouth(), w = bounds.getWest();
        const n = bounds.getNorth(), e = bounds.getEast();
        return _coordinatesAsLines(feat.geometry).some(line =>
            line.some(([lon, lat]) => lat >= s && lat <= n && lon >= w && lon <= e)
        );
    }

    // ── ズームフィルタ + 件数キャップ ────────────────────────────────────────

    function _allowedClasses(zoom) {
        for (const [minZoom, classes] of _ZOOM_CLASS_INCLUDE) {
            if (zoom >= minZoom) return classes;
        }
        return new Set();
    }

    // 道路種別優先度（キャップ時に高いほど優先）
    const _CLASS_PRIORITY = {
        motorway: 5, trunk: 4, primary: 3, secondary: 2, tertiary: 1, unknown: 0,
    };

    // ズーム別の描画フィーチャー上限（SVG path 数削減のため）
    const _FEATURE_CAPS = [
        [13, 600],
        [11, 300],
        [8,  200],
    ];

    // MultiLineString の各 LineString を bounds でクリップし、
    // 画面外のセグメントを描画しないようにする。
    // _merge_by_name が同名セグメントを全国からかき集めるため必須。
    function _clipToBounds(feat, bounds) {
        const s = bounds.getSouth(), w = bounds.getWest();
        const n = bounds.getNorth(), e = bounds.getEast();
        const lines = _coordinatesAsLines(feat.geometry);
        const inView = lines.filter(line =>
            line.some(([lon, lat]) => lat >= s && lat <= n && lon >= w && lon <= e)
        );
        if (inView.length === 0) return null;
        return {
            ...feat,
            geometry: { type: 'MultiLineString', coordinates: inView },
        };
    }

    function _capFeatures(features, zoom) {
        let cap = 600;
        for (const [minZoom, c] of _FEATURE_CAPS) {
            if (zoom >= minZoom) { cap = c; break; }
        }
        if (features.length <= cap) return features;
        // 道路種別優先度でソートして上位 cap 件のみ描画
        return [...features]
            .sort((a, b) => (_CLASS_PRIORITY[_roadClass(b.properties || {})] || 0)
                          - (_CLASS_PRIORITY[_roadClass(a.properties || {})] || 0))
            .slice(0, cap);
    }

    // ── スタイル ──────────────────────────────────────────────────────────────

    function _roadStyle(feature) {
        const cls = _roadClass(feature?.properties || {});
        return {
            color:       _ROAD_COLOR[cls] || _ROAD_COLOR.unknown,
            weight:      _ROAD_WEIGHT[cls] || 1.5,
            opacity:     0.72,
            fillOpacity: 0,
        };
    }

    // ── ポップアップ ──────────────────────────────────────────────────────────

    function _esc(v) {
        return String(v ?? '').replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    const _CLASS_LABEL = {
        motorway:  '高速道路',
        trunk:     '自動車専用道・主要幹線',
        primary:   '国道級',
        secondary: '主要地方道級',
        tertiary:  '地域主要道路',
        unknown:   '—',
    };

    function _buildPopup(props) {
        const name = _esc(props._live_road_name || '—');
        const cls  = _esc(_CLASS_LABEL[_roadClass(props)] || '—');
        const ref  = props.ref ? `<br>路線記号: ${_esc(props.ref)}` : '';
        return `<b>${name}</b><br>種別: ${cls}${ref}`;
    }

    // ── 静的GeoJSON読み込み ───────────────────────────────────────────────────

    function _loadMain() {
        if (_mainPromise) return _mainPromise;
        _mainPromise = fetch(_MAIN_URL)
            .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
            .then(fc => {
                _mainFeatures = fc.features || [];
                console.info(`[live-road-osm] main 読み込み完了: ${_mainFeatures.length} features`);
                return _mainFeatures;
            })
            .catch(e => { _mainPromise = null; throw e; });
        return _mainPromise;
    }

    // ── 描画メインフロー ──────────────────────────────────────────────────────

    async function _refresh() {
        if (!_enabled || !window.liveMap) return;
        const map  = window.liveMap;
        const zoom = map.getZoom();

        if (zoom < _MIN_ZOOM) {
            if (_baseLayer) { map.removeLayer(_baseLayer); _baseLayer = null; }
            window.liveRoadLabelLayer?.clearLabels?.();
            return;
        }

        const bounds = map.getBounds();
        const key = [zoom,
            bounds.getSouth().toFixed(2), bounds.getWest().toFixed(2),
            bounds.getNorth().toFixed(2), bounds.getEast().toFixed(2),
        ].join(',');
        if (key === _lastBoundsKey) return;
        _lastBoundsKey = key;

        try {
            const allFeatures = await _loadMain();

            const allowed  = _allowedClasses(zoom);
            const inBounds = allFeatures
                .filter(feat => {
                    const cls = _roadClass(feat.properties || {});
                    return allowed.has(cls) && _featureIntersectsBounds(feat, bounds);
                })
                .map(feat => _clipToBounds(feat, bounds))
                .filter(Boolean);
            const visible = _capFeatures(inBounds, zoom);

            if (_baseLayer) map.removeLayer(_baseLayer);

            _baseLayer = L.geoJSON(
                { type: 'FeatureCollection', features: visible },
                {
                    style:        _roadStyle,
                    renderer:     _svgRenderer,
                    smoothFactor: zoom >= 13 ? 1 : 2,
                    onEachFeature(feature, layer) {
                        const name = feature.properties?._live_road_name;
                        if (name) layer.bindPopup(_buildPopup(feature.properties));
                    },
                }
            ).addTo(map);

            // ラベル層にフィーチャーを渡す
            window.liveRoadLabelLayer?.setRoadFeatures?.(visible, zoom, bounds);
        } catch (e) {
            console.warn('[live-road-osm] 道路データ読み込み失敗:', e.message);
        }
    }

    function _scheduleRefresh() {
        if (_fetchTimer) clearTimeout(_fetchTimer);
        _fetchTimer = setTimeout(_refresh, _DEBOUNCE_MS);
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    function setVisible(visible) {
        _enabled = visible;
        const map = window.liveMap;
        if (!map) return;
        if (visible) {
            if (!_listenersAdded) {
                map.on('moveend zoomend', _scheduleRefresh);
                _listenersAdded = true;
            }
            _scheduleRefresh();
            window.liveRoadLabelLayer?.setVisible?.(true);
        } else {
            if (_baseLayer) { map.removeLayer(_baseLayer); _baseLayer = null; }
            _lastBoundsKey = null;
            window.liveRoadLabelLayer?.setVisible?.(false);
        }
    }

    window.liveRoadOsmLayer = { setVisible };

})();
