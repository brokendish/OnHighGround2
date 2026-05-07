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

    // ── 全国市区町村座標辞書（非同期ロード） ──────────────────────────────────
    // キー: "都道府県名|市区町村名"  値: { lat, lon }
    let _COORD_DICT = null;  // null = ロード中

    fetch('/data/municipality_coords.json')
        .then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        })
        .then(data => {
            _COORD_DICT = data;
            console.info('[EQ intensity] 座標辞書 ロード完了:', Object.keys(data).length, '件');
        })
        .catch(e => {
            console.warn('[EQ intensity] 座標辞書 ロード失敗:', e);
            _COORD_DICT = {};
        });

    // ── P2P addr → 市区町村単位に正規化 ──────────────────────────────────────
    // P2P の addr は観測所レベル。座標辞書は市区町村レベルなので区・市を抽出する。
    //
    // 政令市パターン: "{市名short}{区名}{地区}" → "{完全市名}{区名}"
    // 例: "横浜鶴見区末広町" → "横浜市鶴見区"
    //
    // 府県prefix パターン: 大阪府・静岡県・岡山県は非政令市でも "大阪"|"静岡"|"岡山" prefix
    // 例: "大阪和泉市府中町" → "和泉市"、"静岡菊川市赤土" → "菊川市"

    // [prefix, 完全市名, skipLen] — 長い prefix を先に置いて競合を防ぐ
    const _SEIREISHI = [
        ['大阪堺市', '堺市',     4],  // 大阪府 堺市: "大阪堺市中区..." → 堺市中区
        ['さいたま', 'さいたま市', 4],
        ['相模原',   '相模原市',  3],
        ['名古屋',   '名古屋市',  3],
        ['北九州',   '北九州市',  3],
        ['札幌',     '札幌市',    2],
        ['仙台',     '仙台市',    2],
        ['千葉',     '千葉市',    2],
        ['横浜',     '横浜市',    2],
        ['川崎',     '川崎市',    2],
        ['新潟',     '新潟市',    2],
        ['静岡',     '静岡市',    2],  // 静岡県 静岡市 ward
        ['浜松',     '浜松市',    2],
        ['大阪',     '大阪市',    2],  // 大阪府 大阪市 ward
        ['京都',     '京都市',    2],
        ['神戸',     '神戸市',    2],
        ['岡山',     '岡山市',    2],  // 岡山県 岡山市 ward
        ['広島',     '広島市',    2],
        ['福岡',     '福岡市',    2],
        ['熊本',     '熊本市',    2],
    ];

    // これらの都道府県では、非政令市 addr にも府県省略名 prefix が付く
    const _PREF_PREFIXES = ['大阪', '静岡', '岡山'];

    function _parseAddrToUnit(pref, rawAddr) {
        const a = rawAddr.replace(/\s+/g, '');

        // 東京都: 23区は "市" なし、多摩・島嶼は通常の市区町村
        if (pref === '東京都') {
            const m23 = a.match(/^東京(.+?[区])/);
            if (m23) return m23[1];
            const mCity = a.match(/^(.+?市)/);
            if (mCity) return mCity[1];
            const mOther = a.match(/^(.+?[町村])/);
            if (mOther) return mOther[1];
            return a;
        }

        // 政令市ワードを前方マッチで検索
        for (const [prefix, fullCity, skipLen] of _SEIREISHI) {
            if (!a.startsWith(prefix)) continue;
            const rest = a.slice(skipLen);
            const mWard = rest.match(/^(.+?[区])/);
            if (mWard) return `${fullCity}${mWard[1]}`;
            // prefix は一致したが区名がない → 政令市以外の住所 (府県 prefix パターン)
            break;
        }

        // 府県 prefix パターン: "大阪"/「静岡」/「岡山」を除去して市区町村を抽出
        for (const pp of _PREF_PREFIXES) {
            if (!a.startsWith(pp)) continue;
            const rest = a.slice(pp.length);
            const m = rest.match(/^(.+?[市区町村])/);
            if (m) return m[1];
            break;
        }

        // 一般: 市区町村名を抽出
        const m = a.match(/^(.+?[市区町村])/);
        return m ? m[1] : a;
    }

    function _dictLookup(key) {
        if (!_COORD_DICT) return null;
        if (_COORD_DICT[key]) return _COORD_DICT[key];
        const alt1 = key.replace(/ヶ/g, 'ケ');
        if (_COORD_DICT[alt1]) return _COORD_DICT[alt1];
        const alt2 = key.replace(/ケ/g, 'ヶ');
        return _COORD_DICT[alt2] ?? null;
    }

    window.resolveIntensityPointLocation = function (pref, addr) {
        const { pref: p, addr: a } = normalizeEarthquakePointName(pref, addr);
        const r1 = _dictLookup(`${p}|${a}`);
        if (r1) return r1;
        const unit = _parseAddrToUnit(p, a);
        if (unit !== a) return _dictLookup(`${p}|${unit}`);
        return null;
    };

    // ── P2P points 抽出・変換（市区町村単位に集約） ────────────────────────────
    window.extractIntensityPoints = function (event) {
        if (!event) return null;
        const raw = Array.isArray(event.points) ? event.points : null;
        if (!raw || raw.length === 0) return null;

        const stationPts = raw.filter(p => p.isArea === false);
        const src = stationPts.length > 0 ? stationPts : raw.filter(p => p.isArea === true);
        if (src.length === 0) return null;

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
