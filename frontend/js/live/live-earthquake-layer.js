'use strict';
// live-earthquake-layer.js — /live 専用 市区町村震度マーカー
// earthquake-intensity-layer.js の市区町村解決ロジックを liveMap 向けに移植。
// navigation.js / state.js に一切依存しない。

(function () {

    // ── 定数（earthquake-intensity-layer.js と同一） ─────────────────────────

    const _SCALE_MAP = {
        10: '1', 20: '2', 30: '3', 40: '4',
        45: '5弱', 50: '5強', 55: '6弱', 60: '6強', 70: '7',
    };

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

    const _SEIREISHI = [
        ['大阪堺市', '堺市',       4],
        ['さいたま', 'さいたま市', 4],
        ['相模原',   '相模原市',   3],
        ['名古屋',   '名古屋市',   3],
        ['北九州',   '北九州市',   3],
        ['札幌',     '札幌市',     2],
        ['仙台',     '仙台市',     2],
        ['千葉',     '千葉市',     2],
        ['横浜',     '横浜市',     2],
        ['川崎',     '川崎市',     2],
        ['新潟',     '新潟市',     2],
        ['静岡',     '静岡市',     2],
        ['浜松',     '浜松市',     2],
        ['大阪',     '大阪市',     2],
        ['京都',     '京都市',     2],
        ['神戸',     '神戸市',     2],
        ['岡山',     '岡山市',     2],
        ['広島',     '広島市',     2],
        ['福岡',     '福岡市',     2],
        ['熊本',     '熊本市',     2],
    ];

    const _PREF_PREFIXES = ['大阪', '静岡', '岡山'];

    // ── 座標辞書（メインアプリと同一ファイルを参照） ─────────────────────────

    let _coordDict = null;

    fetch('/data/municipality_coords.json')
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then(d => { _coordDict = d; })
        .catch(e => { console.warn('[live-eq] 座標辞書ロード失敗:', e); _coordDict = {}; });

    // ── 住所解析（earthquake-intensity-layer.js の _parseAddrToUnit と同一） ─

    function _parseAddrToUnit(pref, rawAddr) {
        const a = rawAddr.replace(/\s+/g, '');
        if (pref === '東京都') {
            const m23 = a.match(/^東京(.+?[区])/);
            if (m23) return m23[1];
            const mCity = a.match(/^(.+?市)/);
            if (mCity) return mCity[1];
            const mOther = a.match(/^(.+?[町村])/);
            if (mOther) return mOther[1];
            return a;
        }
        for (const [prefix, fullCity, skipLen] of _SEIREISHI) {
            if (!a.startsWith(prefix)) continue;
            const rest = a.slice(skipLen);
            const mWard = rest.match(/^(.+?[区])/);
            if (mWard) return `${fullCity}${mWard[1]}`;
            break;
        }
        for (const pp of _PREF_PREFIXES) {
            if (!a.startsWith(pp)) continue;
            const rest = a.slice(pp.length);
            const m = rest.match(/^(.+?[市区町村])/);
            if (m) return m[1];
            break;
        }
        const m = a.match(/^(.+?[市区町村])/);
        return m ? m[1] : a;
    }

    function _norm(s) {
        return String(s || '').trim()
            .replace(/\s+/g, '')
            .replace(/[０-９]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0));
    }

    function _dictLookup(key) {
        if (!_coordDict) return null;
        if (_coordDict[key]) return _coordDict[key];
        const alt1 = key.replace(/ヶ/g, 'ケ');
        if (_coordDict[alt1]) return _coordDict[alt1];
        return _coordDict[key.replace(/ケ/g, 'ヶ')] ?? null;
    }

    function _resolveLocation(pref, addr) {
        const p = _norm(pref);
        const a = _norm(addr);
        const r1 = _dictLookup(`${p}|${a}`);
        if (r1) return r1;
        const unit = _parseAddrToUnit(p, a);
        if (unit !== a) return _dictLookup(`${p}|${unit}`);
        return null;
    }

    // ── points 抽出・市区町村単位に集約（同 extractIntensityPoints） ─────────

    function _extractPoints(event) {
        const raw = Array.isArray(event.points) ? event.points : null;
        if (!raw || raw.length === 0) return null;

        const stationPts = raw.filter(p => p.isArea === false);
        const src = stationPts.length > 0 ? stationPts : raw.filter(p => p.isArea === true);
        if (src.length === 0) return null;

        const groups = new Map();
        for (const p of src) {
            const scale = Number(p.scale);
            const intensity = _SCALE_MAP[scale] ?? null;
            if (intensity == null) continue;
            const pref    = _norm(p.pref);
            const rawAddr = _norm(p.addr);
            const unit    = _parseAddrToUnit(pref, rawAddr);
            const key     = `${pref}|${unit}`;
            const existing = groups.get(key);
            if (!existing || scale > existing.scale) {
                groups.set(key, { pref, addr: unit, scale, intensity });
            }
        }

        if (groups.size === 0) return null;

        return Array.from(groups.values()).sort((a, b) => {
            if (b.scale !== a.scale) return b.scale - a.scale;
            const cp = a.pref.localeCompare(b.pref, 'ja');
            return cp !== 0 ? cp : a.addr.localeCompare(b.addr, 'ja');
        });
    }

    // ── HTML エスケープ ───────────────────────────────────────────────────────

    function _esc(v) {
        return String(v ?? '').replace(/[&<>"']/g, ch =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
    }

    // ── レイヤーグループ ──────────────────────────────────────────────────────

    const _muniGroup = L.layerGroup();
    let _onMap = false;

    function _addToMap() {
        if (!_onMap) { _muniGroup.addTo(liveMap); _onMap = true; }
    }

    function _removeFromMap() {
        if (_onMap) { liveMap.removeLayer(_muniGroup); _onMap = false; }
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    /**
     * 指定地震イベントの市区町村震度マーカーを描画する。
     * 座標辞書未ロード・points なし・座標未登録 の場合は false を返す（フォールバック）。
     */
    function render(event, enabled) {
        _muniGroup.clearLayers();
        _removeFromMap();

        if (!enabled || !event) return false;

        const eid = event.event_id || '';

        if (!_coordDict) {
            console.info(
                'live earthquake municipality markers unavailable, fallback to representative marker:',
                `event_id=${eid}`,
            );
            return false;
        }

        const points = _extractPoints(event);
        if (!points || points.length === 0) {
            console.info(
                'live earthquake municipality markers unavailable, fallback to representative marker:',
                `event_id=${eid}`,
            );
            return false;
        }

        const time = event.occurred_at
            ? new Date(event.occurred_at).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
            : '—';

        let count = 0;
        points.forEach(pt => {
            const loc = _resolveLocation(pt.pref, pt.addr);
            if (!loc) return;

            const style = _INTENSITY_STYLE[pt.intensity] || { bg: '#9e9e9e', fg: '#fff' };
            const label = _INTENSITY_LABEL[pt.intensity] || String(pt.intensity);
            const size  = 28;
            const fs    = label.length > 1 ? 10 : 13;

            const icon = L.divIcon({
                className: '',
                html: `<div class="earthquake-intensity-marker" style="width:${size}px;height:${size}px;background:${style.bg};color:${style.fg};font-size:${fs}px;">${_esc(label)}</div>`,
                iconSize:   [size, size],
                iconAnchor: [size / 2, size / 2],
            });

            const popup = `<div style="font-size:12px;line-height:1.7;min-width:140px;">
                <strong>${_esc(pt.pref)} ${_esc(pt.addr)}</strong><br>
                震度: <strong>${_esc(pt.intensity)}</strong><br>
                発表時刻: ${_esc(time)}
                ${event.epicenter_name ? `<br>震源: ${_esc(event.epicenter_name)}` : ''}
                ${event.magnitude != null ? `<br>M${Number(event.magnitude).toFixed(1)}` : ''}
                ${event.depth_km != null ? ` / 深さ${_esc(String(event.depth_km))}km` : ''}
            </div>`;

            L.marker([loc.lat, loc.lon], { icon, zIndexOffset: 150 })
                .bindPopup(popup)
                .addTo(_muniGroup);
            count++;
        });

        if (count === 0) {
            console.info(
                'live earthquake municipality markers unavailable, fallback to representative marker:',
                `event_id=${eid}`,
            );
            return false;
        }

        _addToMap();
        console.info(`live earthquake municipality markers: event_id=${eid} count=${count}`);
        return true;
    }

    function clear() {
        _muniGroup.clearLayers();
        _removeFromMap();
    }

    window.liveEarthquakeLayer = { render, clear };

})();
