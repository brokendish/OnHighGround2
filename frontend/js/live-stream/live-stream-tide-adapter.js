// /live/stream — tide adapter
// /api/live/tide/stations + /api/live/tide/stations/{id} レスポンス群
// → stream 潮位 ViewModel 変換。純粋変換のみ。副作用・DOM アクセスなし。

const TideStreamAdapter = (function () {

  const _JST_OFFSET_MS = 9 * 60 * 60 * 1000;

  // SVG viewBox 0 0 1000 1300 への簡易投影 (他 adapter と共通スケール)
  function _latLonToSvg(lat, lon) {
    if (lat == null || lon == null) return [500, 800];
    const x = Math.round(582 + (lon - 139.7) * 25);
    const y = Math.round(500 + (lat - 35.7) * (-35));
    return [
      Math.max(100, Math.min(900, x)),
      Math.max(100, Math.min(1200, y)),
    ];
  }

  function _jstDateStr(d) {
    try {
      const t = typeof d === 'string' ? new Date(d) : d;
      if (isNaN(t.getTime())) return '';
      const jst = new Date(t.getTime() + _JST_OFFSET_MS);
      return jst.getUTCFullYear() + '-'
        + String(jst.getUTCMonth() + 1).padStart(2, '0') + '-'
        + String(jst.getUTCDate()).padStart(2, '0');
    } catch (_) { return ''; }
  }

  function _jstHour(isoStr) {
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return null;
      const jst = new Date(d.getTime() + _JST_OFFSET_MS);
      return jst.getUTCHours() + jst.getUTCMinutes() / 60;
    } catch (_) { return null; }
  }

  function _fmtHM(isoStr) {
    const h = _jstHour(isoStr);
    if (h == null) return '--:--';
    const hh = Math.floor(h) % 24;
    const mm = Math.round((h - Math.floor(h)) * 60) % 60;
    return String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
  }

  function _fmtCm(cm) {
    if (cm == null || !isFinite(Number(cm))) return '--';
    return String(Math.round(Number(cm)));
  }

  // todayStr から当日 JST 0:00 の UTC ms を返す
  function _todayMidnightMs(todayStr) {
    return new Date(todayStr + 'T00:00:00+09:00').getTime();
  }

  // h = 当日 JST 0:00 からの経過時間 (昨日=-24〜、翌日=24〜48)
  // 3日分 (前日〜翌日) を受け入れ、中央固定グラフで過去/未来を表示可能にする
  function _parseRecords(records, todayStr) {
    let midMs;
    try {
      midMs = _todayMidnightMs(todayStr);
      if (isNaN(midMs)) return [];
    } catch (_) { return []; }

    const result = [];
    for (const r of (records || [])) {
      if (!r.datetime || r.tide_cm == null) continue;
      try {
        const d = new Date(r.datetime);
        if (isNaN(d.getTime())) continue;
        const h = (d.getTime() - midMs) / 3600000; // 当日 0:00 JST 基準の経過時間
        if (h < -24 || h > 48) continue;
        const cm = Number(r.tide_cm);
        if (!isFinite(cm)) continue;
        result.push({ h, cm });
      } catch (_) {}
    }
    return result.sort((a, b) => a.h - b.h);
  }

  function _parseExtremePoints(extremes, todayStr) {
    let midMs;
    try {
      midMs = _todayMidnightMs(todayStr);
      if (isNaN(midMs)) return { highData: [], lowData: [] };
    } catch (_) { return { highData: [], lowData: [] }; }

    const highData = [], lowData = [];
    for (const e of ((extremes && extremes.high_tides) || [])) {
      if (!e.time) continue;
      try {
        const d = new Date(e.time);
        if (isNaN(d.getTime())) continue;
        const h = (d.getTime() - midMs) / 3600000;
        if (h < -24 || h > 48) continue;
        const cm = Number(e.tide_cm);
        if (!isFinite(cm)) continue;
        highData.push({ h, cm });
      } catch (_) {}
    }
    for (const e of ((extremes && extremes.low_tides) || [])) {
      if (!e.time) continue;
      try {
        const d = new Date(e.time);
        if (isNaN(d.getTime())) continue;
        const h = (d.getTime() - midMs) / 3600000;
        if (h < -24 || h > 48) continue;
        const cm = Number(e.tide_cm);
        if (!isFinite(cm)) continue;
        lowData.push({ h, cm });
      } catch (_) {}
    }
    return { highData, lowData };
  }

  function _buildStation(detail, todayStr) {
    const name = detail.name || detail.station_id || '不明';
    const at   = _latLonToSvg(detail.lat, detail.lon);

    const records            = _parseRecords(detail.records, todayStr);
    const { highData, lowData } = _parseExtremePoints(detail.extremes, todayStr);

    const nh = detail.next_high_tide;
    const nl = detail.next_low_tide;

    return {
      name,
      at,
      alert:    false,     // MVP: 高潮警報ロジック未実装
      source:   'jma',     // 実データ識別フラグ (panels.js でのブランチ用)
      records,             // [{h, cm}] — 今日の時間別データ
      highData,            // [{h, cm}] — 今日の満潮点
      lowData,             // [{h, cm}] — 今日の干潮点
      high: nh ? `${_fmtHM(nh.time)} ${_fmtCm(nh.tide_cm)}cm` : '--:-- --cm',
      low:  nl ? `${_fmtHM(nl.time)} ${_fmtCm(nl.tide_cm)}cm` : '--:-- --cm',
      dev:  null,          // MVP: 偏差データなし
    };
  }

  /**
   * /api/live/tide/stations/{id} レスポンス配列を stream 潮位 ViewModel に変換する。
   *
   * @param {object[]} stationDetails  観測点詳細レスポンスの配列
   * @returns {{ status, stations, alertCount }}
   *   status: 'ok' | 'unavailable'
   */
  function build(stationDetails) {
    if (!Array.isArray(stationDetails) || stationDetails.length === 0) {
      return { status: 'unavailable', stations: [], alertCount: 0 };
    }

    const todayStr = _jstDateStr(new Date());

    const stations = stationDetails
      .filter(d => d && d.station_id)
      .map(d => _buildStation(d, todayStr));

    return {
      status:     'ok',
      stations,
      alertCount: 0,   // MVP: 高潮警報ロジック未実装
    };
  }

  return { build };
})();
