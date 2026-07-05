// /live/stream — earthquake adapter
// /api/live/earthquakes/history レスポンス → stream 地震 ViewModel 変換。
// 純粋変換のみ。副作用・DOM アクセスなし。

const EarthquakeStreamAdapter = (function () {

  // Stream Phase 5-B.1: streamer container 等 OS timezone が UTC の環境でも表示が JST になるよう、
  // ローカルタイムゾーン依存の getHours()/getMinutes() ではなく UTC+9 オフセット経由で計算する
  // (live-stream-tide-adapter.js / live-stream-railway-adapter.js と同じ方式)。
  const _JST_OFFSET_MS = 9 * 60 * 60 * 1000;

  const _RANK = {
    '1': 10, '2': 20, '3': 30, '4': 40,
    '5弱': 45, '5強': 50, '6弱': 55, '6強': 60, '7': 70,
  };

  const _COLOR = {
    '7': 'var(--c-eq)', '6強': 'var(--c-eq)', '6弱': 'var(--c-eq)',
    '5強': 'var(--c-eq)', '5弱': 'var(--c-eq)',
    '4': 'var(--c-eq-2)', '3': 'var(--c-eq-2)', '2': 'var(--c-eq-2)',
    '1': 'var(--c-eq-3)',
  };

  // SVG viewBox 0 0 1000 1300 への簡易投影
  // 基準点: 東京 (35.7N, 139.7E) → SVG (582, 500)
  // 縮尺: 1° lon ≈ 25px, 1° lat ≈ -35px
  function _latLonToSvg(lat, lon) {
    if (lat == null || lon == null) return null;
    const x = Math.round(582 + (lon - 139.7) * 25);
    const y = Math.round(500 + (lat - 35.7) * (-35));
    return [
      Math.max(100, Math.min(900, x)),
      Math.max(100, Math.min(1200, y)),
    ];
  }

  function _fmtHM(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return '—';
      const jst = new Date(d.getTime() + _JST_OFFSET_MS);
      return String(jst.getUTCHours()).padStart(2, '0') + ':' + String(jst.getUTCMinutes()).padStart(2, '0');
    } catch (_) { return '—'; }
  }

  function _fmtMag(mag) {
    const n = Number(mag);
    return (mag != null && !isNaN(n)) ? `M${n.toFixed(1)}` : 'M-';
  }

  function _pulseR(mag) {
    const n = Number(mag);
    if (isNaN(n)) return 12;
    if (n >= 7.0) return 22;
    if (n >= 6.0) return 18;
    if (n >= 5.0) return 15;
    return 12;
  }

  function _rank(intensity) {
    return _RANK[String(intensity || '')] || 0;
  }

  function _filter12h(items, nowMs) {
    const cutoff = nowMs - 12 * 60 * 60 * 1000;
    return items.filter(item => {
      const at = item.occurred_at || item.origin_time;
      if (!at) return false;
      try { return new Date(at).getTime() >= cutoff; }
      catch (_) { return false; }
    });
  }

  // 最大震度 → M → 発生時刻の優先順で子画面表示候補を並べる。
  function _sortByPriority(items) {
    return [...items].sort((a, b) => {
      const ri = _rank(b.max_intensity) - _rank(a.max_intensity);
      if (ri !== 0) return ri;
      const rm = (Number(b.magnitude) || 0) - (Number(a.magnitude) || 0);
      if (rm !== 0) return rm;
      return (b.occurred_at || '') > (a.occurred_at || '') ? 1 : -1;
    });
  }

  // 最大震度 → M → 発生時刻の優先順で注目地震を選択
  function _selectActive(items) {
    if (!items.length) return null;
    return _sortByPriority(items)[0];
  }

  function _toTarget(item) {
    const lat = item.lat;
    const lon = item.lng != null ? item.lng : item.lon;
    const svgAt = _latLonToSvg(lat, lon) || [500, 500];
    const s = String(item.max_intensity || '不明');
    const name = item.epicenter_name || item.hypocenter_name || '震源不明';
    return {
      id: item.event_id || null,
      p: name,
      m: _fmtMag(item.magnitude),
      s,
      t: _fmtHM(item.occurred_at || item.origin_time),
      at: svgAt,
      lat: lat != null ? lat : null,
      lon: lon != null ? lon : null,
      occurredAt: item.occurred_at || item.origin_time || null,
      r: _pulseR(item.magnitude),
      depth: item.depth_km != null ? `${item.depth_km}km` : null,
      tsunami: item.tsunami_info || null,
      // Stream Phase 5-A.1: 市区町村震度一覧 (LiveStreamEarthquakeDetail が正規化する)
      points: Array.isArray(item.points) ? item.points : [],
    };
  }

  function _toHistoryRow(item) {
    const s = String(item.max_intensity || '不明');
    return {
      t: _fmtHM(item.occurred_at || item.origin_time),
      p: item.epicenter_name || item.hypocenter_name || '震源不明',
      m: _fmtMag(item.magnitude),
      s,
      c: _COLOR[s] || 'var(--c-eq-3)',
    };
  }

  /**
   * /api/live/earthquakes/history レスポンスを stream ViewModel に変換する。
   *
   * @param {object} rawData  APIレスポンス ({items: [...]})
   * @param {number} nowMs    現在時刻ms — LiveStreamClock.getNow().getTime() を渡す
   * @returns {{ status, hasActiveEarthquake, targets, history, statusCount }}
   *
   * status: 'ok' | 'unavailable'
   */
  function build(rawData, nowMs) {
    if (!rawData || !Array.isArray(rawData.items)) {
      return { status: 'unavailable', hasActiveEarthquake: false, targets: [], history: [], statusCount: 0 };
    }

    const now = nowMs || Date.now();
    const items12h = _filter12h(rawData.items, now);
    const active = _selectActive(items12h);
    // Stream Phase 5-A bundle: 地震子画面は「対象 n/m 8s切替」と表示するため、
    // 注目1件だけではなく、12h内の地震候補を優先順で複数渡す。先頭は従来どおり active
    // (最大震度→M→時刻) なので既存の初期表示・テロップ優先度は維持される。
    const targets = active ? _sortByPriority(items12h).slice(0, 8).map(_toTarget) : [];
    const history = items12h.slice(0, 8).map(_toHistoryRow);
    // mapEvents: 中央マップ (Stream Phase 3-B) 用の候補イベント一覧。
    // targets は単一の注目震源のみを保持するため、複数地点を地図に描くための候補プールを別途公開する。
    // 表示件数の絞り込み (M5以上/震度3以上優先、最大5件) は呼び出し側 (StreamMapEvents) が行う。
    const mapEvents = items12h.slice(0, 12).map(_toTarget);

    return {
      status: 'ok',
      hasActiveEarthquake: targets.length > 0,
      targets,
      history,
      mapEvents,
      statusCount: items12h.length,
    };
  }

  return { build };
})();
