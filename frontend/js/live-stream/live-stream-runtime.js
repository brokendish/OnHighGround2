'use strict';
// /live/stream — 配信運用向け Runtime 状態管理・diagnostics (Stream Phase 5-A)
//
// このモジュール自体は描画も fetch も行わない。既存の4カテゴリ (地震/豪雨/鉄道/潮位) 独立 fetch
// 構成 (live-stream-main.js) を変えずに、その健全性を「外から検証できる」ようにする診断レイヤー。
// main.js が各 _fetchXxx() の開始/成功/失敗を record* で報告し、本モジュールが
// in-flight 判定・連続失敗カウント・全体 runtimeState (healthy/degraded/error/loading) を導出する。

const LiveStreamRuntime = (function () {

  const CATEGORIES = ['earthquake', 'rain', 'railway', 'tide'];
  const ERROR_THRESHOLD = 3; // 連続失敗3回以上で 'error' 扱い (仕様書 Step 8 の目安に準拠)
  const MAX_RECENT_FAILURES = 5; // Stream Phase 5-C: 直近の fetch failure 概要 (最大件数を制限)

  const _cat = {};
  CATEGORIES.forEach(c => {
    _cat[c] = {
      inFlight: false,
      count: 0,
      successCount: 0,
      failureCount: 0,
      consecutiveFailures: 0,
      status: 'pending', // pending | ok | error
      lastStartedAt: null,
      lastFinishedAt: null,
      lastSuccessAt: null,
      lastErrorAt: null,
    };
  });

  const _startedAt = Date.now();
  let _mapViewRef = null;
  // Stream Phase 5-C: 直近の fetch failure 概要 (API key/token/長いURL全文は含めない)。
  let _recentFetchFailures = [];

  /**
   * @param {object} detail  { category, path, mode, errorName, errorMessage }
   *   category: "earthquake" | "rain" | "railway" | "tide" | "railwayLayer" | "rainTile" | "unknown"
   *   path:     API key 等を含まない相対パスのみ
   */
  function recordFetchFailureDetail(detail) {
    const d = detail || {};
    _recentFetchFailures.push({
      category:     d.category || 'unknown',
      path:         d.path || null,
      mode:         d.mode || null,
      errorName:    d.errorName || null,
      errorMessage: d.errorMessage || null,
      timestamp:    new Date().toISOString(),
    });
    if (_recentFetchFailures.length > MAX_RECENT_FAILURES) _recentFetchFailures.shift();
  }
  // Stream Phase 5-A.1: 地震子画面 市区町村震度詳細の状態 (panels.js から都度上書きされる)。
  // このモジュール自体は詳細の計算を行わない (既存の「fetch/diagnostics のみ管理する」方針を維持)。
  let _eqDetailDiag = null;

  function setEarthquakeDetailDiagnostics(diag) {
    _eqDetailDiag = diag || null;
  }

  // Stream Phase 5-A bundle B: 鉄道子画面 詳細表示の状態 (panels.js から都度上書きされる)。
  let _railDetailDiag = null;

  function setRailwayDetailDiagnostics(diag) {
    _railDetailDiag = diag || null;
  }

  // Stream Phase 5-A bundle C: メイン地図 鉄道路線カラーレイヤーの状態 (live-stream-railway-layer.js から)。
  let _railwayLayerDiag = null;

  function setRailwayLayerDiagnostics(diag) {
    _railwayLayerDiag = diag || null;
  }

  // Stream Phase 5-A.1 (railway calm map): 鉄道子画面小地図の状態 (panels.js から都度上書きされる)。
  let _railwayMiniMapDiag = null;

  function setRailwayMiniMapDiagnostics(diag) {
    _railwayMiniMapDiag = diag || null;
  }

  function recordFetchStart(category) {
    const c = _cat[category];
    if (!c) return;
    c.inFlight = true;
    c.count += 1;
    c.lastStartedAt = new Date().toISOString();
  }

  function recordFetchSuccess(category) {
    const c = _cat[category];
    if (!c) return;
    c.inFlight = false;
    c.successCount += 1;
    c.consecutiveFailures = 0;
    c.status = 'ok';
    c.lastFinishedAt = new Date().toISOString();
    c.lastSuccessAt = c.lastFinishedAt;
  }

  // @param {object} [errorDetail]  { path, mode, errorName, errorMessage } — 渡すと
  //   recentFetchFailures にも同時記録する (Stream Phase 5-C)。
  function recordFetchError(category, errorDetail) {
    const c = _cat[category];
    if (!c) return;
    c.inFlight = false;
    c.failureCount += 1;
    c.consecutiveFailures += 1;
    c.status = 'error';
    c.lastFinishedAt = new Date().toISOString();
    c.lastErrorAt = c.lastFinishedAt;
    if (errorDetail) recordFetchFailureDetail(Object.assign({ category }, errorDetail));
  }

  // main.js の各 _fetchXxx() 冒頭で呼ぶ。true が返ったら既に in-flight なので今回は skip する。
  function isInFlight(category) {
    const c = _cat[category];
    return !!(c && c.inFlight);
  }

  // Stream Phase 5-C: real / demo / calm の判定は LiveStreamEventStore.setEvents() に渡される
  // meta.mode (main.js が real|demo|calm を一意に決めて渡す唯一の情報源) をそのまま読む。
  // ここで新たに mode 判定ロジックを持たない (二重管理による情報の乖離を避ける)。
  function _dataMode() {
    const summary = (typeof LiveStreamEventStore !== 'undefined' && LiveStreamEventStore.getSummary)
      ? LiveStreamEventStore.getSummary() : null;
    return (summary && summary.mode) || null; // 'real' | 'demo' | 'calm' | null (初期化前)
  }

  // demo mode は「本番API取得に失敗している」状態ではなく「本番APIを使わない synthetic 表示」
  // なので、4カテゴリが ずっと pending のままでも 'loading' (取得中扱い) にしない。
  // calm も同様に、実際の fetch 成否とは独立した「平穏表示を強制している」状態として区別する。
  function _runtimeState() {
    const mode = _dataMode();
    if (mode === 'calm') return 'calm';
    if (mode === 'demo') return 'demo';
    const statuses = CATEGORIES.map(c => _cat[c].status);
    if (statuses.every(s => s === 'pending')) return 'loading';
    const maxConsecutive = Math.max(...CATEGORIES.map(c => _cat[c].consecutiveFailures));
    if (statuses.every(s => s === 'error') || maxConsecutive >= ERROR_THRESHOLD) return 'error';
    if (statuses.some(s => s === 'error')) return 'degraded';
    return 'healthy';
  }

  // main.js の render サイクルから毎フレーム呼び、body[data-stream-runtime-state] を最新化する。
  // 既存の body[data-stream-status] (Phase 3-D, 警戒レベル用) とは別属性で競合しない。
  function tick() {
    if (typeof document !== 'undefined' && document.body) {
      document.body.dataset.streamRuntimeState = _runtimeState();
      document.body.dataset.streamDataMode = _dataMode() || 'real';
    }
  }

  function registerMapView(view) {
    _mapViewRef = view;
  }

  function _domSnapshot() {
    if (typeof document === 'undefined') return null;
    const count = sel => document.querySelectorAll(sel).length;
    return {
      mapEventMarkerDom: count('.stream-map-event-icon'),
      pulseMarkerDom:    count('.ls-pulse-icon'),
      railCards:         count('.rail-card'),
      tideCells:         count('.tide-cell'),
      tickerTextNodes:   count('.ls-ticker .move > *'),
    };
  }

  /**
   * E2E・手動検証用のスナップショット。本番UIには使わない。
   */
  function getSnapshot() {
    const byCategory = {};
    CATEGORIES.forEach(c => { byCategory[c] = Object.assign({}, _cat[c]); });

    const refreshInFlight     = CATEGORIES.some(c => _cat[c].inFlight);
    const refreshCount        = CATEGORIES.reduce((s, c) => s + _cat[c].count, 0);
    const successCount        = CATEGORIES.reduce((s, c) => s + _cat[c].successCount, 0);
    const failureCount        = CATEGORIES.reduce((s, c) => s + _cat[c].failureCount, 0);
    const consecutiveFailures = Math.max(...CATEGORIES.map(c => _cat[c].consecutiveFailures));
    const lastSuccessAt = CATEGORIES.map(c => _cat[c].lastSuccessAt).filter(Boolean).sort().pop() || null;
    const lastErrorAt   = CATEGORIES.map(c => _cat[c].lastErrorAt).filter(Boolean).sort().pop() || null;

    const eventStoreDiag = (typeof LiveStreamEventStore !== 'undefined' && LiveStreamEventStore.getDiagnostics)
      ? LiveStreamEventStore.getDiagnostics() : null;
    const focusDiag = (typeof LiveStreamFocusController !== 'undefined') ? {
      ...((LiveStreamFocusController.getDiagnostics && LiveStreamFocusController.getDiagnostics()) || {}),
      ...((LiveStreamFocusController.getState && LiveStreamFocusController.getState()) || {}),
    } : null;
    const mapDiag = _mapViewRef && _mapViewRef.getDiagnostics ? _mapViewRef.getDiagnostics() : null;
    const dom = _domSnapshot();
    const dataMode = _dataMode() || 'real';

    return {
      runtimeState: _runtimeState(),
      dataMode,
      isDemo: dataMode === 'demo',
      isCalm: dataMode === 'calm',
      uptimeMs: Date.now() - _startedAt,

      refreshInFlight,
      refreshCount,
      successCount,
      failureCount,
      consecutiveFailures,
      lastSuccessAt,
      lastErrorAt,
      recentFetchFailures: _recentFetchFailures.slice(),

      eventCount:      eventStoreDiag ? eventStoreDiag.eventCount : null,
      subscriberCount: eventStoreDiag ? eventStoreDiag.subscriberCount : null,
      updateCount:     eventStoreDiag ? eventStoreDiag.updateCount : null,

      focusMode:        focusDiag ? focusDiag.mode : null,
      focusEventId:     focusDiag ? focusDiag.activeEventId : null,
      focusSubscribers: focusDiag ? focusDiag.subscriberCount : null,

      mapInitialized: mapDiag ? mapDiag.mapInitialized : null,
      markerCount:    mapDiag ? (mapDiag.eventMarkerCount + mapDiag.pulseMarkerCount) : null,

      dom,
      byCategory,
      earthquakeDetail: _eqDetailDiag,
      railwayDetail: _railDetailDiag,
      railwayLayer: _railwayLayerDiag,
      railwayMiniMap: _railwayMiniMapDiag,
      memory: (typeof performance !== 'undefined' && performance.memory)
        ? { usedJSHeapSize: performance.memory.usedJSHeapSize }
        : null,
    };
  }

  return {
    recordFetchStart, recordFetchSuccess, recordFetchError, isInFlight,
    recordFetchFailureDetail,
    tick, registerMapView, getSnapshot,
    setEarthquakeDetailDiagnostics, setRailwayDetailDiagnostics, setRailwayLayerDiagnostics, setRailwayMiniMapDiagnostics,
  };
})();
