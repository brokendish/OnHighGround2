'use strict';
// /live/stream — 自動巡回・注目地域フォーカス制御 (Stream Phase 4-A)
//
// LiveStreamEventStore の正規化イベントのみを判断材料にする状態機械。
// DOM描画・地図移動は一切行わず、状態変化を subscribe() 経由で通知するだけ。
// 実際の地図移動・DOMクラス付与は呼び出し側 (live-stream-panels.js) が行う。
// body[data-stream-focus-mode] / body[data-stream-focus-event-id] のみ、
// このモジュール自身が直接書き込む (E2E から素早く参照できるようにするため)。
//
// 状態: overview | focus | returning (focus を離れて overview へ戻る一瞬の遷移状態)
// 無効化時 (focus=off 等) は常に overview に留まり、タイマーは一切動かさない。

const LiveStreamFocusController = (function () {

  const DURATIONS = {
    normal: { overview: 15000, focus: 12000, returning: 3000, minRebuild: 5000 },
    // E2E高速化用。通常運用のデフォルトはこちらにしない。
    test:   { overview: 900,   focus: 900,   returning: 250,  minRebuild: 200 },
  };

  let _enabled = true;
  let _speed = 'normal';
  let _mode = 'overview';
  let _candidates = [];
  let _activeIndex = -1;
  let _timer = null;
  let _lastRebuildAt = 0;
  const _listeners = [];

  // Stream Phase 5-A.1: 子画面側 (地震詳細の市区町村震度スクロール/小地図巡回など) が
  // 「まだ見せ終わっていない」間、自動巡回の advance を一時停止するための最小限の hold 機構。
  // requestHold() を呼んだ側だけが releaseHold() で明示的に解除できる (source で区別)。
  //
  // Stream Phase 5-A bundle: 地震詳細に加え鉄道詳細 (railway-detail) も hold を使うようになったため、
  // 単一の _hold 変数ではなく source をキーにした Map で複数 source の hold を独立管理する
  // (例: 地震の tour 中に鉄道詳細の hold が発生しても、互いの hold を上書き消去しない)。
  const _holds = new Map(); // source -> { source, eventId, until }
  const MAX_HOLD_MS = 60000;

  function _d() { return DURATIONS[_speed] || DURATIONS.normal; }

  function _activeEvent() {
    return (_activeIndex >= 0 && _activeIndex < _candidates.length) ? _candidates[_activeIndex] : null;
  }

  function _applyModeToBody() {
    if (typeof document === 'undefined' || !document.body) return;
    const ev = _activeEvent();
    document.body.dataset.streamFocusMode = _mode;
    document.body.dataset.streamFocusEventId = ev ? ev.id : '';
  }

  // body[data-stream-panel-hold*] は複数 source を同時に表現できないスカラー属性のため、
  // 現在有効な hold のうち1件 (Map挿入順で最初に見つかったもの) を代表として反映する。
  // 個別 source の正確な状態は getHold(source) / getState().holds を参照する。
  function _applyHoldToBody() {
    if (typeof document === 'undefined' || !document.body) return;
    const first = _holds.size > 0 ? _holds.values().next().value : null;
    document.body.dataset.streamPanelHold = first ? first.source : '';
    document.body.dataset.streamPanelHoldEventId = first ? (first.eventId || '') : '';
    document.body.dataset.streamPanelHoldUntil = first ? new Date(first.until).toISOString() : '';
  }

  /**
   * @param {object} opts  { source: string, eventId: string|null, durationMs: number }
   */
  function requestHold(opts) {
    const o = opts || {};
    const source = o.source || 'unknown';
    const durationMs = Math.min(Math.max(Number(o.durationMs) || 8000, 1000), MAX_HOLD_MS);
    _holds.set(source, { source, eventId: o.eventId || null, until: Date.now() + durationMs });
    _applyHoldToBody();
  }

  // source を省略すると全 hold を無条件解除。指定すると同じ source の hold のみ解除する。
  function releaseHold(source) {
    const changed = source ? _holds.delete(source) : (_holds.size > 0 && (_holds.clear(), true));
    if (changed) _applyHoldToBody();
  }

  // 期限切れ・対象消失した hold を掃除する (すべての source について)。
  function _sweepHolds() {
    let changed = false;
    for (const [source, h] of _holds) {
      if (Date.now() >= h.until) { _holds.delete(source); changed = true; continue; }
      if (h.eventId && !_candidates.some(e => e.id === h.eventId)) { _holds.delete(source); changed = true; }
    }
    if (changed) _applyHoldToBody();
  }

  // 現在 focus 中の event を hold している source が1つでもあるか (advance 抑止判定用)。
  function _holdActive() {
    _sweepHolds();
    const ev = _activeEvent();
    if (!ev) return false;
    for (const h of _holds.values()) {
      if (h.eventId === ev.id) return true;
    }
    return false;
  }

  // 特定 source の hold 状態を取得する (地震子画面ローカル固定等、source単位の判定に使う)。
  function getHold(source) {
    _sweepHolds();
    const h = _holds.get(source);
    return h ? { source: h.source, eventId: h.eventId, until: h.until } : null;
  }

  function _notify() {
    const state = getState();
    _listeners.forEach(fn => {
      try { fn(state); } catch (e) { console.warn('[LiveStreamFocusController] listener error:', e.message); }
    });
  }

  function _clearTimer() {
    if (_timer) { clearTimeout(_timer); _timer = null; }
  }

  // 巡回停止中でも状態表示・購読者通知は行うが、タイマーは張らない。
  function _scheduleIfEnabled(fn, ms) {
    if (!_enabled) return;
    _timer = setTimeout(fn, ms);
  }

  function _enterOverview() {
    _clearTimer();
    _mode = 'overview';
    _activeIndex = -1;
    _applyModeToBody();
    _notify();
    _scheduleIfEnabled(_advance, _d().overview);
  }

  // focus → overview は一瞬 'returning' を経由し、地図の帰還アニメーションを開始する余地を作る。
  function _returnToOverview() {
    _clearTimer();
    _mode = 'returning';
    _activeIndex = -1;
    _applyModeToBody();
    _notify();
    if (!_enabled) { _enterOverview(); return; }
    _timer = setTimeout(_enterOverview, _d().returning);
  }

  function _enterFocus(index) {
    _clearTimer();
    _mode = 'focus';
    _activeIndex = index;
    _applyModeToBody();
    _notify();
    _scheduleIfEnabled(_advance, _d().focus);
  }

  function _advance() {
    if (!_enabled) return;
    // hold は「今まさに focus 中の対象を hold している source が1つでもある」場合にだけ
    // 次への遷移を止める (_holdActive() が判定)。他カテゴリが focus 中のときは、
    // 地震/鉄道詳細どちらの hold とも無関係に通常どおり巡回させる
    // (hold は「今表示している対象から切り替えない」ためのものであり、
    //  無関係な focus 巡回まで全体停止させると自動巡回自体が長時間止まってしまう)。
    if (_holdActive()) {
      // 子画面側がまだ表示し終えていない: 遷移せず短い間隔で再チェックするだけに留める。
      _timer = setTimeout(_advance, 1000);
      return;
    }
    if (_candidates.length === 0) { _enterOverview(); return; }
    if (_mode !== 'focus') { _enterFocus(0); return; }
    const next = _activeIndex + 1;
    if (next >= _candidates.length) { _returnToOverview(); }
    else { _enterFocus(next); }
  }

  /**
   * 候補イベント一覧を差し替える。
   * - MIN_REBUILD_INTERVAL_MS 未満での頻繁な入れ替えは抑制する (候補が空→非空/非空→空の遷移は即時反映)。
   * - 現在フォーカス中の event が新候補にも含まれる場合はフォーカスを維持する (カメラジャンプ抑制)。
   * - フォーカス中の event が候補から消えた場合は直ちに解除し、次候補があれば移る、なければ overview へ。
   *
   * @param {Array} events  LiveStreamEventStore.getEvents() の出力。calm 時は呼び出し側で [] を渡す。
   */
  function updateCandidates(events) {
    const next = (typeof LiveStreamFocusPolicy !== 'undefined') ? LiveStreamFocusPolicy.selectCandidates(events) : [];
    const nextIds = next.map(e => e.id).join('|');
    const curIds = _candidates.map(e => e.id).join('|');
    if (nextIds === curIds) { _candidates = next; return; }

    const now = Date.now();
    const bothNonEmpty = _candidates.length > 0 && next.length > 0;
    if (bothNonEmpty && (now - _lastRebuildAt) < _d().minRebuild) return;
    _lastRebuildAt = now;

    const curActive = _activeEvent();
    _candidates = next;

    if (curActive) {
      const stillIdx = _candidates.findIndex(e => e.id === curActive.id);
      if (stillIdx >= 0) {
        _activeIndex = stillIdx;
        _applyModeToBody();
        _notify();
        return;
      }
      // フォーカス中だった event が消えた → 直ちに次候補 or overview へ。
      if (_candidates.length > 0) { _enterFocus(0); }
      else { _enterOverview(); }
      return;
    }

    if (_candidates.length === 0) { _enterOverview(); return; }
    // overview で巡回停止中に新規候補が現れた場合、既存タイマーがあればそれを尊重する
    // (頻繁なカメラジャンプを避けるため、即座には飛びつかない)。
    if (_mode === 'overview' && !_timer) {
      _scheduleIfEnabled(_advance, _d().overview);
    }
  }

  /**
   * @param {object} [options]  { enabled: boolean, speed: 'normal'|'test' }
   */
  function init(options) {
    const o = options || {};
    // 注意: stop() は呼ばない。stop() は購読者も破棄するが、panels.js 側は
    // モジュール読み込み時 (init() より前) に subscribe() 済みのため、ここで listeners を
    // クリアすると地図カメラ追従・フォーカスラベル更新が一切効かなくなる。
    _clearTimer();
    _enabled = o.enabled !== false;
    _speed = o.speed === 'test' ? 'test' : 'normal';
    _mode = 'overview';
    _activeIndex = -1;
    _candidates = [];
    _lastRebuildAt = 0;
    _applyModeToBody();
    _scheduleIfEnabled(_advance, _d().overview);
  }

  function getState() {
    // _sweepHolds() で期限切れ・対象消失時の自動解除を確定させてから読む。
    // _advance() 経由でしか hold を評価しないと、focus=off (無効化時、タイマー自体が動かない)
    // や advance 間隔の合間では期限切れの hold を読み手 (panels.js の地震/鉄道子画面ローカル固定など) が
    // いつまでも「hold中」と誤認してしまうため、参照系はここでも必ず最新化する。
    _sweepHolds();
    const ev = _activeEvent();
    const first = _holds.size > 0 ? _holds.values().next().value : null;
    return {
      mode: _mode,
      enabled: _enabled,
      activeEventId: ev ? ev.id : null,
      activeEvent: ev,
      candidates: _candidates.slice(),
      // 後方互換: Phase 5-A.1 時点は hold が同時に1件のみだった前提の単数形フィールド。
      // 現在有効な hold のうち代表1件を反映する (body[data-stream-panel-hold*] と同じ選び方)。
      holdSource:  first ? first.source : null,
      holdEventId: first ? first.eventId : null,
      holdUntil:   first ? first.until : null,
      // Stream Phase 5-A bundle: 複数 source の hold を同時に確認できる完全な一覧。
      holds: Array.from(_holds.values()).map(h => ({ source: h.source, eventId: h.eventId, until: h.until })),
    };
  }

  function subscribe(listener) {
    if (typeof listener !== 'function') return () => {};
    // Stream Phase 5-A: 同一関数参照の二重 subscribe を防ぐ。
    if (_listeners.indexOf(listener) >= 0) return () => {};
    _listeners.push(listener);
    return () => {
      const i = _listeners.indexOf(listener);
      if (i >= 0) _listeners.splice(i, 1);
    };
  }

  function stop() {
    _clearTimer();
    _listeners.length = 0;
  }

  // Stream Phase 5-A: 長時間運用の診断用。subscriber 数やタイマーの有無を外部から確認できる。
  function getDiagnostics() {
    return {
      subscriberCount: _listeners.length,
      timerActive:      !!_timer,
      speed:            _speed,
      enabled:           _enabled,
      holdActive:       _holdActive(),
      holdCount:        _holds.size,
    };
  }

  return {
    init, updateCandidates, getState, subscribe, stop, getDiagnostics,
    requestHold, releaseHold, getHold,
  };
})();
