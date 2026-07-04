'use strict';
// /live/stream — 中央マップ・左右パネル・テロップ・全体ステータス・カテゴリバッジの共通イベントストア
// (Stream Phase 3-C で導入、Phase 3-D で getSummary().byType を追加)
//
// StreamMapEvents.build() が正規化した event 配列を唯一の入力として受け取り、
// 地図 / パネル / テロップ / 全体ステータス / 上部カテゴリバッジが同じデータを参照できるようにする。
// real / demo / calm いずれのモードでも同じ setEvents() 経路を通す (main.js 側で呼び分ける)。
// DOM操作・fetchは行わない。

const LiveStreamEventStore = (function () {

  const SEVERITY_WEIGHT = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
  const TYPE_PRIORITY = { earthquake: 5, kikikuru: 4, rain: 3, railway: 2, tide: 1, water: 0 };

  let _events = [];
  let _meta = { mode: null, dataState: 'empty', fetchStatus: {}, updatedAt: null };
  const _listeners = [];
  let _updateCount = 0; // Stream Phase 5-A diagnostics: setEvents() 呼び出し回数

  function _sorted(events) {
    return events.slice().sort((a, b) => {
      const sw = (SEVERITY_WEIGHT[b.severity] || 0) - (SEVERITY_WEIGHT[a.severity] || 0);
      if (sw !== 0) return sw;
      const rr = (a.rank || 0) - (b.rank || 0);
      if (rr !== 0) return rr;
      const au = a.updatedAt || '', bu = b.updatedAt || '';
      if (au !== bu) return bu.localeCompare(au);
      return (TYPE_PRIORITY[b.type] || 0) - (TYPE_PRIORITY[a.type] || 0);
    });
  }

  /**
   * イベント一覧を差し替え、購読者へ通知する。
   * @param {Array} events  正規化済みイベント配列 (StreamMapEvents.build() の出力を想定)
   * @param {object} [meta] { mode: 'real'|'demo'|'calm', dataState, fetchStatus, updatedAt }
   */
  function setEvents(events, meta) {
    _events = _sorted(Array.isArray(events) ? events : []);
    _meta = Object.assign({ mode: null, dataState: 'empty', fetchStatus: {}, updatedAt: null }, meta || {});
    _updateCount += 1;
    _listeners.forEach(fn => { try { fn(_events, _meta); } catch (e) { console.warn('[LiveStreamEventStore] listener error:', e.message); } });
  }

  function getEvents() {
    return _events.slice();
  }

  function getEventsByType(type) {
    return _events.filter(e => e.type === type);
  }

  function getHeadlineEvents(limit) {
    return _events.slice(0, limit != null ? limit : 5);
  }

  function _overallStatus() {
    if (_events.some(e => e.severity === 'critical')) return 'critical';
    if (_events.some(e => e.severity === 'high')) return 'alert';
    if (_events.some(e => e.severity === 'medium' || e.severity === 'low')) return 'watch';
    if (_meta.dataState === 'unavailable') return 'unavailable';
    return 'calm';
  }

  // event severity → カテゴリ別状態 (calm|watch|high|critical)。既存 calm/high 語彙を壊さないよう
  // UI 側 (badge/level) で最終的に既存 data-lv 等へマッピングする際の中間表現として使う。
  function _severityToTypeStatus(sev) {
    if (sev === 'critical') return 'critical';
    if (sev === 'high') return 'high';
    if (sev === 'medium' || sev === 'low') return 'watch';
    return 'calm';
  }

  const ALL_TYPES = ['earthquake', 'rain', 'kikikuru', 'railway', 'tide', 'water'];

  /**
   * カテゴリ別 (type別) の件数・最大severityから導出した状態を返す。
   * stale/不正座標/severity不足で除外された event は _events に入らないため、ここにも含まれない。
   */
  function getSummary() {
    const countsByType = {};
    const countsBySeverity = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    const maxSeverityRankByType = {};
    _events.forEach(e => {
      countsByType[e.type] = (countsByType[e.type] || 0) + 1;
      if (countsBySeverity[e.severity] != null) countsBySeverity[e.severity]++;
      const rank = SEVERITY_WEIGHT[e.severity] || 0;
      if (maxSeverityRankByType[e.type] == null || rank > maxSeverityRankByType[e.type].rank) {
        maxSeverityRankByType[e.type] = { rank, severity: e.severity };
      }
    });
    const byType = {};
    ALL_TYPES.forEach(t => {
      const top = maxSeverityRankByType[t];
      byType[t] = {
        count:  countsByType[t] || 0,
        status: top ? _severityToTypeStatus(top.severity) : 'calm',
      };
    });

    const dataState = _meta.dataState || 'empty';
    return {
      overallStatus:     _overallStatus(),
      total:             _events.length,
      activeTotal:       _events.length,
      hasError:          dataState === 'unavailable',
      hasPartialError:   dataState === 'partial',
      countsByType,
      countsBySeverity,
      byType,
      headlineEvents:    getHeadlineEvents(5),
      updatedAt:         _meta.updatedAt || null,
      dataState,
      mode:              _meta.mode || null,
    };
  }

  /**
   * @param {function} listener  (events, meta) => void
   * @returns {function} unsubscribe
   */
  function subscribe(listener) {
    if (typeof listener !== 'function') return () => {};
    // Stream Phase 5-A: 同一関数参照の二重 subscribe を防ぐ (初期化を誤って2回呼んでも増殖しない)。
    if (_listeners.indexOf(listener) >= 0) return () => {};
    _listeners.push(listener);
    return () => {
      const i = _listeners.indexOf(listener);
      if (i >= 0) _listeners.splice(i, 1);
    };
  }

  // Stream Phase 5-A: 長時間運用の診断用。subscriber/イベント件数が増殖していないか外部から確認できる。
  function getDiagnostics() {
    return {
      eventCount:      _events.length,
      subscriberCount: _listeners.length,
      updateCount:     _updateCount,
      lastUpdatedAt:   _meta.updatedAt || null,
    };
  }

  return { setEvents, getEvents, getEventsByType, getHeadlineEvents, getSummary, subscribe, getDiagnostics };
})();
