'use strict';
// /live/stream — 地震子画面 市区町村震度データ正規化 (Stream Phase 5-A.1)
//
// P2P (p2pquake) の points[] (pref/addr/isArea/scale) を、frontend/js/live/live-earthquake-layer.js
// の住所解析・座標辞書ロジックをそのまま移植して正規化する。/live 本体は一切変更しない。
// 本ファイルは純粋な正規化のみを担当し、DOM描画・タイマーは live-stream-panels.js 側が行う。

const LiveStreamEarthquakeDetail = (function () {

  // p2pquake の生 scale (int) → 震度表記。backend/app/services/earthquake_source_p2p.py の
  // _SCALE_MAP と同一対応表。
  const _SCALE_MAP = {
    10: '1', 20: '2', 30: '3', 40: '4',
    45: '5弱', 50: '5強', 55: '6弱', 60: '6強', 70: '7',
  };

  // 表示・並び替え用 rank (指示書の推奨テーブルをそのまま採用)
  const _RANK = {
    '7': 70, '6強': 65, '6弱': 60, '5強': 55, '5弱': 50,
    '4': 40, '3': 30, '2': 20, '1': 10, '不明': 0,
  };

  // 政令指定都市の区表記 (pref込みaddrの先頭がこの表記のとき、fullCity+区名 に正規化する)
  // frontend/js/live/live-earthquake-layer.js の _SEIREISHI と同一。
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

  // ── 座標辞書 (メインアプリ /live と同一ファイルを参照。取得のみ・変更なし) ──
  let _coordDict = null;
  let _dictStatus = 'loading'; // loading | ready | error
  let _dictWaiters = [];

  function _loadDict() {
    fetch('/data/municipality_coords.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => {
        _coordDict = d;
        _dictStatus = 'ready';
        _dictWaiters.forEach(fn => { try { fn(); } catch (_) {} });
        _dictWaiters = [];
      })
      .catch(e => {
        console.warn('[stream-eq-detail] 座標辞書ロード失敗:', e.message);
        _coordDict = {};
        _dictStatus = 'error';
        _dictWaiters.forEach(fn => { try { fn(); } catch (_) {} });
        _dictWaiters = [];
      });
  }
  _loadDict();

  function getDictStatus() { return _dictStatus; }

  // 辞書ロード完了 (成功/失敗いずれか) 後に一度だけ fn を呼ぶ。既に完了していれば同期的に呼ぶ。
  function onDictReady(fn) {
    if (_dictStatus === 'loading') _dictWaiters.push(fn);
    else fn();
  }

  function _dictLookup(key) {
    if (!_coordDict) return null;
    if (_coordDict[key]) return _coordDict[key];
    const alt1 = key.replace(/ヶ/g, 'ケ');
    if (_coordDict[alt1]) return _coordDict[alt1];
    return _coordDict[key.replace(/ケ/g, 'ヶ')] || null;
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

  // build() 結果の簡易キャッシュ。同一 event (id/points件数/辞書状態が同じ) の
  // 再描画 (render() は8秒毎/データ更新毎に呼ばれる) のたびに再計算しない。
  let _cacheKey = null;
  let _cacheVal = null;

  /**
   * 地震 target (EarthquakeStreamAdapter._toTarget() または demo scene の1件) から
   * 市区町村震度一覧を正規化する。
   *
   * @param {object|null} event  { id, points: [{pref,addr,isArea,scale}, ...] }
   * @returns {{eventId, municipalities: Array, municipalCount, markerCount, missingCoordinateCount}}
   *
   * event が null / id なし / points なし の場合は空結果 (詳細なし) を返す。
   * demo fallback はしない — 呼び出し側が渡した event の points をそのまま正規化するだけ。
   */
  function build(event) {
    const eventId = event && event.id ? event.id : null;
    const points = event && Array.isArray(event.points) ? event.points : [];
    if (!eventId || points.length === 0) {
      return { eventId, municipalities: [], municipalCount: 0, markerCount: 0, missingCoordinateCount: 0 };
    }

    const key = eventId + '|' + points.length + '|' + _dictStatus;
    if (_cacheKey === key) return _cacheVal;

    const stationPts = points.filter(p => p && p.isArea === false);
    const src = stationPts.length > 0 ? stationPts : points.filter(p => p && p.isArea !== false);

    const groups = new Map();
    for (const p of src) {
      const scale = Number(p.scale);
      const intensity = _SCALE_MAP[scale];
      if (!intensity) continue;
      const pref = _norm(p.pref);
      const rawAddr = _norm(p.addr);
      if (!pref || !rawAddr) continue;
      const unit = _parseAddrToUnit(pref, rawAddr);
      const gKey = `${pref}|${unit}`;
      const existing = groups.get(gKey);
      if (!existing || scale > existing.scale) {
        groups.set(gKey, { pref, city: unit, scale, intensity });
      }
    }

    let markerCount = 0, missingCoordinateCount = 0;
    const municipalities = Array.from(groups.values()).map(g => {
      const loc = _resolveLocation(g.pref, g.city);
      if (loc && isFinite(loc.lat) && isFinite(loc.lon)) markerCount++;
      else missingCoordinateCount++;
      return {
        id: `${eventId}-${g.pref}-${g.city}`,
        eventId,
        pref: g.pref,
        city: g.city,
        areaName: `${g.pref}${g.city}`,
        intensity: g.intensity,
        intensityRank: _RANK[g.intensity] || 0,
        lat: loc ? loc.lat : null,
        lng: loc ? loc.lon : null,
        source: 'p2pquake',
      };
    }).sort((a, b) => {
      if (b.intensityRank !== a.intensityRank) return b.intensityRank - a.intensityRank;
      const cp = a.pref.localeCompare(b.pref, 'ja');
      return cp !== 0 ? cp : a.city.localeCompare(b.city, 'ja');
    });

    const result = { eventId, municipalities, municipalCount: municipalities.length, markerCount, missingCoordinateCount };
    _cacheKey = key;
    _cacheVal = result;
    return result;
  }

  return { build, getDictStatus, onDictReady };
})();
