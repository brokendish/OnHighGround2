/**
 * earthquake-intensity-layer.js — 震度分布マーカーレイヤー (Phase 1–4)
 *
 * 依存: Leaflet (map グローバル変数)
 * 公開: formatJmaIntensity, normalizeEarthquakePointName,
 *       extractIntensityPoints, resolveIntensityPointLocation,
 *       renderEarthquakeIntensityMarkers, clearEarthquakeIntensityMarkers
 */
(function () {

    // ── P2P scale → 震度表示文字列 ────────────────────────────────────────────
    const _SCALE_MAP = {
        10: '1', 20: '2', 30: '3', 40: '4',
        45: '5弱', 50: '5強', 55: '6弱', 60: '6強', 70: '7',
    };

    window.formatJmaIntensity = function (scale) {
        return _SCALE_MAP[Number(scale)] ?? null;
    };

    // ── 観測点名正規化 ────────────────────────────────────────────────────────
    window.normalizeEarthquakePointName = function (pref, addr) {
        const _norm = s => String(s || '').trim()
            .replace(/\s+/g, '')
            .replace(/[０-９]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0));
        return { pref: _norm(pref), addr: _norm(addr) };
    };

    // ── 観測点座標辞書（東京・神奈川） ─────────────────────────────────────────
    // キー: "都道府県名|地点名"  値: { lat, lon }
    const _COORD_DICT = {
        // 東京都 23区
        '東京都|千代田区':   { lat: 35.6940, lon: 139.7536 },
        '東京都|中央区':     { lat: 35.6702, lon: 139.7730 },
        '東京都|港区':       { lat: 35.6581, lon: 139.7514 },
        '東京都|新宿区':     { lat: 35.6938, lon: 139.7036 },
        '東京都|文京区':     { lat: 35.7077, lon: 139.7520 },
        '東京都|台東区':     { lat: 35.7127, lon: 139.7811 },
        '東京都|墨田区':     { lat: 35.7101, lon: 139.8014 },
        '東京都|江東区':     { lat: 35.6720, lon: 139.8170 },
        '東京都|品川区':     { lat: 35.6094, lon: 139.7304 },
        '東京都|目黒区':     { lat: 35.6322, lon: 139.6987 },
        '東京都|大田区':     { lat: 35.5613, lon: 139.7160 },
        '東京都|世田谷区':   { lat: 35.6465, lon: 139.6536 },
        '東京都|渋谷区':     { lat: 35.6617, lon: 139.7039 },
        '東京都|中野区':     { lat: 35.7077, lon: 139.6653 },
        '東京都|杉並区':     { lat: 35.6995, lon: 139.6365 },
        '東京都|豊島区':     { lat: 35.7296, lon: 139.7188 },
        '東京都|北区':       { lat: 35.7533, lon: 139.7336 },
        '東京都|荒川区':     { lat: 35.7358, lon: 139.7832 },
        '東京都|板橋区':     { lat: 35.7510, lon: 139.6953 },
        '東京都|練馬区':     { lat: 35.7358, lon: 139.6513 },
        '東京都|足立区':     { lat: 35.7757, lon: 139.8048 },
        '東京都|葛飾区':     { lat: 35.7437, lon: 139.8473 },
        '東京都|江戸川区':   { lat: 35.7065, lon: 139.8680 },
        // 東京都 多摩地域
        '東京都|八王子市':   { lat: 35.6641, lon: 139.3163 },
        '東京都|立川市':     { lat: 35.6975, lon: 139.4081 },
        '東京都|武蔵野市':   { lat: 35.7198, lon: 139.5663 },
        '東京都|三鷹市':     { lat: 35.6828, lon: 139.5589 },
        '東京都|府中市':     { lat: 35.6702, lon: 139.4779 },
        '東京都|調布市':     { lat: 35.6515, lon: 139.5415 },
        '東京都|町田市':     { lat: 35.5483, lon: 139.4468 },
        '東京都|小金井市':   { lat: 35.6996, lon: 139.5132 },
        '東京都|小平市':     { lat: 35.7286, lon: 139.4765 },
        '東京都|日野市':     { lat: 35.6715, lon: 139.3952 },
        '東京都|東村山市':   { lat: 35.7548, lon: 139.4686 },
        '東京都|国分寺市':   { lat: 35.7020, lon: 139.4638 },
        '東京都|国立市':     { lat: 35.6847, lon: 139.4424 },
        '東京都|西東京市':   { lat: 35.7258, lon: 139.5383 },
        '東京都|多摩市':     { lat: 35.6362, lon: 139.4468 },
        '東京都|稲城市':     { lat: 35.6391, lon: 139.5053 },
        '東京都|狛江市':     { lat: 35.6333, lon: 139.5786 },
        '東京都|東大和市':   { lat: 35.7402, lon: 139.4274 },
        '東京都|清瀬市':     { lat: 35.7853, lon: 139.5256 },
        '東京都|東久留米市': { lat: 35.7560, lon: 139.5249 },
        '東京都|武蔵村山市': { lat: 35.7547, lon: 139.3874 },
        // 東京都 島嶼
        '東京都|大島町':     { lat: 34.7237, lon: 139.3579 },
        '東京都|利島村':     { lat: 34.5209, lon: 139.2874 },
        '東京都|新島村':     { lat: 34.3856, lon: 139.2710 },
        '東京都|神津島村':   { lat: 34.2029, lon: 139.1333 },
        '東京都|三宅村':     { lat: 34.0858, lon: 139.5277 },
        '東京都|御蔵島村':   { lat: 33.8990, lon: 139.5931 },
        '東京都|八丈町':     { lat: 33.1138, lon: 139.7931 },
        '東京都|青ヶ島村':   { lat: 32.4608, lon: 139.7625 },
        '東京都|小笠原村':   { lat: 27.0943, lon: 142.1977 },
        // 神奈川県 横浜市
        '神奈川県|横浜市中区':     { lat: 35.4442, lon: 139.6420 },
        '神奈川県|横浜市西区':     { lat: 35.4651, lon: 139.6228 },
        '神奈川県|横浜市磯子区':   { lat: 35.3979, lon: 139.6327 },
        '神奈川県|横浜市金沢区':   { lat: 35.3471, lon: 139.6349 },
        '神奈川県|横浜市都筑区':   { lat: 35.5424, lon: 139.5850 },
        '神奈川県|横浜市青葉区':   { lat: 35.5428, lon: 139.5278 },
        '神奈川県|横浜市緑区':     { lat: 35.5228, lon: 139.5895 },
        '神奈川県|横浜市鶴見区':   { lat: 35.5197, lon: 139.6797 },
        '神奈川県|横浜市神奈川区': { lat: 35.4917, lon: 139.6343 },
        '神奈川県|横浜市港北区':   { lat: 35.5292, lon: 139.6338 },
        '神奈川県|横浜市旭区':     { lat: 35.4581, lon: 139.5553 },
        '神奈川県|横浜市瀬谷区':   { lat: 35.4638, lon: 139.5128 },
        '神奈川県|横浜市保土ケ谷区': { lat: 35.4572, lon: 139.5972 },
        '神奈川県|横浜市泉区':     { lat: 35.4139, lon: 139.5234 },
        '神奈川県|横浜市戸塚区':   { lat: 35.4048, lon: 139.5355 },
        '神奈川県|横浜市南区':     { lat: 35.4236, lon: 139.6222 },
        '神奈川県|横浜市栄区':     { lat: 35.3861, lon: 139.5667 },
        '神奈川県|横浜市港南区':   { lat: 35.4032, lon: 139.6072 },
        // 神奈川県 川崎市
        '神奈川県|川崎市川崎区': { lat: 35.5309, lon: 139.7034 },
        '神奈川県|川崎市幸区':   { lat: 35.5372, lon: 139.6699 },
        '神奈川県|川崎市中原区': { lat: 35.5713, lon: 139.6565 },
        '神奈川県|川崎市高津区': { lat: 35.5786, lon: 139.6285 },
        '神奈川県|川崎市多摩区': { lat: 35.5992, lon: 139.5781 },
        '神奈川県|川崎市宮前区': { lat: 35.5636, lon: 139.5907 },
        '神奈川県|川崎市麻生区': { lat: 35.5929, lon: 139.5259 },
        // 神奈川県 相模原市
        '神奈川県|相模原市緑区':   { lat: 35.5878, lon: 139.3751 },
        '神奈川県|相模原市中央区': { lat: 35.5699, lon: 139.3729 },
        '神奈川県|相模原市南区':   { lat: 35.5337, lon: 139.3764 },
        // 神奈川県 その他市町村
        '神奈川県|横須賀市': { lat: 35.2806, lon: 139.6718 },
        '神奈川県|平塚市':   { lat: 35.3282, lon: 139.3497 },
        '神奈川県|鎌倉市':   { lat: 35.3192, lon: 139.5469 },
        '神奈川県|藤沢市':   { lat: 35.3374, lon: 139.4912 },
        '神奈川県|小田原市': { lat: 35.2654, lon: 139.1559 },
        '神奈川県|茅ヶ崎市': { lat: 35.3316, lon: 139.4086 },
        '神奈川県|逗子市':   { lat: 35.2952, lon: 139.5799 },
        '神奈川県|三浦市':   { lat: 35.1393, lon: 139.6165 },
        '神奈川県|厚木市':   { lat: 35.4415, lon: 139.3373 },
        '神奈川県|大和市':   { lat: 35.4740, lon: 139.4617 },
        '神奈川県|伊勢原市': { lat: 35.4007, lon: 139.3093 },
        '神奈川県|海老名市': { lat: 35.4474, lon: 139.3920 },
        '神奈川県|座間市':   { lat: 35.4879, lon: 139.4073 },
        '神奈川県|綾瀬市':   { lat: 35.4325, lon: 139.4338 },
        '神奈川県|南足柄市': { lat: 35.3233, lon: 139.0942 },
        '神奈川県|葉山町':   { lat: 35.2718, lon: 139.5804 },
        '神奈川県|寒川町':   { lat: 35.3834, lon: 139.3742 },
        '神奈川県|大磯町':   { lat: 35.3042, lon: 139.3115 },
        '神奈川県|二宮町':   { lat: 35.3013, lon: 139.2572 },
        '神奈川県|中井町':   { lat: 35.3600, lon: 139.2226 },
        '神奈川県|大井町':   { lat: 35.3286, lon: 139.1733 },
        '神奈川県|松田町':   { lat: 35.3417, lon: 139.1347 },
        '神奈川県|山北町':   { lat: 35.3722, lon: 139.0730 },
        '神奈川県|開成町':   { lat: 35.3250, lon: 139.1265 },
        '神奈川県|箱根町':   { lat: 35.2328, lon: 139.1065 },
        '神奈川県|真鶴町':   { lat: 35.1575, lon: 139.1353 },
        '神奈川県|湯河原町': { lat: 35.1454, lon: 139.1116 },
        '神奈川県|愛川町':   { lat: 35.5306, lon: 139.3219 },
        '神奈川県|清川村':   { lat: 35.5306, lon: 139.2697 },
    };

    // ── P2P addr → 市区町村単位に正規化 ──────────────────────────────────────
    // P2P の addr は "東京練馬区豊玉北" "横浜鶴見区末広町" など観測所レベル。
    // 座標辞書は市区町村レベルなので、区・市の部分だけ抽出する。
    function _parseAddrToUnit(pref, rawAddr) {
        const a = rawAddr.replace(/\s+/g, '');
        if (pref === '東京都') {
            // 23区: "東京{区名}{地区}" → "{区名}"
            const m23 = a.match(/^東京(.+?[区])/);
            if (m23) return m23[1];
            // 市: "八王子市..." → "八王子市"
            const mCity = a.match(/^(.+?市)/);
            if (mCity) return mCity[1];
            // 島嶼など
            const mOther = a.match(/^(.+?[町村])/);
            if (mOther) return mOther[1];
        }
        if (pref === '神奈川県') {
            // 政令市区: "横浜{区名}..." "川崎{区名}..." "相模原{区名}..."
            const bigCities = [['横浜', 3], ['相模原', 4], ['川崎', 3]];
            for (const [city, len] of bigCities) {
                if (a.startsWith(city)) {
                    const rest = a.slice(len);
                    const mWard = rest.match(/^(.+?[区])/);
                    if (mWard) return `${city}市${mWard[1]}`;
                }
            }
            // 一般市
            const mCity = a.match(/^(.+?市)/);
            if (mCity) return mCity[1];
            // 町村
            const mOther = a.match(/^(.+?[町村])/);
            if (mOther) return mOther[1];
        }
        // その他都道府県: 市区町村を抽出
        const m = a.match(/^(.+?[市区町村])/);
        return m ? m[1] : a;
    }

    function _dictLookup(key) {
        if (_COORD_DICT[key]) return _COORD_DICT[key];
        const alt1 = key.replace(/ヶ/g, 'ケ');
        if (_COORD_DICT[alt1]) return _COORD_DICT[alt1];
        const alt2 = key.replace(/ケ/g, 'ヶ');
        return _COORD_DICT[alt2] ?? null;
    }

    window.resolveIntensityPointLocation = function (pref, addr) {
        const { pref: p, addr: a } = normalizeEarthquakePointName(pref, addr);
        // 直接引き（辞書キーは既に unit レベル）
        const r1 = _dictLookup(`${p}|${a}`);
        if (r1) return r1;
        // P2P rawアドレスが渡された場合の保険（unit 抽出後に再引き）
        const unit = _parseAddrToUnit(p, a);
        if (unit !== a) return _dictLookup(`${p}|${unit}`);
        return null;
    };

    // ── P2P points 抽出・変換（市区町村単位に集約） ────────────────────────────
    // isArea:false を優先。複数観測所が同一市区町村の場合は最大 scale を採用。
    window.extractIntensityPoints = function (event) {
        if (!event) return null;
        const raw = Array.isArray(event.points) ? event.points : null;
        if (!raw || raw.length === 0) return null;

        const stationPts = raw.filter(p => p.isArea === false);
        const src = stationPts.length > 0 ? stationPts : raw.filter(p => p.isArea === true);
        if (src.length === 0) return null;

        // (pref, unit) でグループ化し最大 scale を保持
        const groups = new Map();
        for (const p of src) {
            const scale = Number(p.scale);
            const intensity = formatJmaIntensity(scale);
            if (intensity == null) continue;
            const pref    = String(p.pref || '').trim();
            const rawAddr = String(p.addr || '').trim();
            const unit    = _parseAddrToUnit(pref, rawAddr);
            const key     = `${pref}|${unit}`;
            const existing = groups.get(key);
            if (!existing || scale > existing.scale) {
                groups.set(key, { pref, addr: unit, scale, intensity, isArea: p.isArea === true });
            }
        }

        if (groups.size === 0) return null;

        const converted = Array.from(groups.values());
        // 震度降順 → 都道府県昇順 → 地点名昇順
        converted.sort((a, b) => {
            if (b.scale !== a.scale) return b.scale - a.scale;
            const cp = a.pref.localeCompare(b.pref, 'ja');
            if (cp !== 0) return cp;
            return a.addr.localeCompare(b.addr, 'ja');
        });

        return converted;
    };

    // ── 震度別マーカースタイル ────────────────────────────────────────────────
    const _INTENSITY_STYLE = {
        '1':   { bg: '#b3d4f5', fg: '#111' },
        '2':   { bg: '#3c9be8', fg: '#fff' },
        '3':   { bg: '#39c468', fg: '#111' },
        '4':   { bg: '#f9c74f', fg: '#111' },
        '5弱': { bg: '#f8961e', fg: '#fff' },
        '5強': { bg: '#f3722c', fg: '#fff' },
        '6弱': { bg: '#e53935', fg: '#fff' },
        '6強': { bg: '#b71c1c', fg: '#fff' },
        '7':   { bg: '#4a148c', fg: '#fff' },
    };

    const _INTENSITY_LABEL = {
        '5弱': '5-', '5強': '5+', '6弱': '6-', '6強': '6+',
    };

    function _escapeHtml(v) {
        return String(v ?? '').replace(/[&<>"']/g, ch =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
    }

    // ── マーカーレイヤー状態 ──────────────────────────────────────────────────
    let _markers      = [];
    let _currentId    = null;
    let _lastStatus   = { total: 0, mapped: 0, unmapped: 0 };

    window.clearEarthquakeIntensityMarkers = function () {
        _markers.forEach(m => { try { map.removeLayer(m); } catch (_e) {} });
        _markers = [];
        _currentId  = null;
        _lastStatus = { total: 0, mapped: 0, unmapped: 0 };
    };

    window.renderEarthquakeIntensityMarkers = function (event) {
        if (!event) return { total: 0, mapped: 0, unmapped: 0 };

        const newId = String(event.event_id || '');
        // 同一イベントの再呼出しはマップ操作せずステータスだけ返す
        if (newId && newId === _currentId) return { ..._lastStatus };

        clearEarthquakeIntensityMarkers();

        const points = extractIntensityPoints(event);
        if (!points || points.length === 0) {
            _currentId = newId;
            return { total: 0, mapped: 0, unmapped: 0 };
        }

        _currentId = newId;

        let mapped = 0, unmapped = 0;
        const bounds = [];

        // 震源もboundsに含める
        const eLat = Number(event.lat);
        const eLng = Number(event.lng ?? event.lon);
        if (Number.isFinite(eLat) && Number.isFinite(eLng)) bounds.push([eLat, eLng]);

        const time = event.occurred_at
            ? new Date(event.occurred_at).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
            : '—';

        points.forEach(pt => {
            const loc = resolveIntensityPointLocation(pt.pref, pt.addr);
            if (!loc) {
                unmapped++;
                console.warn('[EQ intensity] 座標未登録:', pt.pref, pt.addr);
                return;
            }

            const style = _INTENSITY_STYLE[pt.intensity] || { bg: '#9e9e9e', fg: '#fff' };
            const label = _INTENSITY_LABEL[pt.intensity] || String(pt.intensity);
            const size  = 28;
            const fs    = label.length > 1 ? 10 : 13;

            const icon = L.divIcon({
                className: '',
                html: `<div class="earthquake-intensity-marker" style="width:${size}px;height:${size}px;background:${style.bg};color:${style.fg};font-size:${fs}px;">${_escapeHtml(label)}</div>`,
                iconSize:   [size, size],
                iconAnchor: [size / 2, size / 2],
            });

            const popup = `<div style="font-size:12px;line-height:1.7;min-width:140px;">
                <strong>${_escapeHtml(pt.pref)} ${_escapeHtml(pt.addr)}</strong><br>
                震度: <strong>${_escapeHtml(pt.intensity)}</strong><br>
                発表時刻: ${_escapeHtml(time)}
                ${event.epicenter_name ? `<br>震源: ${_escapeHtml(event.epicenter_name)}` : ''}
                ${event.magnitude != null ? `<br>M${Number(event.magnitude).toFixed(1)}` : ''}
                ${event.depth_km   != null ? ` / 深さ${_escapeHtml(String(event.depth_km))}km` : ''}
            </div>`;

            const marker = L.marker([loc.lat, loc.lon], { icon, zIndexOffset: 100 }).addTo(map);
            marker.bindPopup(popup);
            _markers.push(marker);
            bounds.push([loc.lat, loc.lon]);
            mapped++;
        });

        // fitBounds（ナビ中・追従中は地図を動かさない）
        if (bounds.length >= 1) {
            const navigating = typeof navigationMode !== 'undefined' &&
                (navigationMode === 'navigation_active' || navigationMode === 'navigation_warning');
            if (!navigating) {
                try {
                    if (bounds.length === 1) {
                        map.setView(bounds[0], Math.max(map.getZoom(), 9), { animate: true });
                    } else {
                        map.fitBounds(L.latLngBounds(bounds), { padding: [40, 40], maxZoom: 11, animate: true });
                    }
                } catch (_e) {}
            }
        }

        _lastStatus = { total: points.length, mapped, unmapped };
        return { ..._lastStatus };
    };

})();
