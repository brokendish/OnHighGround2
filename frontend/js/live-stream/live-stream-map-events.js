'use strict';
// /live/stream — 中央メイン地図 本番データイベント正規化 (Stream Phase 3-B)
//
// 既存 /live 系 adapter (EarthquakeStreamAdapter 等) が変換済みの ViewModel から、
// Leaflet 中央地図に描画する共通イベント形式へさらに正規化する。
// fetch や DOM 操作は一切行わない (純粋変換のみ)。呼び出し側は main.js。
//
// 共通イベント形式:
//   { id, type, severity, lat, lng, title, subtitle, timeLabel, updatedAt, source, rank, stale }
//   type:     earthquake | rain | kikikuru | railway | tide
//   severity: critical | high | medium | low | info

const StreamMapEvents = (function () {

  // 日本周辺の簡易 bbox 判定 (厳密でなくてよい。明らかな異常座標のみ除外する)。
  // 地震は JMA 監視範囲に合わせて広め: 千島列島付近 (北海道より北, 〜50°N) や
  // 択捉沖・北西太平洋の沖合震源 (〜157°E) も含める。以前の [20,46]/[122,154] は
  // 実際の地震 (例: 北西太平洋 M6.0, lat48.0/lng154.9) を誤って除外していた。
  const JAPAN_LAT = [17, 50];
  const JAPAN_LNG = [120, 157];

  const CAP_BY_TYPE = { earthquake: 5, rain: 5, kikikuru: 5, railway: 5, tide: 3 };
  const TOTAL_CAP = 20;

  const STALE_MS = {
    earthquake: 24 * 60 * 60 * 1000,
    rain:        3 * 60 * 60 * 1000,
    kikikuru:    3 * 60 * 60 * 1000,
    railway:    24 * 60 * 60 * 1000,
    tide:        6 * 60 * 60 * 1000,
  };

  const SEVERITY_WEIGHT = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };

  // 鉄道: API の operator 代表点 (粗い) が取れない場合のみ使う既知路線の代表駅
  const RAIL_FALLBACK_POINT = {
    chuo:     { lat: 35.6896, lng: 139.7006 }, // 新宿
    yamanote: { lat: 35.6812, lng: 139.7671 }, // 東京
    keihin:   { lat: 35.9068, lng: 139.6238 }, // 大宮
    saikyo:   { lat: 35.7295, lng: 139.7109 }, // 池袋
  };
  // Stream Phase 5-B: backend の operator 代表点 (_operator_representative_latlng) が
  // 未登録の事業者・上記の旧SVG対応4路線にも該当しない路線が「座標が取れない」という理由だけで
  // event 自体から除外され、自動巡回の focus 対象にすらなれない (= 詳細全文表示もズームインも
  // 一切発火しない) ことがあった。座標が粗くても「focus 対象にはなれる」ことを優先し、
  // 最終手段として東京駅付近を汎用フォールバック地点として使う。
  const RAIL_GENERIC_FALLBACK_POINT = { lat: 35.6812, lng: 139.7671 }; // 東京駅

  function _validCoord(lat, lng) {
    return typeof lat === 'number' && isFinite(lat)
      && typeof lng === 'number' && isFinite(lng)
      && lat >= JAPAN_LAT[0] && lat <= JAPAN_LAT[1]
      && lng >= JAPAN_LNG[0] && lng <= JAPAN_LNG[1];
  }

  // 取得時刻不明の場合の既定挙動: type ごとに「stale扱いにするか」を決める。
  // 鉄道は「取得時刻不明でも表示してよいが stale class を付ける」仕様のため true。
  // それ以外は取得時刻不明なら安全側で stale とはしない (座標のみで判定材料が乏しいため除外しない)。
  function _staleInfo(type, updatedAt, nowMs) {
    if (!updatedAt) return { stale: type === 'railway', ageKnown: false };
    const t = new Date(updatedAt).getTime();
    if (isNaN(t)) return { stale: type === 'railway', ageKnown: false };
    const limit = STALE_MS[type];
    return { stale: limit != null && (nowMs - t) > limit, ageKnown: true };
  }

  function _eqSeverity(shindo, mag) {
    const s = String(shindo || '');
    const m = Number(mag) || 0;
    if (s.includes('7') || s.includes('6') || m >= 7) return 'critical';
    if (s.includes('5') || m >= 6) return 'high';
    if (s === '3' || s === '4' || m >= 5) return 'medium';
    return 'low';
  }

  function _rainSeverity(level) {
    if (level === 'danger') return 'critical';
    if (level === 'warning') return 'high';
    return 'medium';
  }

  function _railSeverity(statusCode) {
    if (statusCode === 'suspended') return 'critical';
    if (statusCode === 'partial_suspension') return 'high';
    if (statusCode === 'delay') return 'medium';
    return 'low';
  }

  function _fromEarthquake(eqModel, nowMs) {
    if (!eqModel || eqModel.status !== 'ok') return [];
    const src = Array.isArray(eqModel.mapEvents) ? eqModel.mapEvents : (eqModel.targets || []);
    return src
      .filter(t => _validCoord(t.lat, t.lon))
      .map(t => {
        const { stale } = _staleInfo('earthquake', t.occurredAt, nowMs);
        return {
          id:        t.id || `eq-${t.occurredAt || t.t}-${t.p}`,
          type:      'earthquake',
          severity:  _eqSeverity(t.s, t.m),
          lat:       t.lat,
          lng:       t.lon,
          title:     t.p,
          subtitle:  [t.m, t.s ? `震度${t.s}` : ''].filter(Boolean).join(' / '),
          timeLabel: t.t || '',
          updatedAt: t.occurredAt || null,
          source:    'jma',
          stale,
        };
      })
      .filter(e => !e.stale)
      // M/震度が高いものを優先しつつ新しい順
      .sort((a, b) => (SEVERITY_WEIGHT[b.severity] - SEVERITY_WEIGHT[a.severity])
        || String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')));
  }

  function _fromRain(rainModel, nowMs) {
    if (!rainModel || rainModel.status !== 'ok') return [];
    return (rainModel.targets || [])
      .filter(t => _validCoord(t.lat, t.lon))
      .map(t => {
        const type = t.rawType === 'rain' ? 'rain' : 'kikikuru';
        const { stale } = _staleInfo(type, t.observedAt, nowMs);
        return {
          id:        t.id || `${type}-${t.r}-${t.hazard || t.rawType || ''}`,
          type,
          severity:  _rainSeverity(t.level),
          lat:       t.lat,
          lng:       t.lon,
          title:     t.r,
          subtitle:  t.category ? `${t.category} ${t.lv}` : t.lv,
          timeLabel: '',
          updatedAt: t.observedAt || null,
          source:    'jma',
          stale,
        };
      })
      .filter(e => !e.stale)
      .sort((a, b) => SEVERITY_WEIGHT[b.severity] - SEVERITY_WEIGHT[a.severity]);
  }

  function _fromRailway(railModel, nowMs) {
    if (!railModel || railModel.status !== 'ok') return [];
    return (railModel.affected || [])
      .map(a => {
        // Stream Phase 5-B: 座標が取れない路線でも event 自体は作る (自動巡回の focus 対象から
        // 除外しない)。RAIL_GENERIC_FALLBACK_POINT はあくまで最終手段の粗い代表点であり、
        // 精度を主張するものではない。
        const pt = _validCoord(a.lat, a.lng) ? { lat: a.lat, lng: a.lng }
          : (a.mapId && RAIL_FALLBACK_POINT[a.mapId]) || RAIL_GENERIC_FALLBACK_POINT;
        // 鉄道: 取得時刻不明 or 24h超過は stale class を付けるが、表示自体は除外しない
        const { stale } = _staleInfo('railway', a.updatedAtRaw, nowMs);
        return {
          id:        a.id,
          type:      'railway',
          severity:  _railSeverity(a.statusCode),
          lat:       pt.lat,
          lng:       pt.lng,
          title:     a.name,
          subtitle:  a.status,
          timeLabel: a.updatedAt || '',
          updatedAt: a.updatedAtRaw || null,
          source:    'odpt',
          stale,
        };
      })
      // 鉄道は座標が無くても汎用フォールバック地点を持つため除外されない。
      // 取得時刻不明の場合も stale class のみ付与し、除外はしない。
      .sort((a, b) => SEVERITY_WEIGHT[b.severity] - SEVERITY_WEIGHT[a.severity]);
  }

  function _fromTide(tideModel, nowMs) {
    if (!tideModel || tideModel.status !== 'ok') return [];
    // MVP: 高潮警報とのジョインが未実装のため alert=true の観測点のみ (現状は常に0件)。
    // 参照: TideStreamAdapter._buildStation() コメント「高潮警報ロジック未実装」
    return (tideModel.stations || [])
      .filter(s => s.alert && _validCoord(s.lat, s.lon))
      .map(s => ({
        id:        `tide-${s.name}`,
        type:      'tide',
        severity:  'high',
        lat:       s.lat,
        lng:       s.lon,
        title:     s.name,
        subtitle:  '高潮に注意',
        timeLabel: '',
        updatedAt: null,
        source:    'jma',
        stale:     false,
      }));
  }

  function _dedupe(events) {
    const seen = new Set();
    return events.filter(e => {
      if (seen.has(e.id)) return false;
      seen.add(e.id);
      return true;
    });
  }

  function _capAndSort(events) {
    const counts = {};
    const kept = [];
    for (const e of events) {
      const n = counts[e.type] || 0;
      if (n >= (CAP_BY_TYPE[e.type] || 0)) continue;
      counts[e.type] = n + 1;
      kept.push(e);
    }
    kept.sort((a, b) => SEVERITY_WEIGHT[b.severity] - SEVERITY_WEIGHT[a.severity]);
    return kept.slice(0, TOTAL_CAP).map((e, i) => ({ ...e, rank: i + 1 }));
  }

  /**
   * 各 stream adapter の出力 (status/targets 等を含む ViewModel) から
   * 中央マップ描画用の正規化イベント配列を構築する。
   *
   * @param {object} models
   * @param {object|null} models.eqModel    EarthquakeStreamAdapter.build() の出力 (未取得/失敗時は null)
   * @param {object|null} models.rainModel  RainStreamAdapter.build() の出力
   * @param {object|null} models.railModel  RailwayStreamAdapter.build() の出力
   * @param {object|null} models.tideModel  TideStreamAdapter.build() の出力
   * @param {number}      models.nowMs      現在時刻ms — LiveStreamClock.getNow().getTime() を渡す
   * @returns {Array} 正規化イベント配列 (件数上限適用済み)
   */
  function build(models) {
    const m = models || {};
    const nowMs = m.nowMs || Date.now();
    let events = [
      ..._fromEarthquake(m.eqModel, nowMs),
      ..._fromRain(m.rainModel, nowMs),
      ..._fromRailway(m.railModel, nowMs),
      ..._fromTide(m.tideModel, nowMs),
    ];
    events = _dedupe(events);
    return _capAndSort(events);
  }

  return { build };
})();
