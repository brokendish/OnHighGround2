// /live/stream — rain/kikikuru adapter
// /api/live/summary レスポンス → stream 豪雨 ViewModel 変換。
// 純粋変換のみ。副作用・DOM アクセスなし。

const RainStreamAdapter = (function () {

  const _LEVEL_RANK = { danger: 3, warning: 2, watch: 1 };
  const _LEVEL_LABEL = { danger: '危険', warning: '警戒', watch: '注意' };
  const _LEVEL_COLOR = { danger: '#e879f9', warning: '#fb7185', watch: '#d4a017' };
  const _LEVEL_ALERT_COLOR = { danger: '#a21caf', warning: '#e11d48', watch: '#d4a017' };
  const _HAZARD_LABEL = { land: '土砂', inund: '浸水', flood_mesh: '洪水' };

  // SVG viewBox 0 0 1000 1300 への簡易投影 (earthquake adapter と共通スケール)
  // 基準点: 東京 (35.7N, 139.7E) → SVG (582, 500)
  function _latLonToSvg(lat, lon) {
    if (lat == null || lon == null) return [500, 600];
    const x = Math.round(582 + (lon - 139.7) * 25);
    const y = Math.round(500 + (lat - 35.7) * (-35));
    return [
      Math.max(100, Math.min(900, x)),
      Math.max(100, Math.min(1200, y)),
    ];
  }

  // activeTarget 周辺に簡略雨域セル (rain-map zoom 用)
  function _makeCells(x, y) {
    return [
      [x,      y,      44, 0.55],
      [x - 22, y + 18, 30, 0.45],
      [x + 18, y - 14, 24, 0.38],
    ];
  }

  function _fmtHM(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return '';
      return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    } catch (_) { return ''; }
  }

  function _catLabel(area) {
    const h = area.hazard || '';
    if (_HAZARD_LABEL[h]) return _HAZARD_LABEL[h];
    return area.type === 'rain' ? '豪雨' : 'キキクル';
  }

  function _toTarget(area) {
    const lat = area.lat;
    const lon = area.lng != null ? area.lng : area.lon;
    const [x, y] = _latLonToSvg(lat, lon);
    const level = area.level || 'warning';
    return {
      r:        area.area_name || area.label || '不明',
      lv:       _LEVEL_LABEL[level] || level,
      lvColor:  _LEVEL_COLOR[level] || '#fb7185',
      amt:      '',
      at:       [x, y],
      cells:    _makeCells(x, y),
      category: _catLabel(area),
    };
  }

  function _toAlert(area) {
    const level = area.level || 'warning';
    return {
      r:   area.area_name || area.label || '不明',
      lv:  _LEVEL_LABEL[level] || level,
      cl:  _LEVEL_ALERT_COLOR[level] || '#e11d48',
      cat: _catLabel(area),
      at:  _fmtHM(area.observed_at),
    };
  }

  /**
   * /api/live/summary レスポンスを stream 豪雨 ViewModel に変換する。
   *
   * @param {object} rawSummary  APIレスポンス (null → unavailable)
   * @returns {{ status, hasActiveRain, targets, alerts, statusCount }}
   *
   * status: 'ok' | 'error' | 'unavailable'
   *   ok        → 取得成功 (target 0件 = 対象なし)
   *   error     → rain/kikikuru 両方 offline
   *   unavailable → 引数が null/不正
   */
  function build(rawSummary) {
    if (!rawSummary || typeof rawSummary !== 'object') {
      return { status: 'unavailable', hasActiveRain: false, targets: [], alerts: [], statusCount: 0 };
    }

    const rainSection = rawSummary.rain    || {};
    const kikiSection = rawSummary.kikikuru || {};

    // 両方とも offline → error (取得不可として扱う)
    if (rainSection.status === 'offline' && kikiSection.status === 'offline') {
      return { status: 'error', hasActiveRain: false, targets: [], alerts: [], statusCount: 0 };
    }

    const rainAreas = Array.isArray(rainSection.areas) ? rainSection.areas : [];
    const kikiAreas = Array.isArray(kikiSection.areas) ? kikiSection.areas : [];
    const allAreas  = [...kikiAreas, ...rainAreas];

    const _byLevel = (a, b) => (_LEVEL_RANK[b.level] || 0) - (_LEVEL_RANK[a.level] || 0);

    // warning/danger のみ targets に含める (watch は左パネル alerts のみ)
    // 同一地域名の重複は level 優先で 1件に絞る (APIが hazard 種別ごとに重複する場合に対応)
    const _seenTarget = new Set();
    const targetAreas = allAreas
      .filter(a => a.level === 'danger' || a.level === 'warning')
      .sort(_byLevel)
      .filter(a => {
        const key = a.area_name || a.label || '';
        if (_seenTarget.has(key)) return false;
        _seenTarget.add(key);
        return true;
      })
      .slice(0, 5);

    const _seenAlert = new Set();
    const alertAreas = allAreas
      .slice()
      .sort(_byLevel)
      .filter(a => {
        const key = a.area_name || a.label || '';
        if (_seenAlert.has(key)) return false;
        _seenAlert.add(key);
        return true;
      })
      .slice(0, 8);

    return {
      status:       'ok',
      hasActiveRain: targetAreas.length > 0,
      targets:      targetAreas.map(_toTarget),
      alerts:       alertAreas.map(_toAlert),
      statusCount:  targetAreas.length,
    };
  }

  return { build };
})();
