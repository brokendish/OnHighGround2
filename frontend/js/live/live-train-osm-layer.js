'use strict';
// live-train-osm-layer.js — OSM鉄道路線ベースレイヤー + ODPT障害路線強調
// MVPでは Overpass API で表示範囲内の路線を取得し、ODPT障害情報と照合してスタイルを変える。
// zoom < _MIN_ZOOM では描画しない（全国一括描画禁止）。

(function () {

    const _RAILWAY_OSM_URL = '/api/live/trains/osm';
    const _MIN_ZOOM     = 8;
    const _DEBOUNCE_MS  = 500;

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

    const _RAILWAY_TYPES   = new Set(['rail', 'subway', 'light_rail', 'monorail']);
    const _EXCLUDE_SERVICE = new Set(['yard', 'siding', 'service', 'platform', 'station']);

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    // liveMap は preferCanvas: true のため GeoJSON に明示的に SVG renderer を指定
    const _svgRenderer = L.svg();

    let _enabled        = false;
    let _baseLayer      = null;
    let _lastItems      = [];
    let _fetchTimer     = null;
    let _lastBoundsKey  = null;
    let _listenersAdded = false;

    // ── スタイル ──────────────────────────────────────────────────────────────

    function _baseStyle() {
        return { color: '#888888', weight: 1.5, opacity: 0.3, fillOpacity: 0 };
    }

    function _disruptedStyle(status) {
        const colors = { delay: '#FFD54F', partial_suspension: '#FF9800', suspended: '#F44336' };
        return { color: colors[status] || '#FF9800', weight: 4, opacity: 0.9, fillOpacity: 0 };
    }

    // ── Overpass API 取得 ─────────────────────────────────────────────────────

    async function _fetchRailways(bounds) {
        const s = bounds.getSouth().toFixed(4);
        const w = bounds.getWest().toFixed(4);
        const n = bounds.getNorth().toFixed(4);
        const e = bounds.getEast().toFixed(4);
        const res = await fetch(`${_RAILWAY_OSM_URL}?south=${s}&west=${w}&north=${n}&east=${e}`);
        if (!res.ok) throw new Error(`railway osm HTTP ${res.status}`);
        return res.json();
    }

    function _toGeoJSON(data) {
        const features = [];
        for (const el of data.elements || []) {
            if (el.type !== 'way' || !el.geometry?.length) continue;
            const tags = el.tags || {};
            if (!_RAILWAY_TYPES.has(tags.railway)) continue;
            if (_EXCLUDE_SERVICE.has(tags.service)) continue;
            features.push({
                type: 'Feature',
                properties: {
                    osm_id:  el.id,
                    name:    tags.name       || '',
                    name_en: tags['name:en'] || '',
                    railway: tags.railway,
                },
                geometry: {
                    type:        'LineString',
                    coordinates: el.geometry.map(n => [n.lon, n.lat]),
                },
            });
        }
        return { type: 'FeatureCollection', features };
    }

    // ── ODPT マッチング ────────────────────────────────────────────────────────

    function _findMatch(props, items) {
        const n  = (props.name    || '').toLowerCase();
        const ne = (props.name_en || '').toLowerCase();
        for (const item of items) {
            for (const alias of (_ODPT_TO_OSM[item.railway_id] || [])) {
                const a = alias.toLowerCase();
                if (n.includes(a) || ne.includes(a)) return item;
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

    // マッチした障害路線にスタイルを適用。マッチした railway_id の Set を返す。
    function _applyDisruptions(items) {
        const matched = new Set();
        if (!_baseLayer) return matched;
        _baseLayer.eachLayer(fl => {
            const props = fl.feature?.properties || {};
            const match = _findMatch(props, items);
            if (match) {
                fl.setStyle(_disruptedStyle(match.status));
                fl.bindPopup(_buildPopup(match));
                fl.bringToFront();
                matched.add(match.railway_id);
            } else {
                fl.setStyle(_baseStyle());
                fl.unbindPopup();
            }
        });
        return matched;
    }

    // ── 取得・描画メインフロー ─────────────────────────────────────────────────

    async function _refresh() {
        if (!_enabled || !window.liveMap) return;
        const map  = window.liveMap;
        const zoom = map.getZoom();
        if (zoom < _MIN_ZOOM) {
            if (_baseLayer) { map.removeLayer(_baseLayer); _baseLayer = null; }
            return;
        }
        const bounds = map.getBounds();
        const key = [
            bounds.getSouth(), bounds.getWest(), bounds.getNorth(), bounds.getEast(),
        ].map(v => v.toFixed(2)).join(',');
        if (key === _lastBoundsKey) return;
        _lastBoundsKey = key;

        try {
            const raw     = await _fetchRailways(bounds);
            const geojson = _toGeoJSON(raw);
            if (_baseLayer) map.removeLayer(_baseLayer);
            _baseLayer = L.geoJSON(geojson, { style: _baseStyle, renderer: _svgRenderer }).addTo(map);
            const matched = _applyDisruptions(_lastItems);
            // マーカーレイヤーにマッチ済みIDを通知（OSMで描画済みのマーカーを非表示に）
            window.liveTrainLayer?.updateMatched?.(matched);
        } catch (e) {
            console.warn('[live-train-osm] 鉄道路線取得失敗:', e.message);
        }
    }

    function _scheduleRefresh() {
        if (_fetchTimer) clearTimeout(_fetchTimer);
        _fetchTimer = setTimeout(_refresh, _DEBOUNCE_MS);
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    // 障害データをOSM路線に適用し、マッチした railway_id の Set を返す。
    function setDisruptions(items) {
        _lastItems = Array.isArray(items) ? items : [];
        return _applyDisruptions(_lastItems);
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
        } else {
            if (_baseLayer) { map.removeLayer(_baseLayer); _baseLayer = null; }
            _lastBoundsKey = null;
        }
    }

    window.liveTrainOsmLayer = { setDisruptions, setVisible };

})();
