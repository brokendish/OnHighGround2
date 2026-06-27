'use strict';
// live-train-pmtiles-layer.js — 全国鉄道路線 PMTiles ベース表示レイヤー
// protomaps-leaflet を使い PMTiles から全国路線・駅を描画する。
//
// Phase 7-A.5-A: 路線ベース表示（全国・路線色）
// Phase 7-A.5-B: 駅アイコン・駅名表示（zoom 制御付き）
//
// 依存: protomaps-leaflet が window.protomapsL として読み込まれていること
//       PMTiles ファイル: /layers/railways/railways_japan.pmtiles
//       （build_railway_pmtiles.sh で生成）
//
// 共存: live-train-osm-layer.js との競合なし。
//       PMTilesが関東GeoJSONのベース描画を置き換えるため、GeoJSONレイヤーは
//       障害路線強調オーバーレイのみを担う（Phase 7-A.5-C参照）。

(function () {

    const _PMTILES_URL = '/layers/railways/railways_japan.pmtiles';
    // PMTilesファイルに含まれる最大ズームレベル（tippecanoe -z 14 に対応）。
    // これを超えるズームでは z14 タイルをオーバーズームして継続表示する。
    const _MAX_DATA_ZOOM = 14;

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    let _layer   = null;
    let _enabled = false;
    let _ready   = false;
    let _requestSeq = 0;

    // ── 路線カラーマップ（live-train-osm-layer.js と共通） ──────────────────

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

    const _COLOR_KEYS_SORTED = Object.keys(_LINE_COLORS).sort((a, b) => b.length - a.length);

    function _resolveRailColor(props) {
        const candidates = [
            props.name,
            props['name:ja'],
            props['name:en'],
            props.ref,
            props.operator,
        ].filter(Boolean).map(String);

        for (const name of candidates) {
            if (_LINE_COLORS[name]) return _LINE_COLORS[name];
        }
        // 部分一致（「東京メトロ銀座線」→「銀座線」ヒット）
        for (const name of candidates) {
            for (const key of _COLOR_KEYS_SORTED) {
                if (name.includes(key)) return _LINE_COLORS[key];
            }
        }
        return _FALLBACK_COLOR;
    }

    // ── ズーム別スタイル ───────────────────────────────────────────────────────

    function _railWidth(zoom) {
        if (zoom <= 6) return 0.4;
        if (zoom <= 8) return 0.7;
        if (zoom <= 10) return 1.1;
        if (zoom <= 12) return 1.6;
        return 2.0;
    }

    function _railOpacity(zoom) {
        if (zoom <= 6) return 0.35;
        if (zoom <= 8) return 0.45;
        if (zoom <= 10) return 0.55;
        return 0.70;
    }

    const _EXCLUDE_SERVICE = new Set(['yard', 'siding', 'spur', 'crossover']);

    function _isDisplayable(zoom, f) {
        const svc = f.props.service || '';
        const usage = f.props.usage || '';
        if (_EXCLUDE_SERVICE.has(svc)) return false;
        if (usage === 'industrial') return false;
        return true;
    }

    function _buildPaintRules() {
        const P = window.protomapsL;
        return [
            {
                dataLayer: 'railways',
                filter: _isDisplayable,
                symbolizer: new P.LineSymbolizer({
                    color:   (zoom, f) => _resolveRailColor(f.props),
                    width:   _railWidth,
                    opacity: _railOpacity,
                }),
            },
            {
                dataLayer: 'stations',
                minzoom: 11,
                symbolizer: new P.CircleSymbolizer({
                    fill:    '#6b7280',
                    radius:  3,
                    stroke:  '#ffffff',
                    width:   1,
                    opacity: 0.75,
                }),
            },
        ];
    }

    function _buildLabelRules() {
        const P = window.protomapsL;
        return [
            // ── 路線名ラベル：全国（zoom 9+, 路線色でライン沿い表示）──────────
            {
                dataLayer: 'railways',
                filter: _isDisplayable,
                minzoom: 9,
                symbolizer: new P.LineLabelSymbolizer({
                    label_props: ['name'],
                    fill:   (zoom, f) => _resolveRailColor(f.props),
                    stroke: '#00000099',
                    width:  3,
                    font:   (zoom) => {
                        if (zoom >= 13) return 'bold 10px sans-serif';
                        return '9px sans-serif';
                    },
                }),
            },

            // ── 駅名ラベル（zoom 12+）────────────────────────────────────────
            {
                dataLayer: 'stations',
                minzoom: 12,
                symbolizer: new P.CenteredTextSymbolizer({
                    label_props: ['name'],
                    fill:        '#e2e8f0',
                    stroke:      '#00000099',
                    width:       2,
                    font:        (zoom) => {
                        if (zoom >= 14) return 'bold 11px sans-serif';
                        return '10px sans-serif';
                    },
                }),
            },
        ];
    }

    // ── レイヤー生成 ──────────────────────────────────────────────────────────

    function _createLayer() {
        if (!window.protomapsL) {
            console.warn('[live-train-pmtiles] protomaps-leaflet が読み込まれていません');
            return null;
        }
        const P = window.protomapsL;
        try {
            const layer = P.leafletLayer({
                url:         _PMTILES_URL,
                paintRules:  _buildPaintRules(),
                labelRules:  _buildLabelRules(),
                // PMTilesはz14まで。z15以上はz14タイルをオーバーズームして継続表示。
                maxDataZoom: _MAX_DATA_ZOOM,
                maxZoom:     20,
                attribution: '© OpenStreetMap contributors',
            });
            console.info('[live-train-pmtiles] PMTilesレイヤー生成完了:', _PMTILES_URL);
            return layer;
        } catch (e) {
            console.error('[live-train-pmtiles] レイヤー生成失敗:', e.message);
            return null;
        }
    }

    // ── PMTiles ファイル存在確認 ──────────────────────────────────────────────

    let _probeResult = null;

    async function _probeFile() {
        if (_probeResult !== null) return _probeResult;
        try {
            const res = await fetch(_PMTILES_URL, { method: 'HEAD' });
            _probeResult = res.ok;
        } catch {
            _probeResult = false;
        }
        return _probeResult;
    }

    // ── 公開 API ──────────────────────────────────────────────────────────────

    async function setVisible(visible) {
        const seq = ++_requestSeq;
        _enabled = visible;
        const map = window.liveMap;
        if (!map) return;

        if (visible) {
            const exists = await _probeFile();
            if (seq !== _requestSeq || !_enabled) return;
            if (!exists) {
                console.warn('[live-train-pmtiles] PMTilesファイルが見つかりません:', _PMTILES_URL);
                console.info('[live-train-pmtiles] フォールバック: 関東GeoJSONのみ使用');
                return;
            }

            if (!window.protomapsL) {
                console.warn('[live-train-pmtiles] protomaps-leaflet 未ロード。フォールバック。');
                return;
            }

            if (!_layer) {
                _layer = _createLayer();
                if (!_layer) return;
            }
            if (!map.hasLayer(_layer)) {
                _layer.addTo(map);
            }
            _ready = true;
        } else {
            if (_layer && map.hasLayer(_layer)) {
                map.removeLayer(_layer);
            }
            _ready = false;
        }
    }

    function isReady() {
        return _ready && !!_layer;
    }

    window.liveTrainPmtilesLayer = { setVisible, isReady };

})();
