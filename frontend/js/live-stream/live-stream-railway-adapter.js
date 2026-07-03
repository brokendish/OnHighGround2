// /live/stream — railway adapter
// /api/live/trains/summary レスポンス → stream 鉄道 ViewModel 変換。
// 純粋変換のみ。副作用・DOM アクセスなし。

const RailwayStreamAdapter = (function () {

  const _JST_OFFSET_MS = 9 * 60 * 60 * 1000;

  // stream ステータスチップ色 (live-stream-scene.js の demo 色に合わせる)
  const _ST_COLOR = {
    suspended:          'var(--c-eq)',
    partial_suspension: 'var(--c-eq-2)',
    delay:              '#d4a017',
    unknown:            '#5d6878',
  };

  // stream SVG 路線図への対応付け (RAIL_LINES_BASE のキー)
  const _LINE_MAP_ID = {
    '中央線快速': 'chuo',
    '中央線':     'chuo',
    '山手線':     'yamanote',
    '京浜東北線': 'keihin',
    '埼京線':     'saikyo',
  };

  // 路線バー色 (ODPT railway_id パターン)
  function _lineColor(item) {
    const mapId = _LINE_MAP_ID[item.railway_name || ''];
    if (mapId === 'chuo')     return '#f15a22';
    if (mapId === 'yamanote') return '#9acd32';
    if (mapId === 'keihin')   return '#00a7e0';
    if (mapId === 'saikyo')   return '#00ac9b';
    const id = item.railway_id || '';
    if (id.includes('Ginza'))        return '#f39700';
    if (id.includes('Marunouchi'))   return '#e60012';
    if (id.includes('Hibiya'))       return '#b5b5ac';
    if (id.includes('Tozai'))        return '#00a7d8';
    if (id.includes('Chiyoda'))      return '#00bb85';
    if (id.includes('Yurakucho'))    return '#c8a400';
    if (id.includes('Hanzomon'))     return '#8f76d6';
    if (id.includes('Namboku'))      return '#00ac9b';
    if (id.includes('Fukutoshin'))   return '#9c5e31';
    if (id.includes('TokyoMetro'))   return '#b5b5ac';
    if (id.includes('Toei.Asakusa')) return '#e85298';
    if (id.includes('Toei.Mita'))    return '#0079c2';
    if (id.includes('Toei.Shinjuku')) return '#6cbb5a';
    if (id.includes('Toei.Oedo'))    return '#b6007a';
    if (id.includes('JR-East'))      return '#f15a22';
    return '#7888a0';
  }

  function _fmtUpdated(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return '';
      const jst = new Date(d.getTime() + _JST_OFFSET_MS);
      return String(jst.getUTCHours()).padStart(2, '0') + ':' + String(jst.getUTCMinutes()).padStart(2, '0');
    } catch (_) { return ''; }
  }

  function _truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.slice(0, maxLen - 1) + '…' : str;
  }

  function _buildLine(item) {
    const mapId = _LINE_MAP_ID[item.railway_name || ''] || null;
    return {
      id:        item.railway_id || String(Math.random()),
      mapId,
      name:      item.railway_name || '路線名不明',
      operator:  item.operator_name || '',
      status:    item.status_label || item.status || '状態不明',
      note:      _truncate(item.description || '', 40),
      updatedAt: _fmtUpdated(item.updated_at),
      stColor:   _ST_COLOR[item.status] || '#5d6878',
      lineColor: _lineColor(item),
      severity:  Number(item.severity) || 0,
    };
  }

  /**
   * /api/live/trains/summary レスポンスを stream 鉄道 ViewModel に変換する。
   *
   * @param {object} raw  API レスポンス
   * @returns {{ status, affected, affectedCount }}
   *   status: 'ok' | 'unavailable' | 'error'
   */
  function build(raw) {
    if (!raw) return { status: 'unavailable', affected: [], affectedCount: 0 };

    // ODPT未設定や外部エラー → unavailable (デモ fallback なし: error として扱う)
    if (raw.status === 'unavailable') {
      return { status: 'error', affected: [], affectedCount: 0 };
    }

    const items = (raw.items || [])
      .filter(item => item && Number(item.severity) > 0)  // severity=0 = 平常 → 除外
      .sort((a, b) => (Number(b.severity) || 0) - (Number(a.severity) || 0))  // 重要度降順
      .slice(0, 6);  // 最大 6 件

    return {
      status:        'ok',
      affected:      items.map(_buildLine),
      affectedCount: items.length,
    };
  }

  return { build };
})();
