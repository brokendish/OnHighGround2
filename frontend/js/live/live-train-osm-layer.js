'use strict';
// live-train-osm-layer.js — OSM鉄道路線ベースレイヤー + ODPT障害路線強調
// 静的GeoJSON（OSM PBFから事前生成）を使用。Overpass API 不要。

(function () {

    const _STATIC_URL = '/layers/railways/kanto_railways.geojson';
    const _MIN_ZOOM   = 8;
    const _DEBOUNCE_MS = 300;

    // ── 路線公式カラー辞書 ────────────────────────────────────────────────────
    // 路線名（日本語）→ 公式ラインカラー

    const _LINE_COLORS = {
        '山手線':           '#9ACD32',
        '中央線':           '#F15A22',
        '中央線快速':       '#F15A22',
        '中央快速線':       '#F15A22',
        '中央本線':         '#F15A22',
        '中央緩行線':       '#FFD400',
        '京浜東北線':       '#00A7E3',
        '根岸線':           '#00A7E3',
        '総武線':           '#FFD400',
        '総武線各駅停車':   '#FFD400',
        '中央・総武線':     '#FFD400',
        '総武緩行線':       '#FFD400',
        '総武快速線':       '#006DB3',
        '総武本線':         '#006DB3',
        '京葉線':           '#E85298',
        '埼京線':           '#00AC9A',
        '赤羽線':           '#00AC9A',
        '川越線':           '#00AC9A',
        '常磐線':           '#00B261',
        '常磐快速線':       '#00B261',
        '常磐緩行線':       '#00B261',
        '武蔵野線':         '#F68B1E',
        '横浜線':           '#00A94F',
        '南武線':           '#F5A200',
        '高崎線':           '#F15A22',
        '宇都宮線':         '#F15A22',
        '東北本線':         '#F15A22',
        '横須賀線':         '#006DB3',
        '青梅線':           '#F15A22',
        '相模線':           '#00A94F',
        '湘南新宿ライン':   '#F15A22',
        '内房線':           '#0068B7',
        '外房線':           '#0068B7',
        '成田線':           '#00B261',
        '日光線':           '#F15A22',
        '銀座線':           '#F39700',
        '丸ノ内線':         '#E60012',
        '日比谷線':         '#9C9EA0',
        '東西線':           '#00A7DB',
        '千代田線':         '#009944',
        '有楽町線':         '#C1A03E',
        '半蔵門線':         '#8F76D6',
        '南北線':           '#00ACA5',
        '副都心線':         '#8B6239',
        '都営浅草線':       '#E4007F',
        '浅草線':           '#E4007F',
        '都営三田線':       '#0079C2',
        '三田線':           '#0079C2',
        '都営新宿線':       '#6CBB5A',
        '新宿線':           '#6CBB5A',
        '都営大江戸線':     '#C84E00',
        '大江戸線':         '#C84E00',
        '東京さくらトラム': '#E9546B',
        '都電荒川線':       '#E9546B',
        '日暮里・舎人ライナー': '#CD8A00',
        '小田急線':         '#2288CC',
        '小田急小田原線':   '#2288CC',
        '小田急電鉄小田原線': '#2288CC',
        '小田急江ノ島線':   '#2288CC',
        '小田急電鉄江ノ島線': '#2288CC',
        '小田急多摩線':     '#2288CC',
        '小田急電鉄多摩線': '#2288CC',
        '京王線':           '#DD0077',
        '京王電鉄京王線':   '#DD0077',
        '京王相模原線':     '#DD0077',
        '京王電鉄相模原線': '#DD0077',
        '京王高尾線':       '#DD0077',
        '京王電鉄高尾線':   '#DD0077',
        '井の頭線':         '#3994C3',
        '京王電鉄井の頭線': '#3994C3',
        '東急東横線':       '#DA0442',
        '東急田園都市線':   '#20A288',
        '東急目黒線':       '#00BB85',
        '東急大井町線':     '#EE86A7',
        '東急池上線':       '#D9A700',
        '東急多摩川線':     '#AE0378',
        '西武池袋線':       '#F39800',
        '西武新宿線':       '#00A6BF',
        '西武拝島線':       '#00A6BF',
        '西武多摩湖線':     '#00A6BF',
        '東武スカイツリーライン': '#F6873A',
        '東武伊勢崎線':     '#F6873A',
        '伊勢崎線':         '#F6873A',
        '東武東上線':       '#004098',
        '東武野田線':       '#33A23D',
        '京急本線':         '#E5171F',
        '京浜急行電鉄本線': '#E5171F',
        '京急空港線':       '#E5171F',
        '京急久里浜線':     '#E5171F',
        '京浜急行電鉄久里浜線': '#E5171F',
        '京成本線':         '#E85B11',
        '京成押上線':       '#E85B11',
        '京成千葉線':       '#E85B11',
        '京成成田空港線':   '#E85B11',
        '北総線':           '#00A0E9',
        'つくばエクスプレス': '#00B274',
        'ゆりかもめ':       '#00ADEE',
        'りんかい線':       '#00ABC4',
        '東京モノレール':   '#80CBC4',
        '多摩モノレール':   '#009FE8',
        'ブルーライン':     '#0080CB',
        '横浜市営地下鉄ブルーライン': '#0080CB',
        '横浜市営1号線':    '#0080CB',
        '横浜市営3号線':    '#0080CB',
        'グリーンライン':   '#4CAF50',
        '横浜市営地下鉄グリーンライン': '#4CAF50',
        '東海道本線':       '#F15A22',
        '東海道新幹線':     '#0068B7',
        '東北新幹線':       '#009944',
        '上越新幹線':       '#E60012',
        '北陸新幹線':       '#C1A03E',
    };

    const _FALLBACK_COLOR = '#8FA3B0';
    const _ROUTE_KEY_FALLBACK_PREFIX = '__route__';

    // ── ODPT railway_id → OSM name 対応辞書（主要路線） ────────────────────────

    const _ODPT_TO_OSM = {
        'odpt.Railway:JR-East.Yamanote':                ['山手線'],
        'odpt.Railway:JR-East.ChuoRapid':               ['中央線', '中央快速線'],
        'odpt.Railway:JR-East.ChuoSobuLocal':           ['中央・総武線', '総武線'],
        'odpt.Railway:JR-East.SobuLocal':               ['中央・総武線', '総武線'],
        'odpt.Railway:JR-East.KeihinTohokuNegishi':     ['京浜東北線', '根岸線'],
        'odpt.Railway:JR-East.Joban':                   ['常磐線'],
        'odpt.Railway:JR-East.JobanRapid':              ['常磐快速線', '常磐線'],
        'odpt.Railway:JR-East.JobanLocal':              ['常磐緩行線', '常磐線'],
        'odpt.Railway:JR-East.Musashino':               ['武蔵野線'],
        'odpt.Railway:JR-East.Yokohama':                ['横浜線'],
        'odpt.Railway:JR-East.Nambu':                   ['南武線'],
        'odpt.Railway:JR-East.Saikyo':                  ['埼京線'],
        'odpt.Railway:JR-East.SaikyoKawagoe':           ['埼京線', '川越線'],
        'odpt.Railway:JR-East.Takasaki':                ['高崎線'],
        'odpt.Railway:JR-East.Utsunomiya':              ['宇都宮線'],
        'odpt.Railway:JR-East.Keiyo':                   ['京葉線'],
        'odpt.Railway:JR-East.Shonan-Shinjuku':         ['湘南新宿ライン'],
        'odpt.Railway:JR-East.ShonanShinjuku':          ['湘南新宿ライン'],
        'odpt.Railway:JR-East.SobuRapid':               ['総武快速線', '総武線'],
        'odpt.Railway:JR-East.Uchibo':                  ['内房線'],
        'odpt.Railway:JR-East.Sotobou':                 ['外房線'],
        'odpt.Railway:JR-East.Nikko':                   ['日光線'],
        'odpt.Railway:TokyoMetro.Ginza':                ['銀座線'],
        'odpt.Railway:TokyoMetro.Marunouchi':           ['丸ノ内線'],
        'odpt.Railway:TokyoMetro.Hibiya':               ['日比谷線'],
        'odpt.Railway:TokyoMetro.Tozai':                ['東西線'],
        'odpt.Railway:TokyoMetro.Chiyoda':              ['千代田線'],
        'odpt.Railway:TokyoMetro.Yurakucho':            ['有楽町線'],
        'odpt.Railway:TokyoMetro.Hanzomon':             ['半蔵門線'],
        'odpt.Railway:TokyoMetro.Namboku':              ['南北線'],
        'odpt.Railway:TokyoMetro.Fukutoshin':           ['副都心線'],
        'odpt.Railway:Toei.Asakusa':                    ['都営浅草線'],
        'odpt.Railway:Toei.Mita':                       ['都営三田線'],
        'odpt.Railway:Toei.Shinjuku':                   ['都営新宿線'],
        'odpt.Railway:Toei.Oedo':                       ['都営大江戸線'],
        'odpt.Railway:Toei.Arakawa':                    ['東京さくらトラム', '都電荒川線'],
        'odpt.Railway:Toei.NipporiToneri':              ['日暮里・舎人ライナー'],
        'odpt.Railway:Odakyu.Odawara':                  ['小田急小田原線', '小田急線'],
        'odpt.Railway:Odakyu.Enoshima':                 ['小田急江ノ島線'],
        'odpt.Railway:Odakyu.Tama':                     ['小田急多摩線'],
        'odpt.Railway:Keio.Keio':                       ['京王線'],
        'odpt.Railway:Keio.Sagamihara':                 ['京王相模原線'],
        'odpt.Railway:Keio.Takao':                      ['京王高尾線'],
        'odpt.Railway:Keio.Inokashira':                 ['井の頭線'],
        'odpt.Railway:Tokyu.Toyoko':                    ['東急東横線'],
        'odpt.Railway:Tokyu.DenEnToshi':                ['東急田園都市線'],
        'odpt.Railway:Tokyu.Meguro':                    ['東急目黒線'],
        'odpt.Railway:Tokyu.Oimachi':                   ['東急大井町線'],
        'odpt.Railway:Tokyu.Ikegami':                   ['東急池上線'],
        'odpt.Railway:Seibu.Ikebukuro':                 ['西武池袋線'],
        'odpt.Railway:Seibu.Shinjuku':                  ['西武新宿線'],
        'odpt.Railway:Tobu.TobuSkytree':                ['東武スカイツリーライン', '東武伊勢崎線'],
        'odpt.Railway:Tobu.TobuTojo':                   ['東武東上線'],
        'odpt.Railway:Keikyu.Main':                     ['京急本線'],
        'odpt.Railway:Keikyu.Airport':                  ['京急空港線'],
        'odpt.Railway:Keisei.Main':                     ['京成本線'],
        'odpt.Railway:Keisei.Oshiage':                  ['京成押上線'],
        'odpt.Railway:MIR.TX':                          ['つくばエクスプレス'],
        'odpt.Railway:MIR.TsukubaExpress':              ['つくばエクスプレス'],
        'odpt.Railway:Yurikamome.Yurikamome':           ['ゆりかもめ'],
        'odpt.Railway:TWR.Rinkai':                      ['りんかい線'],
        'odpt.Railway:TokyoMonorail.HanedaAirport':     ['東京モノレール'],
        'odpt.Railway:TamaMonorail.TamaMonorail':       ['多摩モノレール'],
        'odpt.Railway:YokohamaMunicipal.Blue':          ['ブルーライン', '横浜市営地下鉄ブルーライン'],
        'odpt.Railway:YokohamaMunicipal.Green':         ['グリーンライン', '横浜市営地下鉄グリーンライン'],
    };

    // 表示対象の railway タグ値（営業路線のみ）
    const _INCLUDE_RAILWAY = new Set(['rail', 'subway', 'light_rail', 'monorail', 'tram']);
    const _EXCLUDE_RAILWAY = new Set(['service', 'siding', 'yard', 'platform', 'station', 'spur']);
    const _EXCLUDE_SERVICE = new Set(['yard', 'siding', 'spur', 'crossover']);
    const _EXCLUDE_USAGE   = new Set(['industrial']);

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    // liveMap は preferCanvas: true のため GeoJSON に明示的に SVG renderer を指定
    const _svgRenderer = L.svg();

    let _enabled        = false;
    let _baseLayer      = null;
    let _haloLayers     = [];   // 障害路線ハローレイヤーのリスト（cleanup用）
    let _lastItems      = [];
    let _fetchTimer     = null;
    let _lastBoundsKey  = null;
    let _listenersAdded = false;

    // 静的GeoJSONを一度だけ読み込んでキャッシュ
    let _allFeatures   = null; // Feature[]
    let _loadPromise   = null;

    // ── 路線カラー解決 ────────────────────────────────────────────────────────

    function _lineNameCandidates(props) {
        return [
            props._live_route_name,
            props.name,
            props.name_ja,
            props.name_en,
            props.ref,
            props.line,
            props.route_name,
            props.operator,
        ].filter(Boolean).map(v => String(v));
    }

    function _resolveLineColor(props) {
        if (props._live_route_color) return props._live_route_color;
        const candidates = _lineNameCandidates(props);
        for (const name of candidates) {
            if (_LINE_COLORS[name]) return _LINE_COLORS[name];
        }
        // 部分一致（例: 「東京メトロ銀座線」→ 「銀座線」キーにヒット）
        const colorKeys = Object.keys(_LINE_COLORS).sort((a, b) => b.length - a.length);
        for (const name of candidates) {
            for (const key of colorKeys) {
                if (name.includes(key)) return _LINE_COLORS[key];
            }
        }
        return _FALLBACK_COLOR;
    }

    // ── フィルタリング ────────────────────────────────────────────────────────

    function _isMainLine(feat) {
        const props = feat.properties || {};
        const railway = props.railway || '';
        const service = props.service || '';
        const usage   = props.usage || '';
        const name    = String(props.name || props.name_ja || '').trim();
        if (!name) return false;
        if (_EXCLUDE_RAILWAY.has(railway)) return false;
        if (_EXCLUDE_SERVICE.has(service)) return false;
        if (_EXCLUDE_USAGE.has(usage)) return false;
        if (name.includes('貨物線')) return false;
        return _INCLUDE_RAILWAY.has(railway);
    }

    function _routeKey(props) {
        const name = String(props.name || props.name_ja || props.ref || '').trim();
        if (name) return name.replace(/\s+/g, ' ');
        return `${_ROUTE_KEY_FALLBACK_PREFIX}${props.osm_id || 'unknown'}`;
    }

    function _coordinatesAsLines(geometry) {
        if (!geometry) return [];
        if (geometry.type === 'LineString') return [geometry.coordinates || []];
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

    function _mergeVisibleByRoute(features) {
        const byRoute = new Map();
        features.forEach(feat => {
            const props = feat.properties || {};
            const key = _routeKey(props);
            const lines = _coordinatesAsLines(feat.geometry).filter(line => line.length >= 2);
            if (!lines.length) return;
            if (!byRoute.has(key)) {
                const mergedProps = {
                    ...props,
                    _live_route_key: key,
                    _live_route_name: String(props.name || props.name_ja || props.ref || key),
                };
                mergedProps._live_route_color = _resolveLineColor(mergedProps);
                byRoute.set(key, {
                    type: 'Feature',
                    properties: mergedProps,
                    geometry: { type: 'MultiLineString', coordinates: [] },
                });
            }
            const route = byRoute.get(key);
            route.geometry.coordinates.push(...lines);
        });
        return Array.from(byRoute.values());
    }

    // ── スタイル ──────────────────────────────────────────────────────────────

    function _routeStyle(feature) {
        const color = _resolveLineColor(feature?.properties || {});
        return { color, weight: 1.8, opacity: 0.55, fillOpacity: 0, dashArray: null };
    }

    function _disruptedMainStyle(feature, status) {
        const color = _resolveLineColor(feature?.properties || {});
        if (status === 'delay') {
            return { color, weight: 3.5, opacity: 0.95, fillOpacity: 0, dashArray: null };
        }
        if (status === 'partial_suspension') {
            return { color, weight: 4.0, opacity: 0.95, fillOpacity: 0, dashArray: '8 6' };
        }
        if (status === 'suspended') {
            return { color, weight: 4.5, opacity: 1.0, fillOpacity: 0, dashArray: null };
        }
        return { color, weight: 3.5, opacity: 0.95, fillOpacity: 0, dashArray: null };
    }

    function _haloStyle(status) {
        const h = {
            delay:              { color: 'rgba(255,213,79,0.55)',  weight: 6 },
            partial_suspension: { color: 'rgba(255,152,0,0.6)',    weight: 7 },
            suspended:          { color: 'rgba(244,67,54,0.75)',   weight: 8 },
        };
        const s = h[status] || h.delay;
        return { color: s.color, weight: s.weight, opacity: 1, fillOpacity: 0, dashArray: null };
    }

    // ── 静的GeoJSON読み込み（初回のみ） ──────────────────────────────────────

    function _loadStatic() {
        if (_loadPromise) return _loadPromise;
        _loadPromise = fetch(_STATIC_URL)
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then(fc => {
                _allFeatures = (fc.features || []).filter(_isMainLine);
                console.info(`[live-train-osm] 静的路線データ読み込み完了: ${_allFeatures.length} フィーチャー`);
                return _allFeatures;
            })
            .catch(e => {
                _loadPromise = null; // 次回リトライ可能にする
                throw e;
            });
        return _loadPromise;
    }

    // ── bounds フィルタリング ──────────────────────────────────────────────────

    function _featuresInBounds(features, bounds) {
        return features.filter(feat => _featureIntersectsBounds(feat, bounds));
    }

    // ── ODPT マッチング ────────────────────────────────────────────────────────

    function _findMatch(props, items) {
        const haystack = _lineNameCandidates(props).join(' ').toLowerCase();
        for (const item of items) {
            for (const alias of (_ODPT_TO_OSM[item.railway_id] || [])) {
                const a = alias.toLowerCase();
                if (haystack.includes(a)) return item;
            }
        }
        return null;
    }

    function _esc(v) {
        return String(v ?? '').replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function _buildPopup(item) {
        return `<b>${_esc(item.railway_name)}</b><br>`
            + `事業者: ${_esc(item.operator_name)}<br>`
            + `状態: ${_esc(item.status_label)}<br>`
            + (item.description ? `説明: <small>${_esc(item.description)}</small><br>` : '')
            + `更新時刻: ${_esc(item.updated_at)}<br>`
            + `出典: ${_esc(item.source || 'ODPT')}`;
    }

    // ── ハロー管理 ─────────────────────────────────────────────────────────────

    function _clearHalos() {
        const map = window.liveMap;
        _haloLayers.forEach(l => { try { if (map) map.removeLayer(l); } catch (_) {} });
        _haloLayers = [];
    }

    // ── 障害スタイル適用 ──────────────────────────────────────────────────────

    function _applyDisruptions(items) {
        const matched = new Set();
        if (!_baseLayer) return matched;
        const map = window.liveMap;

        _clearHalos();

        const haloEntries   = []; // { feature, status }
        const matchedLayers = []; // 障害にマッチした主線レイヤー

        _baseLayer.eachLayer(fl => {
            const props = fl.feature?.properties || {};
            const match = _findMatch(props, items);
            if (match) {
                fl.setStyle(_disruptedMainStyle(fl.feature, match.status));
                fl.bindPopup(_buildPopup(match));
                matched.add(match.railway_id);
                haloEntries.push({ feature: fl.feature, status: match.status });
                matchedLayers.push(fl);
            } else {
                fl.setStyle(_routeStyle(fl.feature));
                fl.unbindPopup();
            }
        });

        // ハローを追加してから障害路線の主線のみ前面に移動（非障害路線は動かさない）
        if (map && haloEntries.length) {
            haloEntries.forEach(({ feature, status }) => {
                const hl = L.geoJSON(feature, {
                    style: _haloStyle(status),
                    renderer: _svgRenderer,
                    interactive: false, // ハローは非インタラクティブ（クリック干渉を防ぐ）
                }).addTo(map);
                _haloLayers.push(hl);
            });
            // ハロー追加後に障害路線のみ前面へ → SVG末尾 = 障害路線主線
            matchedLayers.forEach(fl => {
                try { fl.bringToFront(); } catch (_) {}
            });
        }

        return matched;
    }

    // ── 描画メインフロー ──────────────────────────────────────────────────────

    async function _refresh() {
        if (!_enabled || !window.liveMap) return;
        const map  = window.liveMap;
        const zoom = map.getZoom();
        if (zoom < _MIN_ZOOM) {
            if (_baseLayer) { map.removeLayer(_baseLayer); _baseLayer = null; }
            _clearHalos();
            return;
        }
        const bounds = map.getBounds();
        const key = [
            bounds.getSouth(), bounds.getWest(), bounds.getNorth(), bounds.getEast(),
        ].map(v => v.toFixed(2)).join(',');
        if (key === _lastBoundsKey) return;
        _lastBoundsKey = key;

        try {
            const features = await _loadStatic();
            const visible  = _mergeVisibleByRoute(_featuresInBounds(features, bounds));

            _clearHalos();
            if (_baseLayer) map.removeLayer(_baseLayer);

            _baseLayer = L.geoJSON(
                { type: 'FeatureCollection', features: visible },
                { style: _routeStyle, renderer: _svgRenderer }
            ).addTo(map);

            const matched = _applyDisruptions(_lastItems);
            window.liveTrainLayer?.updateMatched?.(matched);
            // ラベル層に集約済み路線フィーチャーを渡す
            window.liveTrainLabelLayer?.setRouteFeatures?.(visible);
        } catch (e) {
            console.warn('[live-train-osm] 路線データ読み込み失敗:', e.message);
        }
    }

    function _scheduleRefresh() {
        if (_fetchTimer) clearTimeout(_fetchTimer);
        _fetchTimer = setTimeout(_refresh, _DEBOUNCE_MS);
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    function setDisruptions(items) {
        _lastItems = Array.isArray(items) ? items : [];
        const matched = _applyDisruptions(_lastItems);
        window.liveTrainLabelLayer?.setDisruptions?.(_lastItems);
        return matched;
    }

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
            window.liveTrainLabelLayer?.setVisible?.(true);
        } else {
            _clearHalos();
            if (_baseLayer) { map.removeLayer(_baseLayer); _baseLayer = null; }
            _lastBoundsKey = null;
            window.liveTrainLabelLayer?.setVisible?.(false);
        }
    }

    // カードクリック → 該当路線へ fitBounds + 描画
    // 現在のズームレベル・画面範囲に関わらず全フィーチャーから路線を探して表示する
    async function focusRailway(railway_id) {
        const map = window.liveMap;
        if (!map) return;

        // 静的データを確保（キャッシュ済みなら即返る）
        let allFeatures;
        try {
            allFeatures = await _loadStatic();
        } catch (e) {
            console.warn('[live-train-osm] focusRailway: データ読み込み失敗', e);
            const fb = _lastItems.find(i => i.railway_id === railway_id);
            if (fb?.lat != null) map.flyTo([fb.lat, fb.lng], 10);
            return;
        }

        // 対象路線の全フィーチャーを抽出（現在の bounds を無視）
        const aliases = _ODPT_TO_OSM[railway_id] || [];
        const matching = aliases.length
            ? allFeatures.filter(feat => {
                const haystack = _lineNameCandidates(feat.properties || {}).join(' ').toLowerCase();
                return aliases.some(a => haystack.includes(a.toLowerCase()));
            })
            : [];

        if (!matching.length) {
            // GeoJSONにマッチしない路線 → 代表座標へフォールバック
            const fb = _lastItems.find(i => i.railway_id === railway_id);
            if (fb?.lat != null) map.flyTo([fb.lat, fb.lng], 10);
            return;
        }

        // 路線全体の bounds を計算
        const bounds = L.latLngBounds([]);
        matching.forEach(feat => {
            _coordinatesAsLines(feat.geometry).forEach(line =>
                line.forEach(([lon, lat]) => bounds.extend([lat, lon]))
            );
        });

        if (!bounds.isValid()) return;

        // fitBounds: minZoom:8 で _MIN_ZOOM チェックを確実にパスさせる
        map.fitBounds(bounds, { padding: [40, 40], minZoom: 8, maxZoom: 12 });

        // boundsキャッシュを無効化 → moveend 後の _refresh で必ず再描画
        _lastBoundsKey = null;
        // moveend を待たず即時もスケジュール（debounce 込み）
        _scheduleRefresh();
    }

    window.liveTrainOsmLayer = { setDisruptions, setVisible, focusRailway };

})();
