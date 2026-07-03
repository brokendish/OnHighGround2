// /live/stream — 状態制御・メインループ
// 依存: SCENES, buildScene (live-stream-scene.js)
//        EarthquakeStreamAdapter (live-stream-earthquake-adapter.js)
//        RainStreamAdapter (live-stream-rain-adapter.js)
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

const _TIDE_SELECT = 4; // 詳細を取得する最大地点数

async function _fetchEq() {
  const nowMs = LiveStreamClock.getNow().getTime();
  try {
    const res = await fetch('/api/live/earthquakes/history?days=1');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _liveEqModel = EarthquakeStreamAdapter.build(data, nowMs);
    _eqStatus = 'ok';
    frame(true);
  } catch (e) {
    console.warn('[stream-eq] fetch failed:', e.message);
    _liveEqModel = { status: 'error', hasActiveEarthquake: false, targets: [], history: [], statusCount: 0 };
    _eqStatus = 'error';
    frame(true);
  }
}

async function _fetchRain() {
  try {
    const res = await fetch('/api/live/summary');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _liveRainModel = RainStreamAdapter.build(data);
    _rainStatus = 'ok';
    frame(true);
  } catch (e) {
    console.warn('[stream-rain] fetch failed:', e.message);
    _liveRainModel = { status: 'error', hasActiveRain: false, targets: [], alerts: [], statusCount: 0 };
    _rainStatus = 'error';
    frame(true);
  }
}

async function _fetchRail() {
  try {
    const res = await fetch('/api/live/trains/summary');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _liveRailModel = RailwayStreamAdapter.build(data);
    _railStatus = 'ok';
    frame(true);
  } catch (e) {
    console.warn('[stream-rail] fetch failed:', e.message);
    _liveRailModel = { status: 'error', affected: [], affectedCount: 0 };
    _railStatus = 'error';
    frame(true);
  }
}

async function _fetchTide() {
  try {
    const res = await fetch('/api/live/tide/stations');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const withData = (data.stations || []).filter(s => s.has_data);
    const selected = withData.slice(0, _TIDE_SELECT);

    if (selected.length === 0) {
      _liveTideModel = { status: 'ok', stations: [], alertCount: 0 };
      _tideStatus = 'ok';
      frame(true);
      return;
    }

    const details = await Promise.all(
      selected.map(s =>
        fetch(`/api/live/tide/stations/${encodeURIComponent(s.id)}`)
          .then(r => r.ok ? r.json() : null)
          .catch(() => null)
      )
    );

    const validDetails = details.filter(Boolean);
    // 詳細が全件取得失敗した場合も 'ok' + 空地点 として扱う (デモ fallback を防ぐ)
    _liveTideModel = validDetails.length > 0
      ? TideStreamAdapter.build(validDetails)
      : { status: 'ok', stations: [], alertCount: 0 };
    _tideStatus = 'ok';
    frame(true);
  } catch (e) {
    console.warn('[stream-tide] fetch failed:', e.message);
    _liveTideModel = { status: 'error', stations: [], alertCount: 0 };
    _tideStatus = 'error';
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
  render(scene, _tick);
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

// 初期描画
_fit();
updateClock();
initTicker();
frame(true);

// 実データ取得 (demo=1 の場合はスキップ)
if (!_isDemo) {
  _fetchEq();
  _fetchRain();
  _fetchRail();
  _fetchTide();
  setInterval(_fetchEq,   3 * 60 * 1000);
  setInterval(_fetchRain, 3 * 60 * 1000);
  setInterval(_fetchRail, 2 * 60 * 1000);
  setInterval(_fetchTide, 30 * 60 * 1000); // 潮位は変化が遅いため間隔を長くとる
}
