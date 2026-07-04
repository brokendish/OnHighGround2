// /live/stream — 状態制御・メインループ
// 依存: SCENES, buildScene, buildDemoStreamModels (live-stream-scene.js)
//        EarthquakeStreamAdapter (live-stream-earthquake-adapter.js)
//        RainStreamAdapter (live-stream-rain-adapter.js)
//        StreamMapEvents (live-stream-map-events.js) — real/demo共通の正規化
//        LiveStreamEventStore (live-stream-event-store.js) — 地図/パネル/テロップ共通ソース (Phase 3-C)
//        render (live-stream-panels.js)
//        LiveStreamClock, updateClock (live-stream-clock.js)
//        initTicker (live-stream-ticker.js)

const _params = new URLSearchParams(location.search);
const _rawState = _params.get('state');
// 通常 (/live/stream) は常に alert (実データ表示)。
// state=calm のみ平穏強制。デモ自動サイクルは廃止。
let _mode = (_rawState === 'calm') ? 'calm' : 'alert';  // calm | alert

// ?demo=1: デモデータ固定 (E2E安定化・実データ取得スキップ)
const _isDemo = _params.get('demo') === '1';

// Stream Phase 4-A: 自動巡回の有効/無効 (?focus=off / ?autofocus=0) と速度 (?focusSpeed=test, E2E高速化用)。
// 通常運用のデフォルトは常に enabled=true, speed=normal。
const _focusEnabled = !(_params.get('focus') === 'off' || _params.get('autofocus') === '0');
const _focusSpeed = _params.get('focusSpeed') === 'test' ? 'test' : 'normal';

// Stream Phase 5-A: fetch timeout の E2E高速化用 (focusSpeed とは衝突しない別名)。
// fetch の実行間隔 (2〜30分, カテゴリごとに既に調整済み) 自体は本番運用のまま変更しない。
const _runtimeSpeed = _params.get('runtimeSpeed') === 'test' ? 'test' : 'normal';

// 通常は開発用UIを非表示。?devControls=1 で表示する。
if (_params.get('devControls') !== '1') {
  const devEl = document.getElementById('dev');
  if (devEl) devEl.classList.add('hidden');
}

let _tick = 0, _lastSig = '';

// 地震実データ取得状態
let _liveEqModel = null;
let _eqStatus = 'pending'; // pending | ok | error

// 豪雨/キキクル実データ取得状態
let _liveRainModel = null;
let _rainStatus = 'pending'; // pending | ok | error

// 鉄道実データ取得状態
let _liveRailModel = null;
let _railStatus = 'pending'; // pending | ok | error

// 潮位実データ取得状態
let _liveTideModel = null;
let _tideStatus = 'pending'; // pending | ok | error

const _TIDE_SELECT = 8; // 1回のfetchで詳細を取得する地点数
// 全観測点 (現在50地点) を巡回して表示するための回転オフセット。
// 以前は常に withData.slice(0, N) で先頭 N 件 (北海道の稚内・小樽・函館・室蘭など、
// API が返す配列の先頭に固定的に並ぶ地点) のみを固定表示しており、他地点が一切表示されなかった。
// 初期値も時刻から分散させる: OBS ブラウザソースの再読み込み等でページが再訪問された場合でも
// 毎回まったく同じ地点から始まらないようにする (セッション内では通常通り30分ごとに進む)。
let _tideRotateOffset = Math.floor(Date.now() / 60000) % 97;
const FETCH_TIMEOUT_MS = _runtimeSpeed === 'test' ? 500 : 5000;

// AbortController で timeout する fetch。配信画面が API ハングで固まらないようにする。
async function _fetchJson(url, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs || FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// Stream Phase 5-A: すべての _fetchXxx() 共通ガード。in-flight 中は新規実行しない
// (setInterval とテスト用 forceRefresh() の両方から呼ばれても多重実行を防ぐ)。
// path: API key 等を含まない相対パスのみ (diagnostics.recentFetchFailures に出しても安全なもの)。
function _runtimeGuard(category, path) {
  if (typeof LiveStreamRuntime === 'undefined') return { start() {}, ok() {}, err() {} };
  if (LiveStreamRuntime.isInFlight(category)) return null;
  LiveStreamRuntime.recordFetchStart(category);
  return {
    ok: () => LiveStreamRuntime.recordFetchSuccess(category),
    // Stream Phase 5-C: diagnostics.recentFetchFailures 用に、失敗種別/メッセージを併せて記録する。
    err: (e) => LiveStreamRuntime.recordFetchError(category, {
      path: path || null,
      mode: _isDemo ? 'demo' : (_mode === 'calm' ? 'calm' : 'real'),
      errorName: (e && e.name) || null,
      errorMessage: (e && e.message) || null,
    }),
  };
}

async function _fetchEq() {
  const path = '/api/live/earthquakes/history';
  const guard = _runtimeGuard('earthquake', path);
  if (!guard) return; // 前回の取得がまだ in-flight
  const nowMs = LiveStreamClock.getNow().getTime();
  try {
    const data = await _fetchJson(`${path}?days=1`);
    _liveEqModel = EarthquakeStreamAdapter.build(data, nowMs);
    _eqStatus = 'ok';
    guard.ok();
    frame(true);
  } catch (e) {
    console.warn('[stream-eq] fetch failed:', e.message);
    _liveEqModel = { status: 'error', hasActiveEarthquake: false, targets: [], history: [], mapEvents: [], statusCount: 0 };
    _eqStatus = 'error';
    guard.err(e);
    frame(true);
  }
}

async function _fetchRain() {
  const path = '/api/live/summary';
  const guard = _runtimeGuard('rain', path);
  if (!guard) return;
  try {
    const data = await _fetchJson(path);
    _liveRainModel = RainStreamAdapter.build(data);
    _rainStatus = 'ok';
    guard.ok();
    frame(true);
  } catch (e) {
    console.warn('[stream-rain] fetch failed:', e.message);
    _liveRainModel = { status: 'error', hasActiveRain: false, targets: [], alerts: [], statusCount: 0 };
    _rainStatus = 'error';
    guard.err(e);
    frame(true);
  }
}

async function _fetchRail() {
  const path = '/api/live/trains/summary';
  const guard = _runtimeGuard('railway', path);
  if (!guard) return;
  try {
    const data = await _fetchJson(path);
    _liveRailModel = RailwayStreamAdapter.build(data);
    _railStatus = 'ok';
    guard.ok();
    frame(true);
  } catch (e) {
    console.warn('[stream-rail] fetch failed:', e.message);
    _liveRailModel = { status: 'error', affected: [], affectedCount: 0 };
    _railStatus = 'error';
    guard.err(e);
    frame(true);
  }
}

async function _fetchTide() {
  const path = '/api/live/tide/stations';
  const guard = _runtimeGuard('tide', path);
  if (!guard) return;
  try {
    const data = await _fetchJson(path);
    const withData = (data.stations || []).filter(s => s.has_data);

    if (withData.length === 0) {
      _liveTideModel = { status: 'ok', stations: [], alertCount: 0 };
      _tideStatus = 'ok';
      guard.ok();
      frame(true);
      return;
    }

    // 全観測点を順に一巡させる: fetch のたびに開始位置をずらして次の N 件を選ぶ。
    // 観測点数が _TIDE_SELECT 以下の場合は全件を毎回選ぶ (回転の意味がないため offset は 0 のまま)。
    const n = withData.length;
    const count = Math.min(_TIDE_SELECT, n);
    const start = _tideRotateOffset % n;
    const selected = [];
    for (let i = 0; i < count; i++) selected.push(withData[(start + i) % n]);
    _tideRotateOffset = (start + count) % n;

    const details = await Promise.all(
      selected.map(s =>
        _fetchJson(`/api/live/tide/stations/${encodeURIComponent(s.id)}`).catch(() => null)
      )
    );

    const validDetails = details.filter(Boolean);
    // 詳細が全件取得失敗した場合も 'ok' + 空地点 として扱う (デモ fallback を防ぐ)
    _liveTideModel = validDetails.length > 0
      ? TideStreamAdapter.build(validDetails)
      : { status: 'ok', stations: [], alertCount: 0 };
    _tideStatus = 'ok';
    guard.ok();
    frame(true);
  } catch (e) {
    console.warn('[stream-tide] fetch failed:', e.message);
    _liveTideModel = { status: 'error', stations: [], alertCount: 0 };
    _tideStatus = 'error';
    guard.err(e);
    frame(true);
  }
}

function frame(force) {
  const useDemo     = _isDemo || _eqStatus    === 'pending';
  const useRainDemo = _isDemo || _rainStatus  === 'pending';
  const useRailDemo = _isDemo || _railStatus  === 'pending';
  const useTideDemo = _isDemo || _tideStatus  === 'pending';
  let scene, kind;

  const _opts = (mode) => ({
    mode,
    useDemo,
    rainModel:    _liveRainModel,
    useRainDemo,
    railModel:    _liveRailModel,
    useRailDemo,
    tideModel:    _liveTideModel,
    useTideDemo,
  });

  if (_mode === 'calm') {
    scene = buildScene(_liveEqModel, { mode: 'calm' }); kind = 'calm';
  } else {
    // alert (デフォルト) / state 未指定: 実データで警戒表示
    scene = buildScene(_liveEqModel, _opts('alert')); kind = 'alert';
  }

  // モード変更 / 状態遷移 / 8秒サイクル進行 / 取得完了時のみ再描画
  const sig = _mode + '|' + kind + '|' + Math.floor(_tick / 8) + '|' + _eqStatus + '|' + _rainStatus + '|' + _railStatus + '|' + _tideStatus;
  if (!force && sig === _lastSig) return;
  _lastSig = sig;

  // Stream Phase 3-C: 地図・パネル・テロップ・全体ステータスの共通データソースを
  // LiveStreamEventStore に反映する (real / demo / calm すべて同じ経路)。
  const streamEvents = _computeStreamEvents(kind, scene);
  if (typeof LiveStreamEventStore !== 'undefined') {
    LiveStreamEventStore.setEvents(streamEvents, {
      mode:        _mode === 'calm' ? 'calm' : (_isDemo ? 'demo' : 'real'),
      dataState:   _computeDataState(streamEvents.length),
      fetchStatus: { earthquake: _eqStatus, rain: _rainStatus, railway: _railStatus, tide: _tideStatus },
      updatedAt:   LiveStreamClock.getNow().toISOString(),
    });
  }

  // Stream Phase 5-B: 路線図の太線強調は scene.rail.affected (カード一覧と同じ、座標の有無に
  // 関わらない全件) を直接使う。EventStore.getEventsByType('railway') は「地図上にピンを置ける
  // 座標がある路線」だけに絞り込まれる (StreamMapEvents._fromRailway が代表座標を取得できない
  // 路線を除外するため) ため、これを強調判定に流用すると、座標が無い/レガシーSVG対応表に無い
  // 事業者の路線が「カードには出るのに太線にはならない」という食い違いが起きていた。
  // calm は scene.rail.affected が空配列になるため、強調は自動的に消える (従来同様)。
  if (typeof LiveStreamRailwayLayer !== 'undefined' && scene && scene.rail) {
    LiveStreamRailwayLayer.setAffectedEvents((scene.rail.affected || []).map(a => ({ title: a.name })));
  }

  // Stream Phase 4-A: 自動巡回候補も EventStore と同じ正規化イベントから決める。
  // state=calm では巡回対象にしない (仕様通り)。
  if (typeof LiveStreamFocusController !== 'undefined') {
    LiveStreamFocusController.updateCandidates(_mode === 'calm' ? [] : streamEvents);
  }

  // 中央マップは実データモードのときだけ event 配列を渡す (store から読み出す = 同一ソース)。
  // demo/calm は null を渡し、render() 側で従来の scene ベース demo パルス表示にする
  // (data-testid 互換維持のため。store にはこのケースでも demo/calm の正規化 event が入っている)。
  const mapEvents = (_mode === 'calm' || _isDemo) ? null
    : (typeof LiveStreamEventStore !== 'undefined' ? LiveStreamEventStore.getEvents() : streamEvents);

  render(scene, _tick, mapEvents);

  // Stream Phase 5-A: body[data-stream-runtime-state] を最新化する。
  if (typeof LiveStreamRuntime !== 'undefined') LiveStreamRuntime.tick();
}

// 中央マップ・パネル・テロップの共通正規化イベント配列を算出する。
// real: 本番APIモデルから StreamMapEvents.build()。取得中/失敗のカテゴリは空扱い、demoへは絶対に落とさない。
// demo: scene (SCENES.alert) を buildDemoStreamModels() で本番モデル同等の形へ変換し、同じ正規化を通す。
// calm: 常に空配列。
function _computeStreamEvents(kind, scene) {
  if (kind === 'calm') return [];
  if (typeof StreamMapEvents === 'undefined') return [];
  const nowMs = LiveStreamClock.getNow().getTime();
  if (_isDemo) {
    const demoModels = (typeof buildDemoStreamModels === 'function') ? buildDemoStreamModels(scene) : {};
    return StreamMapEvents.build(Object.assign({ nowMs }, demoModels));
  }
  return StreamMapEvents.build({
    eqModel:   _eqStatus   === 'ok' ? _liveEqModel   : null,
    rainModel: _rainStatus === 'ok' ? _liveRainModel : null,
    railModel: _railStatus === 'ok' ? _liveRailModel : null,
    tideModel: _tideStatus === 'ok' ? _liveTideModel : null,
    nowMs,
  });
}

// dataState: 'ok' | 'partial' | 'empty' | 'unavailable'
// demo/calm は常に 'ok' 扱い (fetchを行わないため取得失敗という概念がない)。
function _computeDataState(totalEvents) {
  if (_mode === 'calm' || _isDemo) return 'ok';
  const statuses = [_eqStatus, _rainStatus, _railStatus, _tideStatus];
  if (statuses.every(s => s === 'error')) return 'unavailable';
  if (statuses.some(s => s === 'error' || s === 'pending')) return 'partial';
  return totalEvents > 0 ? 'ok' : 'empty';
}

// 1秒ごとにシーン評価 (再描画ガード付き)
setInterval(() => { _tick++; frame(false); }, 1000);

// 時計更新:
//   demoNow 固定時 → 初回のみ表示 (同値を毎秒更新する無駄を避ける)
//   実時刻時     → 毎秒更新
if (LiveStreamClock.isFixedDemoTime()) {
  updateClock();
} else {
  setInterval(updateClock, 1000);
}

// dev ボタン操作
const _devEl = document.getElementById('dev');
if (_devEl) {
  _devEl.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    _mode = b.dataset.state;
    _tick = 0;
    _devEl.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    frame(true);
  });
  _devEl.querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.state === _mode));
}

// フィット (プレビュー用; OBS 1920x1080 では scale=1)
function _fit() {
  const s = Math.min(innerWidth / 1920, innerHeight / 1080);
  const stage = document.getElementById('stage');
  if (stage) stage.style.transform = `scale(${s})`;
}
addEventListener('resize', _fit);

// 中央マップ (Leaflet) リサイズ対応: resize イベントを debounce して invalidateSize()
let _mapResizeTimer = null;
addEventListener('resize', () => {
  clearTimeout(_mapResizeTimer);
  _mapResizeTimer = setTimeout(() => {
    if (typeof _centerMapView !== 'undefined' && _centerMapView) _centerMapView.invalidateSize();
  }, 200);
});

// Stream Phase 4-A: 自動巡回コントローラ初期化。body[data-stream-focus-mode] を即座に 'overview' にする。
// フォーカス遷移 (overview/focus/returning) は main.js の 1秒tickとは非同期に自身のタイマーで起こるため、
// 状態が変わるたびに再描画をキックして地図marker/パネル/テロップへ即座に反映する。
// setTimeout(0) で1マクロタスク遅延させ、コントローラ内部の同期的な状態遷移処理と再入させない。
if (typeof LiveStreamFocusController !== 'undefined') {
  LiveStreamFocusController.init({ enabled: _focusEnabled, speed: _focusSpeed });
  LiveStreamFocusController.subscribe(() => { setTimeout(() => frame(true), 0); });
}

// 初期描画
_fit();
updateClock();
initTicker();
frame(true);
if (typeof _centerMapView !== 'undefined' && _centerMapView) _centerMapView.invalidateSize();

// Stream Phase 5-A: 診断レイヤーへ地図インスタンスを登録する (marker/layer 件数の外部確認用)。
if (typeof LiveStreamRuntime !== 'undefined' && typeof _centerMapView !== 'undefined' && _centerMapView) {
  LiveStreamRuntime.registerMapView(_centerMapView);
}

// 実データ取得 (demo=1 の場合はスキップ)。interval ID を保持し、diagnostics の stop/start から制御できるようにする。
let _fetchIntervalIds = [];
function _startFetchIntervals() {
  if (_isDemo || _fetchIntervalIds.length > 0) return; // 二重起動防止
  _fetchEq();
  _fetchRain();
  _fetchRail();
  _fetchTide();
  _fetchIntervalIds = [
    setInterval(_fetchEq,   3 * 60 * 1000),
    setInterval(_fetchRain, 3 * 60 * 1000),
    setInterval(_fetchRail, 2 * 60 * 1000),
    setInterval(_fetchTide, 30 * 60 * 1000), // 潮位は変化が遅いため間隔を長くとる
  ];
}
function _stopFetchIntervals() {
  _fetchIntervalIds.forEach(clearInterval);
  _fetchIntervalIds = [];
}
_startFetchIntervals();

// Stream Phase 5-A: E2E・手動検証用の diagnostics API。本番UIには一切表示しない。
// forceRefresh/stop/start はテスト・検証用途のみで、通常操作UIからは呼ばない。
window.__LiveStreamDiagnostics = {
  getSnapshot() {
    return (typeof LiveStreamRuntime !== 'undefined') ? LiveStreamRuntime.getSnapshot() : null;
  },
  forceRefresh() {
    if (_isDemo) return; // demo は fetch 自体を行わない
    _fetchEq(); _fetchRain(); _fetchRail(); _fetchTide();
  },
  stop: _stopFetchIntervals,
  start: _startFetchIntervals,
};
