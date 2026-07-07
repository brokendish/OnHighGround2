// /live/stream — メイン描画 render(scene, tick, mapEvents)
// 時計は live-stream-clock.js で別 interval 管理。
// 毎秒フル再描画せず、モード変更 / 状態遷移 / 8秒サイクル進行時のみ再描画。
// 依存: renderMap, zoomToTarget, renderTide (live-stream-map.js)
//        LiveStreamMapView (live-stream-map-view.js) — 中央マップ Leaflet 本番地図
//        RAIL_LINES_BASE, TICKER_TEXT, RAIL_PULSE_LATLON (live-stream-scene.js)
//        LiveStreamClock (live-stream-clock.js)
// mapEvents (第3引数) は main.js の _computeMapEvents() (live-stream-map-events.js の
// StreamMapEvents.build() を呼ぶ) が算出する。null=demo/calmパルス表示、配列=本番データ表示。

const FULL_VIEW = {zoom:1, cx:500, cy:650};
const $s = id => document.getElementById(id);
let _lastTickerText = '';

// 中央メイン地図 — Leaflet 本番地図 (Stream Phase 3-A)
// 初期化失敗時 (Leaflet 未ロード等) は null のままとし、render() 側で旧SVGモック地図へフォールバックする。
let _centerMapView = null;
(function initCenterMap() {
  if (typeof LiveStreamMapView === 'undefined') return;
  const view = new LiveStreamMapView({ containerId: 'center-map', mode: 'center', interactive: false });
  const ok = view.initialize();
  _centerMapView = ok ? view : null;
})();

// 地震子画面 小地図 — Stream Phase 5-A bundle: 本番Leaflet地図化 (Phase 5-A.1 時点のSVGモック地図から移行)。
// 中央地図 (_centerMapView) と同じ singleton パターン。地震切替のたびにインスタンスを作り直さず、
// marker layer (setIntensityMarkers) だけを差し替える。初期化失敗時は旧SVG小窓へフォールバックする。
let _eqMiniMapView = null;
(function initEqMiniMap() {
  if (typeof LiveStreamMapView === 'undefined') return;
  const view = new LiveStreamMapView({ containerId: 'eq-map', mode: 'eq-mini', interactive: false });
  const ok = view.initialize();
  _eqMiniMapView = ok ? view : null;
})();

// キキクル・豪雨子画面 小地図 — Stream Phase 5-A.1: モックSVG(抽象的な雨雲ブロブ)では場所の特定が
// 困難という指摘を受け、地震子画面と同じ本番Leaflet地図 (+実降水ナウキャストタイル) へ移行する。
// 対象切替のたびにインスタンスを作り直さず、pulse marker と camera 位置だけ差し替える。
let _rainMiniMapView = null;
let _rainMiniMapActiveId = null; // 直近で flyTo した対象 id (同一対象への再flyToを避けるため)
(function initRainMiniMap() {
  if (typeof LiveStreamMapView === 'undefined') return;
  const view = new LiveStreamMapView({ containerId: 'rain-map', mode: 'rain-mini', interactive: false });
  const ok = view.initialize();
  _rainMiniMapView = ok ? view : null;
})();

// 鉄道子画面 小地図 — Stream Phase 5-A.1 (railway calm map): 平常時 (影響路線0件) でも
// 首都圏ODPT対応路線が収まる範囲で路線図を表示するため、SVGモック(RAIL_LINES_BASE 4路線のみ)から
// 本番Leaflet+PMTiles地図 (中央地図と同じ全国路線データ・同じ公式カラー表) へ移行する。
// 影響路線の有無に関わらず毎回 fixed bounds で初期化する (「路線図を出すか」と「強調するか」を分離)。
const STREAM_RAILWAY_DEFAULT_BOUNDS = [
  [35.50, 139.45],
  [35.90, 140.05],
];
let _railMiniMapView = null;
(function initRailMiniMap() {
  if (typeof LiveStreamMapView === 'undefined') return;
  const view = new LiveStreamMapView({ containerId: 'rail-map', mode: 'rail-mini', interactive: false });
  const ok = view.initialize();
  if (!ok) return;
  view.fitTo(STREAM_RAILWAY_DEFAULT_BOUNDS, { animate: false });
  _railMiniMapView = view;
})();

// Stream Phase 4-A/4-B — 自動巡回コントローラの状態変化を購読し、中央地図のカメラを動かす。
// ユーザー操作は無効のままだが、プログラムによる移動 (flyTo/fitBounds) は許可する。
const _FOCUS_ZOOM_BY_TYPE = { earthquake: 6, rain: 7, kikikuru: 7, railway: 9, tide: 8, water: 8 };
// Stream Phase 5-A: 同じ focus (mode+event id) へ notify のたびに毎回 flyTo/fitBounds し直さない。
// updateCandidates() は候補リストが更新されただけでも同じ active event を維持したまま notify するため、
// 対策なしだと「対象は変わっていないのに地図が何度も同じ場所へ飛び直す」冗長な発火が起きていた。
let _lastAppliedFocusKey = null;
(function initFocusMapBinding() {
  if (typeof LiveStreamFocusController === 'undefined') return;
  LiveStreamFocusController.subscribe(state => {
    if (!_centerMapView) return;
    const key = state.mode + ':' + (state.activeEventId || '');
    const changed = key !== _lastAppliedFocusKey;
    _lastAppliedFocusKey = key;
    if (changed) {
      if (state.mode === 'focus' && state.activeEvent) {
        const zoom = _FOCUS_ZOOM_BY_TYPE[state.activeEvent.type] || 7;
        _centerMapView.focusOn(state.activeEvent.lat, state.activeEvent.lng, zoom);
      } else if (state.mode === 'returning' || state.mode === 'overview') {
        _centerMapView.fitJapan(true); // returning への遷移を滑らかにする (Stream Phase 4-B)
      }
    }
    _renderFocusHud(state); // HUD反映は軽量・冪等なので毎回更新してよい
  });
})();

// 中央地図上部の Focus HUD (Stream Phase 4-B)。
// data-focus-* 属性は mode に関わらず常に現在状態を反映し (body の値と矛盾させない)、
// 表示 (hidden 解除) は focus 中のみに絞って既存UI (パネル/テロップ) を邪魔しない。
function _renderFocusHud(state) {
  const el = $s('focus-hud');
  if (!el) return;
  const ev = state.activeEvent;
  el.dataset.focusMode = state.mode;
  el.dataset.focusEventId = ev ? ev.id : '';
  el.dataset.focusType = ev ? ev.type : '';
  el.dataset.focusSeverity = ev ? ev.severity : '';

  const titleEl = $s('focus-hud-title');
  const subEl = $s('focus-hud-sub');
  if (state.mode === 'focus' && ev) {
    if (titleEl) titleEl.textContent = `注目：${ev.title || '不明'}`;
    if (subEl) subEl.textContent = ev.subtitle || '';
    el.hidden = false;
  } else {
    if (titleEl) titleEl.textContent = '';
    if (subEl) subEl.textContent = '';
    el.hidden = true;
  }
}

// 潮位 正弦モデルで任意時刻の潮位(cm)を計算する (デモ用)
function _tideLvl(st, hourFloat) {
  return st.base + st.amp * Math.sin(2 * Math.PI * (hourFloat - st.phase) / 12.42);
}

// 実潮位記録 [{h, cm}] から時刻 h に対応する潮位を線形補間する
function _interpolateFromRecords(records, h) {
  if (!records || records.length === 0) return null;
  if (h <= records[0].h) return records[0].cm;
  if (h >= records[records.length - 1].h) return records[records.length - 1].cm;
  for (let i = 0; i < records.length - 1; i++) {
    const a = records[i], b = records[i + 1];
    if (a.h <= h && h <= b.h && b.h > a.h) {
      return Math.round(a.cm + (h - a.h) / (b.h - a.h) * (b.cm - a.cm));
    }
  }
  return records[records.length - 1].cm;
}

// SVGフォールバック用の簡易 緯度経度→SVG座標 投影 (adapter群と同じ基準点)
function _fallbackLatLonToSvg(lat, lng) {
  if (lat == null || lng == null) return [500, 650];
  const x = Math.round(582 + (lng - 139.7) * 25);
  const y = Math.round(500 + (lat - 35.7) * (-35));
  return [Math.max(100, Math.min(900, x)), Math.max(100, Math.min(1200, y))];
}

/* ================================================================
   Stream Phase 5-A.1 — 地震子画面 市区町村震度詳細
   (list/mini-map の DOM 更新は本モジュールが行う。正規化のみ live-stream-earthquake-detail.js)
   ================================================================ */

const _EQ_MUNI_VISIBLE_ROWS = 7;
const _EQ_MUNI_MIN_MS = 8000;
const _EQ_MUNI_MAX_MS = 60000; // LiveStreamFocusController の MAX_HOLD_MS と合わせる (それ以上保持しても意味がない)
const _EQ_MINI_FRAME_MS = 4000;
const _EQ_MINI_MAX_FRAMES = 6;

let _eqDetailActiveId = null;    // 現在 list/mini-map を構築済みの event id (null = 詳細非表示)
let _eqDetailPlan = null;        // _buildEqDetailPlan() の結果
let _eqDetailEqCurRef = null;    // 現在の eqCur (at/s/r 参照用。render() のたびに更新)
let _eqDetailFrameIndex = 0;     // 小地図 tour の現在フレーム (0-based)
let _eqDetailFrameElapsedMs = 0;
let _eqDetailListStartedAt = 0;

const _EQ_INTENSITY_CLASS = {
  '1':'1', '2':'2', '3':'3', '4':'4',
  '5弱':'5-lower', '5強':'5-upper', '6弱':'6-lower', '6強':'6-upper', '7':'7',
};
const _EQ_INTENSITY_COLOR = {
  '1':'#b3d4f5','2':'#3c9be8','3':'#39c468','4':'#f9c74f',
  '5弱':'#f8961e','5強':'#f3722c','6弱':'#e53935','6強':'#b71c1c','7':'#4a148c','不明':'#9e9e9e',
};
const _EQ_INTENSITY_LABEL = { '5弱':'5-', '5強':'5+', '6弱':'6-', '6強':'6+' };

function _eqEsc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, ch =>
    ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
}

// SVG小窓の投影 (adapter群/live-stream-earthquake-adapter.js の _latLonToSvg と同一基準点)
function _eqMuniLatLonToSvg(lat, lng) {
  const x = Math.round(582 + (lng - 139.7) * 25);
  const y = Math.round(500 + (lat - 35.7) * (-35));
  return [Math.max(80, Math.min(920, x)), Math.max(80, Math.min(1220, y))];
}

// 市区町村 (座標ありのみ) を都道府県単位でグループ化し、グループ内最大震度の降順に並べる。
// 小地図 tour の各フレームに対応する。座標なし市区町村はどのフレームにも含めない (リストのみ表示)。
function _eqGroupMunicipalitiesByPref(municipalities) {
  const order = [];
  const byPref = new Map();
  municipalities.forEach(m => {
    if (m.lat == null || m.lng == null) return;
    if (!byPref.has(m.pref)) { byPref.set(m.pref, []); order.push(m.pref); }
    byPref.get(m.pref).push(m);
  });
  const groups = order.map(pref => byPref.get(pref));
  groups.sort((a, b) => Math.max(...b.map(m => m.intensityRank)) - Math.max(...a.map(m => m.intensityRank)));
  return groups.slice(0, _EQ_MINI_MAX_FRAMES);
}

// SVG座標群を収める view (cx, cy, zoom) を計算する簡易 fit。
function _eqFitSvgView(svgPoints, fallbackView) {
  if (!svgPoints.length) return fallbackView;
  const xs = svgPoints.map(p => p[0]), ys = svgPoints.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const spanX = Math.max(60, maxX - minX + 140);
  const spanY = Math.max(60, maxY - minY + 140);
  const zoom = Math.max(1.4, Math.min(6, 900 / Math.max(spanX, spanY)));
  return { cx, cy, zoom };
}

function _eqEmptyDetailPlan(scrollMode, miniMapMode, eventId) {
  return {
    eventId: eventId || null, scrollMode, municipalities: [], miniMapMode, frames: [],
    frameIntervalMs: _EQ_MINI_FRAME_MS, scrollDurationMs: 0, holdMs: 0, truncated: false,
    missingCoordinateCount: 0, markerCount: 0, municipalCount: 0,
  };
}

/**
 * 現在対象の地震 (eqCur) について、市区町村震度詳細の表示計画を作る。
 * demo fallback はしない — eqCur (real/demo いずれも同じ形) が持つ points をそのまま正規化するだけ。
 */
function _buildEqDetailPlan(eqCur) {
  if (typeof LiveStreamEarthquakeDetail === 'undefined') {
    return _eqEmptyDetailPlan('unavailable', 'unavailable', eqCur.id);
  }
  if (LiveStreamEarthquakeDetail.getDictStatus() === 'loading') {
    return _eqEmptyDetailPlan('unavailable', 'unavailable', eqCur.id);
  }

  const built = LiveStreamEarthquakeDetail.build(eqCur);
  const municipalities = built.municipalities;

  if (municipalities.length === 0) {
    const plan = _eqEmptyDetailPlan('empty', 'empty', eqCur.id);
    plan.missingCoordinateCount = built.missingCoordinateCount;
    plan.markerCount = built.markerCount;
    return plan;
  }

  const rowCount = municipalities.length;
  let scrollMode, idealMs;
  if (rowCount <= _EQ_MUNI_VISIBLE_ROWS) { scrollMode = 'static'; idealMs = 0; }
  else { scrollMode = 'scrolling'; idealMs = rowCount * 1200; }
  const scrollDurationMs = Math.max(_EQ_MUNI_MIN_MS, Math.min(_EQ_MUNI_MAX_MS, idealMs || _EQ_MUNI_MIN_MS));

  const groups = _eqGroupMunicipalitiesByPref(municipalities);
  let miniMapMode, frames;
  if (groups.length === 0)      { miniMapMode = 'empty'; frames = []; }
  else if (groups.length === 1) { miniMapMode = 'fit';   frames = [groups[0]]; }
  else                          { miniMapMode = 'tour';  frames = groups; }

  const idealTourMs = frames.length * _EQ_MINI_FRAME_MS;
  const idealTotalMs = Math.max(idealMs, idealTourMs);
  const truncated = idealTotalMs > _EQ_MUNI_MAX_MS;
  const holdMs = (scrollMode === 'scrolling' || miniMapMode === 'tour')
    ? Math.max(scrollDurationMs, idealTourMs) : 0;

  return {
    eventId: eqCur.id, scrollMode, municipalities, miniMapMode, frames,
    frameIntervalMs: _EQ_MINI_FRAME_MS, scrollDurationMs, holdMs, truncated,
    missingCoordinateCount: built.missingCoordinateCount, markerCount: built.markerCount, municipalCount: built.municipalCount,
  };
}

function _renderEqMuniList(plan) {
  const panelEl = $s('eq-muni');
  if (!panelEl) return;
  const trackEl = $s('eq-muni-track');

  panelEl.hidden = false;
  panelEl.dataset.eqMuniScrollMode = plan.scrollMode;
  panelEl.dataset.eqMuniCount = String(plan.municipalCount);
  panelEl.dataset.eqMuniMarkerCount = String(plan.markerCount);
  panelEl.dataset.eqMuniMissingCount = String(plan.missingCoordinateCount);

  if (plan.scrollMode === 'empty' || plan.scrollMode === 'unavailable') {
    panelEl.style.removeProperty('--eq-muni-scroll-dur');
    const msg = plan.scrollMode === 'unavailable' ? '市区町村震度: 詳細取得中' : '市区町村震度: 詳細なし';
    if (trackEl) trackEl.innerHTML = `<div class="eq-muni-empty" data-testid="live-stream-earthquake-municipal-empty">${msg}</div>`;
    return;
  }

  const rowHtml = m => {
    const cls = _EQ_INTENSITY_CLASS[m.intensity] ? ` eq-muni-row--${_EQ_INTENSITY_CLASS[m.intensity]}` : '';
    const hasCoord = m.lat != null && m.lng != null;
    return `<div class="eq-muni-row${cls}" data-testid="live-stream-earthquake-municipal-row" data-intensity="${_eqEsc(m.intensity)}" data-pref="${_eqEsc(m.pref)}" data-city="${_eqEsc(m.city)}" data-has-coordinate="${hasCoord}">
      <span class="lv">${_eqEsc(m.intensity)}</span><span class="area">${_eqEsc(m.pref)} ${_eqEsc(m.city)}</span>
    </div>`;
  };

  if (plan.scrollMode === 'scrolling') {
    // ticker と同じ手法: 内容を2回連続で並べ、-50% までの translateY を無限ループさせるとシームレスに繋がる
    const rowsHtml = plan.municipalities.map(rowHtml).join('');
    if (trackEl) trackEl.innerHTML = rowsHtml + rowsHtml;
    panelEl.style.setProperty('--eq-muni-scroll-dur', (plan.scrollDurationMs / 1000) + 's');
  } else {
    if (trackEl) trackEl.innerHTML = plan.municipalities.map(rowHtml).join('');
    panelEl.style.removeProperty('--eq-muni-scroll-dur');
  }
}

// SVGフォールバック用マーカーオブジェクト (Leaflet未初期化時のみ使用)
function _eqMuniMarkerObjsSvg(list) {
  return (list || []).filter(m => m.lat != null && m.lng != null).map(m => {
    const [x, y] = _eqMuniLatLonToSvg(m.lat, m.lng);
    const color = _EQ_INTENSITY_COLOR[m.intensity] || '#9e9e9e';
    const clsSuffix = _EQ_INTENSITY_CLASS[m.intensity] || '0';
    return {
      x, y, r: 7, color, noRing: true,
      cls: `stream-eq-intensity-marker stream-eq-intensity-marker--${clsSuffix}`,
      attrs: ` data-testid="live-stream-earthquake-municipal-marker" data-intensity="${_eqEsc(m.intensity)}" data-pref="${_eqEsc(m.pref)}" data-city="${_eqEsc(m.city)}"`,
      label: _EQ_INTENSITY_LABEL[m.intensity] || m.intensity,
      fs: 11,
    };
  });
}

// Leaflet用マーカーオブジェクト (LiveStreamMapView#setIntensityMarkers() の入力形式)。
// frame内最大震度の地点は isActive=true にして少し強調する (指示書 A-2 「最大震度地点はやや強調してもよい」)。
function _eqMuniMarkerObjsLeaflet(list) {
  const filtered = (list || []).filter(m => m.lat != null && m.lng != null);
  const maxRank = filtered.length ? Math.max(...filtered.map(m => m.intensityRank)) : null;
  return filtered.map(m => ({
    lat: m.lat, lng: m.lng, intensity: m.intensity, pref: m.pref, city: m.city,
    clsSuffix: _EQ_INTENSITY_CLASS[m.intensity] || '0',
    label: _EQ_INTENSITY_LABEL[m.intensity] || m.intensity,
    isActive: maxRank != null && m.intensityRank === maxRank,
  }));
}

// 小地図に震源 + 市区町村震度マーカーを描く。
// Stream Phase 5-A bundle: Leaflet本番地図化 (_eqMiniMapView)。Leaflet未初期化/失敗時は
// Phase 5-A.1 時点のSVGモック小地図へフォールバックする (中央地図と同じフォールバック方針)。
// animated=true は初回表示時のみ (既存のズームイン演出); フレーム切替は即時カット (ちらつき防止)。
function _renderEqMiniMap(plan, eqCur, frameIndex, animated) {
  if (!eqCur) return;
  if (_eqMiniMapView && !_eqMiniMapView.failed) _renderEqMiniMapLeaflet(plan, eqCur, frameIndex, animated);
  else _renderEqMiniMapSvgFallback(plan, eqCur, frameIndex, animated);
}

function _renderEqMiniMapLeaflet(plan, eqCur, frameIndex, animated) {
  const el = $s('eq-map');
  if (!el) return;
  el.dataset.eqMiniMapMode = plan.miniMapMode;

  const hasEpicenter = eqCur.lat != null && eqCur.lon != null && isFinite(eqCur.lat) && isFinite(eqCur.lon);
  if (hasEpicenter) {
    // 第2引数 (activeEventId) は「地図全体の自動巡回フォーカス」と一致した場合のみ強調する比較対象であり、
    // ここでは意図的に null を渡す (震源マーカー自体は常時同じ強調表示のままでよく、
    // 誤って常時 data-active=true になっていた回帰を修正: Phase 5-A.1 のSVG版に合わせ非アクティブ扱いにする)。
    _eqMiniMapView.setPulses(
      [{ id: eqCur.id, category: 'earthquake', lat: eqCur.lat, lon: eqCur.lon, label: eqCur.s, testid: 'live-stream-earthquake-epicenter-marker' }],
      null
    );
  } else {
    _eqMiniMapView.clearPulses();
  }

  if (plan.miniMapMode === 'empty' || plan.miniMapMode === 'unavailable') {
    el.dataset.eqMiniMapFrameIndex = '0';
    el.dataset.eqMiniMapFrameTotal = '0';
    _eqMiniMapView.clearIntensityMarkers();
    if (hasEpicenter) _eqMiniMapView.fitTo([[eqCur.lat, eqCur.lon]], { animate: animated, singleZoom: 7 });
    else _eqMiniMapView.fitJapan(animated);
    return;
  }

  const frames = plan.frames;
  const idx = Math.max(0, Math.min(frameIndex, frames.length - 1));
  const frameGroup = frames[idx] || [];
  _eqMiniMapView.setIntensityMarkers(_eqMuniMarkerObjsLeaflet(frameGroup));

  el.dataset.eqMiniMapFrameIndex = String(idx + 1);
  el.dataset.eqMiniMapFrameTotal = String(frames.length);

  const points = frameGroup.filter(m => m.lat != null && m.lng != null).map(m => [m.lat, m.lng]);
  if (hasEpicenter) points.push([eqCur.lat, eqCur.lon]);
  if (points.length > 0) _eqMiniMapView.fitTo(points, { animate: animated, padding: [24, 24], maxZoom: 9 });
  else if (hasEpicenter) _eqMiniMapView.fitTo([[eqCur.lat, eqCur.lon]], { animate: animated, singleZoom: 7 });
}

// Phase 5-A.1 時点のSVGモック小地図描画 (Leaflet未初期化/失敗時のフォールバックとしてのみ残す)。
function _renderEqMiniMapSvgFallback(plan, eqCur, frameIndex, animated) {
  const el = $s('eq-map');
  if (!el) return;

  const epicenterMarker = { x: eqCur.at[0], y: eqCur.at[1], color: 'var(--c-eq)', r: eqCur.r || 15, label: eqCur.s, fs: 19 };
  const fallbackView = { zoom: 3.2, cx: eqCur.at[0], cy: eqCur.at[1] };

  el.dataset.eqMiniMapMode = plan.miniMapMode;

  if (plan.miniMapMode === 'empty' || plan.miniMapMode === 'unavailable') {
    el.dataset.eqMiniMapFrameIndex = '0';
    el.dataset.eqMiniMapFrameTotal = '0';
    if (animated) zoomToTarget(el, fallbackView, { markers: [epicenterMarker] });
    else renderMap(el, { view: fallbackView, markers: [epicenterMarker], graticule: true });
    return;
  }

  const frames = plan.frames;
  const idx = Math.max(0, Math.min(frameIndex, frames.length - 1));
  const frameGroup = frames[idx] || [];
  const svgPoints = frameGroup.filter(m => m.lat != null && m.lng != null).map(m => _eqMuniLatLonToSvg(m.lat, m.lng));
  svgPoints.push(eqCur.at); // 震源も常に視野に含める
  const view = _eqFitSvgView(svgPoints, fallbackView);
  const markers = [epicenterMarker].concat(_eqMuniMarkerObjsSvg(frameGroup));

  el.dataset.eqMiniMapFrameIndex = String(idx + 1);
  el.dataset.eqMiniMapFrameTotal = String(frames.length);

  if (animated) zoomToTarget(el, view, { markers, graticule: true });
  else renderMap(el, { view, markers, graticule: true });
}

// eq 子画面の詳細表示 (list + mini-map) を非表示・初期状態へ戻す (対象なし / 取得エラー / calm 時)。
function _clearEqDetail() {
  if (_eqDetailActiveId !== null && typeof LiveStreamFocusController !== 'undefined') {
    LiveStreamFocusController.releaseHold('earthquake-detail');
  }
  _eqDetailActiveId = null;
  _eqDetailPlan = null;
  _eqDetailEqCurRef = null;
  _eqDetailFrameIndex = 0;
  _eqDetailFrameElapsedMs = 0;
  const panelEl = $s('eq-muni');
  if (panelEl) {
    panelEl.hidden = true;
    panelEl.dataset.eqMuniScrollMode = '';
    panelEl.dataset.eqMuniCount = '0';
    panelEl.dataset.eqMuniMarkerCount = '0';
    panelEl.dataset.eqMuniMissingCount = '0';
    panelEl.style.removeProperty('--eq-muni-scroll-dur');
    const trackEl = $s('eq-muni-track');
    if (trackEl) trackEl.innerHTML = '';
  }
  const el = $s('eq-map');
  if (el) {
    el.dataset.eqMiniMapMode = 'empty';
    el.dataset.eqMiniMapFrameIndex = '0';
    el.dataset.eqMiniMapFrameTotal = '0';
  }
  const sectionEl = document.querySelector('[data-testid="live-stream-panel-earthquake"]');
  if (sectionEl) sectionEl.dataset.earthquakeDetailId = '';
  _pushEqDetailDiagnostics();
}

// 現在対象の eqCur が変わった (id変化) 場合のみ list/mini-map/hold を作り直す。
// id が同じ限り、rain/rail/tide 側のfetch完了等による再描画では list のスクロール/tour を中断しない。
function _syncEqDetail(eqCur) {
  _eqDetailEqCurRef = eqCur;
  if (eqCur.id === _eqDetailActiveId) return; // 既存 plan のまま (scroll/tour継続)

  // 座標辞書ロード中は「詳細取得中」を暫定表示するだけに留め、_eqDetailActiveId は確定させない。
  // (確定させてしまうと、同一 event が長時間対象のままの実運用で、辞書ロード完了後も
  //  id が変わらない限り再構築のきっかけが無く「詳細取得中」のまま固まってしまう。
  //  _eqDetailTick が毎秒 _eqDetailActiveId !== _eqDetailEqCurRef.id を見て再試行する。)
  if (typeof LiveStreamEarthquakeDetail !== 'undefined' && LiveStreamEarthquakeDetail.getDictStatus() === 'loading') {
    const transientPlan = _eqEmptyDetailPlan('unavailable', 'unavailable', eqCur.id);
    _eqDetailPlan = transientPlan;
    const loadingSectionEl = document.querySelector('[data-testid="live-stream-panel-earthquake"]');
    if (loadingSectionEl) loadingSectionEl.dataset.earthquakeDetailId = eqCur.id || '';
    _renderEqMuniList(transientPlan);
    _renderEqMiniMap(transientPlan, eqCur, 0, true);
    _pushEqDetailDiagnostics();
    return;
  }

  const plan = _buildEqDetailPlan(eqCur);
  _eqDetailActiveId = eqCur.id;
  _eqDetailPlan = plan;
  _eqDetailFrameIndex = 0;
  _eqDetailFrameElapsedMs = 0;
  _eqDetailListStartedAt = Date.now();

  const sectionEl = document.querySelector('[data-testid="live-stream-panel-earthquake"]');
  if (sectionEl) sectionEl.dataset.earthquakeDetailId = eqCur.id || '';

  _renderEqMuniList(plan);
  _renderEqMiniMap(plan, eqCur, 0, true);

  if (plan.holdMs > 0 && typeof LiveStreamFocusController !== 'undefined') {
    LiveStreamFocusController.requestHold({ source: 'earthquake-detail', eventId: eqCur.id, durationMs: plan.holdMs });
  }
  _pushEqDetailDiagnostics();
}

function _pushEqDetailDiagnostics() {
  if (typeof LiveStreamRuntime === 'undefined' || !LiveStreamRuntime.setEarthquakeDetailDiagnostics) return;
  const plan = _eqDetailPlan;
  if (!plan) { LiveStreamRuntime.setEarthquakeDetailDiagnostics(null); return; }
  const scrollProgress = plan.scrollMode === 'scrolling' && plan.scrollDurationMs > 0
    ? Math.max(0, Math.min(1, (Date.now() - _eqDetailListStartedAt) / plan.scrollDurationMs))
    : (plan.scrollMode === 'static' ? 1 : 0);
  const holdActive = !!(typeof LiveStreamFocusController !== 'undefined' && LiveStreamFocusController.getHold
    && LiveStreamFocusController.getHold('earthquake-detail'));

  // Stream Phase 5-A bundle: 指示書提案の語彙 (detailStatus/listScrollState/mapTourState 等) も
  // 追加公開する。Phase 5-A.1 の既存フィールド名 (scrollMode/miniMapMode 等) は後方互換のため残す。
  const detailStatus = (plan.scrollMode === 'unavailable') ? 'loading'
    : (plan.scrollMode === 'empty') ? 'empty' : 'ready';
  const listScrollState = (plan.scrollMode !== 'scrolling') ? 'idle'
    : (scrollProgress >= 1 ? 'done' : 'running');
  const frameTotal = plan.frames.length;
  const mapTourState = (plan.miniMapMode !== 'tour') ? 'done'
    : (_eqDetailFrameIndex >= frameTotal - 1 ? 'done' : 'running');

  LiveStreamRuntime.setEarthquakeDetailDiagnostics({
    activeEventId: plan.eventId,
    municipalCount: plan.municipalCount,
    markerCount: plan.markerCount,
    missingCoordinateCount: plan.missingCoordinateCount,
    scrollMode: plan.scrollMode,
    scrollProgress,
    miniMapMode: plan.miniMapMode,
    miniMapFrameIndex: _eqDetailFrameIndex + 1,
    miniMapFrameTotal: frameTotal,
    truncated: plan.truncated,
    holdActive,
    // 指示書 A-6 提案の語彙
    activeEarthquakeId: plan.eventId,
    detailStatus,
    intensityCount: plan.municipalCount,
    listScrollState,
    mapTourState,
    mapTourFrameIndex: _eqDetailFrameIndex + 1,
    mapTourFrameCount: frameTotal,
    holdReason: holdActive ? 'earthquake-detail-tour' : null,
  });
}

// 小地図 tour のフレーム送り専用の 1 秒ティッカー。main.js の 8秒サイクル render() ゲートとは
// 独立させ、tour/diagnostics の更新が rain/rail/tide 側の再描画頻度に引きずられないようにする。
// Stream Phase 5-A bundle: 鉄道詳細の scrollState (running→done) 更新もこの同じ1秒ティッカーに相乗りさせる
// (地震用・鉄道用で別々に setInterval を増やさない)。
// モジュール読み込み時に一度だけ起動する (多重起動しない)。
let _eqDetailTickTimer = null;
function _eqDetailTick() {
  // 座標辞書ロード完了待ちで確定できなかった場合の再試行 (最大1秒後)
  if (_eqDetailEqCurRef && _eqDetailActiveId !== _eqDetailEqCurRef.id) {
    _syncEqDetail(_eqDetailEqCurRef);
  }
  if (_eqDetailPlan && _eqDetailPlan.miniMapMode === 'tour' && _eqDetailEqCurRef) {
    _eqDetailFrameElapsedMs += 1000;
    if (_eqDetailFrameElapsedMs >= _eqDetailPlan.frameIntervalMs) {
      _eqDetailFrameElapsedMs = 0;
      if (_eqDetailFrameIndex < _eqDetailPlan.frames.length - 1) {
        _eqDetailFrameIndex += 1;
        _renderEqMiniMap(_eqDetailPlan, _eqDetailEqCurRef, _eqDetailFrameIndex, false);
      }
    }
  }
  _pushEqDetailDiagnostics();
  if (typeof _pushRailDetailDiagnostics === 'function' && _railDetailActiveId !== null) _pushRailDetailDiagnostics();
}
(function initEqDetailTicker() {
  if (_eqDetailTickTimer) return;
  _eqDetailTickTimer = setInterval(_eqDetailTick, 1000);
})();

/* ================================================================
   Stream Phase 5-A bundle B — 鉄道子画面 詳細表示 (自動巡回/focus中の1路線)
   地震子画面と異なり、鉄道子画面はカテゴリ内の複数路線を常時カード一覧で表示済みなので、
   ここで扱う「詳細」は「現在 focus 中の鉄道 event 1件」の全文説明 + 自動スクロールのみ。
   ローカルな巡回インデックス (eqI 相当) は不要 — グローバル focus と直結する。
   ================================================================ */

const _RAIL_DETAIL_MIN_MS = 6000;
const _RAIL_DETAIL_MAX_MS = 30000;
// 詳細本文がこの文字数を超えたら自動スクロール。#rail-detail-viewport の実測サイズ
// (313px高 ÷ 17.6px行高 ≈ 17行、189px幅で1行あたり約17文字 → 無スクロールで約280文字収まる)
// を元に設定 (旧値 70 は #rail-overlay の小さいポップアップ時代の名残で、実際の ODPT
// 障害説明文 (60〜150文字程度) のほとんどが不要にスクロール扱いとなり、自動巡回が
// 地震情報より大幅に長く hold されて「切り替わるまで時間がかかる」原因になっていた)。
const _RAIL_DETAIL_SCROLL_CHARS = 260;

// Stream Phase 6-G: 潮位小窓の8秒巡回ペア切替を検知するための直前 pairStart。
// tide-body の innerHTML は現在値 (cm) 更新のため毎秒作り直すが、スライド演出は
// ペアが実際に切り替わったタイミングでのみ発火させたい (毎秒アニメーションが
// 再生されると単調さの解消どころかチカチカして逆効果になるため)。
let _tidePairStart = -1;

let _railDetailActiveId = null;
let _railDetailScrollMode = 'idle'; // idle | static | scrolling
let _railDetailStartedAt = 0;
let _railDetailDurationMs = 0;
// Stream Phase 6-H: 小地図のズームは「対象1件の代表点へ固定ズーム」ではなく、現在の障害路線
// *全件* の実ジオメトリから統合 bounds を作って fitBounds する方式に変更 (東西に離れた複数路線が
// 同時に障害でも、事業者の代表点1点にしか寄れず他路線が画面外になっていた不具合の対応)。
let _railBoundsSig = null;      // 直近にfitした対象路線名集合のシグネチャ (再フィット要否判定)
let _railBoundsInFlight = null; // 問い合わせ中のシグネチャ (対象が変わったら古い結果は捨てる)
let _railFittedIds = [];        // 直近のfitに実際に含まれた対象路線の event id 一覧 (診断用)

function _railEsc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, ch =>
    ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
}

function _clearRailDetail() {
  if (_railDetailActiveId !== null && typeof LiveStreamFocusController !== 'undefined') {
    LiveStreamFocusController.releaseHold('railway-detail');
  }
  _railDetailActiveId = null;
  _railDetailScrollMode = 'idle';
  const el = $s('rail-overlay');
  if (el) { el.hidden = true; el.innerHTML = ''; }
  const detailEl = $s('rail-detail');
  if (detailEl) {
    detailEl.hidden = true;
    detailEl.dataset.railwayDetailScrollMode = '';
    detailEl.style.removeProperty('--rail-detail-scroll-dur');
    const trackEl = $s('rail-detail-track');
    if (trackEl) trackEl.innerHTML = '';
  }
  const sectionEl = document.querySelector('[data-testid="live-stream-panel-rail"]');
  if (sectionEl) sectionEl.dataset.railwayDetailId = '';
  // 小地図のズームアウトは _syncRailMiniMapZoom() が render() 側で一元管理する (Stream Phase 6-E)。
  _pushRailDetailDiagnostics();
}

// line.id が変わったときだけ DOM/hold/ズームを作り直す (対象が同じ限り自動スクロールを中断しない)。
function _renderRailDetail(line) {
  const el = $s('rail-overlay');
  const detailEl = $s('rail-detail');
  if (!el || !detailEl) return;
  el.hidden = false;
  detailEl.hidden = false;
  if (line.id === _railDetailActiveId) { _pushRailDetailDiagnostics(); return; }

  _railDetailActiveId = line.id;
  _railDetailStartedAt = Date.now();

  const desc = line.description || '';
  const hasDesc = desc.trim().length > 0;
  _railDetailScrollMode = hasDesc && desc.length > _RAIL_DETAIL_SCROLL_CHARS ? 'scrolling' : 'static';
  _railDetailDurationMs = _railDetailScrollMode === 'scrolling'
    ? Math.max(_RAIL_DETAIL_MIN_MS, Math.min(_RAIL_DETAIL_MAX_MS, desc.length * 150))
    : 0;

  const sectionEl = document.querySelector('[data-testid="live-stream-panel-rail"]');
  if (sectionEl) sectionEl.dataset.railwayDetailId = line.id || '';

  // ---- 概要ポップアップ (#rail-overlay): 路線名・状態・事業者・更新時刻のみの短い固定表示 ----
  el.innerHTML = `<div class="popup popup--rail-detail zoomin" data-testid="live-stream-railway-detail" data-event-id="${line.id || ''}">
    <div class="rd-head">
      <span class="rd-name" data-testid="live-stream-railway-detail-name">${_railEsc(line.name)}</span>
      <span class="rd-status" style="background:${line.stColor}" data-testid="live-stream-railway-detail-status">${_railEsc(line.status)}</span>
    </div>
    <div class="rd-meta">
      <span data-testid="live-stream-railway-detail-operator">${line.operator ? _railEsc(line.operator) : '事業者不明'}</span>
      <span data-testid="live-stream-railway-detail-updated">${line.updatedAt ? '更新 ' + _railEsc(line.updatedAt) : '更新時刻不明'}</span>
    </div>
    <div class="rd-note" data-testid="live-stream-railway-detail-note">詳細は左のリストへ ↓</div>
  </div>`;

  // ---- 詳細本文 (#rail-detail): 未取得情報は非断定表示にする (影響区間/原因の個別フィールドが
  // backend に無いため、description 全文をそのまま「詳細本文」として表示する。
  // 空の場合のみ「詳細未取得」と明示する)。地震子画面の #eq-muni と同じ手法で、
  // 長文のときだけ内容を2回連続で並べ -50%までのtranslateYを無限ループさせる。 ----
  const bodyText = hasDesc ? _railEsc(desc) : '詳細未取得';
  const sourceLine = line.source ? `\n\n出典: ${_railEsc(line.source)}` : '';
  const fullText = bodyText + sourceLine;
  const trackEl = $s('rail-detail-track');
  if (trackEl) {
    trackEl.innerHTML = _railDetailScrollMode === 'scrolling'
      ? `<div class="rail-detail-copy" data-testid="live-stream-railway-detail-body">${fullText}</div>
         <div class="rail-detail-copy" aria-hidden="true">${fullText}</div>`
      : `<div class="rail-detail-copy" data-testid="live-stream-railway-detail-body">${fullText}</div>`;
  }
  detailEl.dataset.railwayDetailScrollMode = _railDetailScrollMode;
  if (_railDetailScrollMode === 'scrolling') {
    detailEl.style.setProperty('--rail-detail-scroll-dur', (_railDetailDurationMs / 1000) + 's');
  } else {
    detailEl.style.removeProperty('--rail-detail-scroll-dur');
  }

  if (_railDetailScrollMode === 'scrolling' && typeof LiveStreamFocusController !== 'undefined') {
    LiveStreamFocusController.requestHold({ source: 'railway-detail', eventId: line.id, durationMs: _railDetailDurationMs });
  }

  // 小地図のズームインは _syncRailMiniMapZoom() が render() 側で一元管理する (Stream Phase 6-E)。
  _pushRailDetailDiagnostics();
}

// Stream Phase 6-H: 小地図のズーム対象を、対象路線の表示 (_renderRailDetail/_clearRailDetail) と
// 切り離して一元管理する。render() から毎 tick 無条件に呼ばれるが、実際に fit し直すのは
// 「現在の障害路線名の集合」が前回と変わったときだけ (_railBoundsSig による signature 比較)。
//
// 以前は「巡回中の1路線の代表点 (事業者代表点。無ければ東京駅の汎用フォールバック) へ固定ズーム
// (zoom 12)」だったため、東西に離れた複数路線が同時に障害でも、常に同じ代表点 (例: 東京メトロの
// 路線なら全部同じ1点) にしか寄れず、他の路線は画面外だった。LiveStreamRailwayLayer.getBoundsForNames()
// で障害路線 *全件* の実ジオメトリ (GeoJSON LineString) から統合 bounds を作り、それに fitBounds する。
// 実ジオメトリが1件も見つからない (名称不一致等) ときのみ、代表点群からの bounds へフォールバックする。
//
// Stream Phase 6-F: flyTo アニメーション (requestAnimationFrame駆動) は、OBS配信用の streamer
// コンテナ (ヘッドレスChromium・非フォーカスのタブ) やバックグラウンドタブ化したブラウザで rAF が
// スロットリングされ、ズーム値が中途半端な値のまま固まることが実機確認で判明した。この小地図は
// 配信HUDの一情報源であり滑らかなカメラワークは必須ではないため、常に animate:false で即座に適用する。
async function _syncRailMiniMapZoom(affectedLines) {
  if (!_railMiniMapView || _railMiniMapView.failed || !_railMiniMapView.map) return;
  const lines = affectedLines || [];
  const names = [...new Set(lines.map(l => l.name).filter(Boolean))].sort();
  const sig = names.join('|');
  if (sig === _railBoundsSig || sig === _railBoundsInFlight) return;
  _railBoundsInFlight = sig;

  if (names.length === 0) {
    _railBoundsInFlight = null;
    _railBoundsSig = sig;
    _railFittedIds = [];
    _railMiniMapView.fitTo(STREAM_RAILWAY_DEFAULT_BOUNDS, { animate: false });
    return;
  }

  const bounds = (typeof LiveStreamRailwayLayer !== 'undefined' && LiveStreamRailwayLayer.getBoundsForNames)
    ? await LiveStreamRailwayLayer.getBoundsForNames(names)
    : null;

  // 問い合わせ中に対象集合が変わっていたら、この結果は古いので破棄する (最新の呼び出しに委ねる)。
  if (_railBoundsInFlight !== sig) return;
  _railBoundsInFlight = null;
  _railBoundsSig = sig;
  _railFittedIds = lines.map(l => l.id).filter(Boolean);

  if (bounds) {
    _railMiniMapView.fitTo([[bounds.south, bounds.west], [bounds.north, bounds.east]], {
      animate: false, padding: [24, 24], maxZoom: 13,
    });
  } else {
    const pts = lines
      .filter(l => l.lat != null && l.lng != null && isFinite(l.lat) && isFinite(l.lng))
      .map(l => [l.lat, l.lng]);
    if (pts.length > 0) {
      _railMiniMapView.fitTo(pts, { animate: false, padding: [24, 24], maxZoom: 13, singleZoom: 12 });
    } else {
      _railMiniMapView.fitTo(STREAM_RAILWAY_DEFAULT_BOUNDS, { animate: false });
    }
  }
}

function _pushRailDetailDiagnostics() {
  if (typeof LiveStreamRuntime === 'undefined' || !LiveStreamRuntime.setRailwayDetailDiagnostics) return;
  const holdActive = !!(typeof LiveStreamFocusController !== 'undefined' && LiveStreamFocusController.getHold
    && LiveStreamFocusController.getHold('railway-detail'));
  const scrollState = _railDetailScrollMode !== 'scrolling' ? 'idle'
    : (Date.now() - _railDetailStartedAt >= _railDetailDurationMs ? 'done' : 'running');
  LiveStreamRuntime.setRailwayDetailDiagnostics({
    activeRailwayEventId: _railDetailActiveId,
    detailStatus: _railDetailActiveId ? 'ready' : 'empty',
    hasScrollableDetail: _railDetailScrollMode === 'scrolling',
    scrollState,
    holdActive,
    holdReason: holdActive ? 'railway-detail-scroll' : null,
  });
}

/* ================================================================
   Stream Phase 3-D — 全体ステータス・カテゴリバッジ・パネル件数の同期
   すべて LiveStreamEventStore.getSummary() を単一参照元とする。
   ================================================================ */

const _STATUS_RANK = { calm: 0, watch: 1, high: 2, critical: 3 };

// ヘッダー表示上、rain+kikikuru を「豪雨」、tide+water を「潮位」として合算する。
function _combinedCategory(byType, types) {
  let count = 0, status = 'calm';
  types.forEach(t => {
    const b = (byType && byType[t]) || { count: 0, status: 'calm' };
    count += b.count;
    if ((_STATUS_RANK[b.status] || 0) > (_STATUS_RANK[status] || 0)) status = b.status;
  });
  return { count, status };
}

// カテゴリバッジ (#ct-*) の数値と data-count/data-status を同時に更新する。
// fetchStatusError=true (該当カテゴリが取得失敗中) の場合は '-' 表示とし、平常/0件と誤認させない。
function _renderCategoryBadge(selector, numEl, combined, fetchStatusError) {
  const badgeEl = document.querySelector(selector);
  if (fetchStatusError) {
    if (numEl) numEl.textContent = '-';
    if (badgeEl) { badgeEl.dataset.count = ''; badgeEl.dataset.status = 'error'; }
    return;
  }
  if (numEl) numEl.textContent = String(combined.count);
  if (badgeEl) { badgeEl.dataset.count = String(combined.count); badgeEl.dataset.status = combined.status; }
}

// Stream Phase 4-A/4-B: パネル項目が自動巡回の注目 event と一致する場合の class/属性文字列を返す。
function _activeMarkup(itemId, activeEventId) {
  if (!activeEventId || !itemId || itemId !== activeEventId) return { cls: '', attr: '' };
  return { cls: ' stream-panel-item--active', attr: ' data-active="true" data-focused="true"' };
}

// パネル右上 (data-panel="...") へ EventStore 由来の件数・状態を付与する (表示テキストは既存のまま維持)。
function _annotatePanel(testid, combined, fetchStatusError) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (!el) return;
  if (fetchStatusError) {
    el.dataset.count = '';
    el.dataset.status = 'error';
    return;
  }
  el.dataset.count = String(combined.count);
  el.dataset.status = combined.status;
}

/**
 * render(scene, tick, mapEvents)
 * @param {object} scene
 * @param {number} tick
 * @param {Array|null} mapEvents  Stream Phase 3-B 本番データイベント (StreamMapEvents.build() の出力)。
 *   null の場合は demo/calm モードとして扱い、従来の scene ベース demo パルスを中央マップに表示する。
 *   配列 (0件含む) の場合は本番データモードとして扱い、demo パルスは一切表示しない。
 */
function render(scene, tick, mapEvents) {
  const eq   = scene.earthquake;
  const rain  = scene.rain;
  const rail  = scene.rail;
  const tide  = scene.tide;
  const tideAlerts = tide.stations.filter(s => s.alert);
  const eqOn   = eq.targets.length > 0;
  const rainOn  = rain.targets.length > 0;
  const railOn  = rail.affected.length > 0;
  const tideOn  = tideAlerts.length > 0;

  // Stream Phase 4-A: 自動巡回コントローラが選んだ注目 event id。地図/パネル/テロップ/HUDで共有する。
  // demo/calm の小窓地図・ポップアップは 1カテゴリ1件のみ表示するため (Stream Phase 3-A の互換維持)、
  // focus 対象がそのカテゴリの「現在の巡回中でない」targetを指す場合は表示自体を追従させる。
  // これをやらないと、focus が示す id の marker/panel item が地図・パネル上に一つも存在しなくなる
  // (Stream Phase 4-B 検証で判明: kikikuru-愛知県 東部-land 等、8秒巡回で表示されていない対象への
  //  focus 時に active marker/panel item が消失するバグ)。
  const focusState = (typeof LiveStreamFocusController !== 'undefined') ? LiveStreamFocusController.getState() : null;
  const activeEventId = focusState ? focusState.activeEventId : null;

  // 8秒サイクルで巡回するインデックス (focus 対象がこのカテゴリ内にあれば、そちらを優先表示する)
  const cyc   = Math.floor(tick / 8);
  const focusedEqIdx   = activeEventId && eqOn   ? eq.targets.findIndex(t => t.id === activeEventId)   : -1;
  const focusedRainIdx = activeEventId && rainOn ? rain.targets.findIndex(t => t.id === activeEventId) : -1;
  // Stream Phase 5-A.1: 市区町村震度リストの自動スクロール/小地図巡回が完了するまで、地震子画面
  // 自身の8秒巡回 (eqI) が対象を切り替えてしまわないよう、hold中は対象 event の index に固定する。
  // (LiveStreamFocusController の hold はカテゴリ横断の自動巡回のみを止めるため、この画面ローカルな
  //  8秒巡回は別途ここで止める必要がある)
  // Stream Phase 5-A bundle: 鉄道詳細 (railway-detail) も同じ hold 機構を使うようになったため、
  // getState().holdSource (代表1件) ではなく getHold('earthquake-detail') で自分の source だけを見る。
  const eqHold = (typeof LiveStreamFocusController !== 'undefined' && LiveStreamFocusController.getHold)
    ? LiveStreamFocusController.getHold('earthquake-detail') : null;
  const eqHoldEventId = eqHold ? eqHold.eventId : null;
  const heldEqIdx = eqHoldEventId && eqOn ? eq.targets.findIndex(t => t.id === eqHoldEventId) : -1;
  const eqI   = eqOn   ? (heldEqIdx >= 0 ? heldEqIdx : (focusedEqIdx >= 0 ? focusedEqIdx : cyc % eq.targets.length)) : 0;
  const rainI  = rainOn  ? (focusedRainIdx >= 0 ? focusedRainIdx : cyc % rain.targets.length) : 0;
  const eqCur  = eq.targets[eqI];
  const rainCur = rain.targets[rainI];
  const focusedRailIdx = activeEventId && railOn ? rail.affected.findIndex(a => a.id === activeEventId) : -1;
  // Stream Phase 6-D: 鉄道子画面にも地震/豪雨と同じ「グローバルfocusが無ければ自身の8秒巡回で
  // 全件を順番に見せる」フォールバックを追加する。以前は focusedRailIdx が無い場合 index 0 固定
  // だったため、グローバル自動巡回の候補上限 (LiveStreamFocusPolicy) に乗れなかった路線は
  // ポップアップ・ズームインが永久に表示されないバグがあった。
  const railHold = (typeof LiveStreamFocusController !== 'undefined' && LiveStreamFocusController.getHold)
    ? LiveStreamFocusController.getHold('railway-detail') : null;
  const railHoldEventId = railHold ? railHold.eventId : null;
  const heldRailIdx = railHoldEventId && railOn ? rail.affected.findIndex(a => a.id === railHoldEventId) : -1;
  const railI = railOn && rail.affected.length > 0
    ? (heldRailIdx >= 0 ? heldRailIdx : (focusedRailIdx >= 0 ? focusedRailIdx : cyc % rail.affected.length))
    : -1;
  const railPulseSource = railOn ? rail.affected[railI >= 0 ? railI : 0] : null;
  // Stream Phase 5-A bundle B / 6-D: 鉄道 event 1件の詳細表示。グローバル自動巡回が鉄道に
  // focus していればそれを優先し、していなければ railI (自身の8秒巡回) が指す対象を表示する
  // (地震/豪雨と同じ「対象が無ければ自分で全件を順番に見せる」方式。これにより自動巡回の
  // 候補上限に乗れなかった路線も、いずれ必ずポップアップ・ズームインの対象になる)。
  const focusedRailLine = (rail.status !== 'error' && railOn && railI >= 0)
    ? rail.affected[railI] : null;
  // Stream Phase 6-H: 小地図のズームは「巡回中の1路線」ではなく「現在の障害路線 *全件*」を
  // 対象に統合 bounds を作る (東西に離れた複数路線が同時に画面内へ収まるようにするため)。
  // 診断情報 (setRailwayMiniMapDiagnostics) のスナップショットより前に呼ぶ必要がある —
  // 後段で呼ぶと診断値が1描画パス分古いままになる (Stream Phase 6-E で判明した順序制約)。
  _syncRailMiniMapZoom(rail.status !== 'error' && railOn ? rail.affected : []);

  /* ---- ヘッダー件数・カテゴリバッジ・全体ステータス (Stream Phase 3-D: EventStore summary が単一参照元) ---- */
  const summary = (typeof LiveStreamEventStore !== 'undefined') ? LiveStreamEventStore.getSummary() : null;
  const byType = (summary && summary.byType) || {};
  const eqCombined   = byType.earthquake || { count: 0, status: 'calm' };
  const rainCombined = _combinedCategory(byType, ['rain', 'kikikuru']);
  const railCombined = byType.railway || { count: 0, status: 'calm' };
  const tideCombined = _combinedCategory(byType, ['tide', 'water']);

  _renderCategoryBadge('.cbadge--eq',   $s('ct-eq'),   eqCombined,   eq.status   === 'error');
  _renderCategoryBadge('.cbadge--rain', $s('ct-rain'), rainCombined, rain.status === 'error');
  _renderCategoryBadge('.cbadge--rail', $s('ct-rail'), railCombined, rail.status === 'error');
  _renderCategoryBadge('.cbadge--tide', $s('ct-tide'), tideCombined, tide.status === 'error');

  _annotatePanel('live-stream-panel-earthquake', eqCombined,   eq.status   === 'error');
  _annotatePanel('live-stream-panel-rain',       rainCombined, rain.status === 'error');
  _annotatePanel('live-stream-panel-rail',       railCombined, rail.status === 'error');
  _annotatePanel('live-stream-panel-tide',       tideCombined, tide.status === 'error');

  // 全体ステータス: EventStore.overallStatus を単一参照元とし、地図/バッジ/オーバーレイ間で矛盾させない。
  // 既存 CSS/E2E が calm/high の2値のみ対応のため data-lv はその語彙を維持しつつ、
  // dataState='unavailable' (全カテゴリ取得失敗) は calm と誤表示しないよう専用文言・data属性を分ける。
  const overallStatus = summary ? summary.overallStatus : (eqOn || rainOn || railOn || tideOn ? 'alert' : 'calm');
  const dataState = summary ? summary.dataState : 'empty';
  const calm = overallStatus === 'calm';
  let levelText;
  if (dataState === 'unavailable') levelText = '取得確認中';
  else if (dataState === 'partial') levelText = '一部取得確認中';
  else if (calm) levelText = '平常 · 監視中';
  else if (overallStatus === 'watch') levelText = '注意監視';
  else levelText = '警戒レベル 高';
  $s('level').dataset.streamOverallStatus = overallStatus;
  document.body.dataset.streamStatus = calm ? 'calm' : 'high';

  /* ---- 中央マップ (Leaflet 本番地図。Leaflet 初期化失敗時は旧SVGモック地図へフォールバック) ---- */
  if (mapEvents) {
    // 本番データモード (Stream Phase 3-B): StreamMapEvents 正規化イベントのみ描画。demoパルスは出さない。
    if (_centerMapView) {
      _centerMapView.setEvents(mapEvents, activeEventId);
      _centerMapView.clearPulses();
    } else {
      const cm = mapEvents.map(e => {
        const [x, y] = _fallbackLatLonToSvg(e.lat, e.lng);
        return { x, y, color: 'var(--c-eq)', r: 7, label: '', testid: `live-stream-map-event-${e.type}` };
      });
      renderMap($s('center-map'), {view:FULL_VIEW, markers:cm, graticule:true});
    }
  } else {
    // demo / calm モード (Stream Phase 3-A 挙動を維持)
    // id は scene 側 (adapter/demoデータ) が持つ値をそのまま使う。パネル側の data-event-id と
    // 同じ値になるため、地図とパネルで同一 event が同一 id で同期していることを検証できる (Stream Phase 3-C)。
    const pulses = [];
    if (eqOn)   pulses.push({id:eqCur.id,   category:'earthquake', lat:eqCur.lat,   lon:eqCur.lon,   label:eqCur.s, testid:'live-stream-pulse-earthquake'});
    if (rainOn) pulses.push({id:rainCur.id, category:'rain',       lat:rainCur.lat, lon:rainCur.lon, testid:'live-stream-pulse-rain'});
    if (railOn) pulses.push({id:railPulseSource && railPulseSource.id, category:'rail', lat:RAIL_PULSE_LATLON[0], lon:RAIL_PULSE_LATLON[1], testid:'live-stream-pulse-rail'});  // ポップアップ無し・路線別緯度経度なしのため代表地点固定 (focus対象があればそちらのidを使う)
    tideAlerts.forEach(s => pulses.push({id:`tide-${s.name}`, category:'tide', lat:s.lat, lon:s.lon, testid:'live-stream-pulse-tide'}));

    if (_centerMapView) {
      _centerMapView.setPulses(pulses, activeEventId);
      _centerMapView.clearEvents();
    } else {
      const cm = [], cr = [];
      if (eqOn)   cm.push({x:eqCur.at[0],   y:eqCur.at[1],   color:'var(--c-eq)',     r:(eqCur.r||12)-2, label:eqCur.s,   fs:16, testid:'live-stream-pulse-earthquake'});
      if (rainOn) {
        cm.push({x:rainCur.at[0], y:rainCur.at[1], color:'var(--c-rain-2)', r:9, label:'', testid:'live-stream-pulse-rain'});
        rainCur.cells.forEach(c => cr.push(c));
      }
      if (railOn) cm.push({x:545, y:476, color:'var(--c-rail)', r:8, label:'', testid:'live-stream-pulse-rail'});
      tideAlerts.forEach(s => cm.push({x:s.at[0], y:s.at[1], color:'var(--c-tide-2)', r:8, label:'', testid:'live-stream-pulse-tide'}));
      renderMap($s('center-map'), {view:FULL_VIEW, markers:cm, rain:cr, graticule:true});
    }
  }
  $s('center-overlay').innerHTML = calm
    ? `<div class="center-empty"><div class="ring"><div></div></div><div class="m">現在、表示対象なし</div><div class="s">ALL CLEAR · 全国の警戒情報を監視中</div></div>`
    : '';
  $s('level').dataset.lv    = calm ? 'calm' : 'high';
  $s('level-text').textContent = levelText;

  /* ---- 地震小窓 ---- */
  if (eq.status === 'error') {
    $s('eq-meta').innerHTML = `<span class="quiet" data-testid="live-stream-earthquake-status">一時的に取得不可</span>`;
  } else if (eqOn) {
    $s('eq-meta').innerHTML = eq.targets.length > 1
      ? `<span data-testid="live-stream-earthquake-status">対象 ${eqI+1}/${eq.targets.length}</span><span class="cyc"></span><span class="cyc-note">8s切替</span>`
      : `<span data-testid="live-stream-earthquake-status">対象 1/1</span>`;
  } else {
    $s('eq-meta').innerHTML = `<span class="quiet" data-testid="live-stream-earthquake-status">監視中</span>`;
  }
  $s('eq-history').innerHTML = eq.history.map(e =>
    `<div class="row" data-testid="live-stream-earthquake-history-item"><span class="tm">${e.t}</span><span class="nm">${e.p}</span><span class="mag">${e.m}</span><span class="chip" style="background:${e.c}">${e.s}</span></div>`
  ).join('');
  if (eqOn) {
    // Stream Phase 5-A.1: 市区町村震度リスト/小地図マーカーは eqCur.id が変わったときだけ作り直す
    // (毎 render() で呼んでも中断しない。scroll/tour の途中状態は _eqDetailTick 側が保持する)。
    _syncEqDetail(eqCur);
    const depthLine = eqCur.depth ? `<div class="l">深さ ${eqCur.depth}</div>` : '';
    const tsunamiLine = eqCur.tsunami ? `<div class="l">津波: ${eqCur.tsunami}</div>` : '';
    const eqActive = _activeMarkup(eqCur.id, activeEventId);
    $s('eq-overlay').innerHTML =
      `<div class="popup popup--eq zoomin${eqActive.cls}" data-testid="live-stream-earthquake-popup" data-event-id="${eqCur.id || ''}"${eqActive.attr}>
        <div class="p" data-testid="live-stream-earthquake-active">${eqCur.p}</div>
        <div class="l">${eqCur.m} ・ 震度<b style="color:#fff;font-size:14px">${eqCur.s}</b> ・ ${eqCur.t}</div>
        ${depthLine}${tsunamiLine}
      </div>`;
  } else {
    if (_eqMiniMapView && !_eqMiniMapView.failed) {
      _eqMiniMapView.clearPulses();
      _eqMiniMapView.clearIntensityMarkers();
      _eqMiniMapView.fitJapan(false);
    } else {
      const eqMapEl = $s('eq-map');
      if (eqMapEl.__raf) { cancelAnimationFrame(eqMapEl.__raf); eqMapEl.__raf = null; }
      renderMap(eqMapEl, {view:FULL_VIEW, graticule:true});
    }
    $s('eq-overlay').innerHTML = `<div class="win-empty"><div class="m">現在 対象なし</div><div class="s">全国を監視中</div></div>`;
    _clearEqDetail();
  }

  /* ---- 豪雨小窓 ---- */
  if (rain.status === 'error') {
    $s('rain-meta').innerHTML = `<span class="quiet" data-testid="live-stream-rain-status">一時的に取得不可</span>`;
  } else if (rainOn) {
    $s('rain-meta').innerHTML = rain.targets.length > 1
      ? `<span data-testid="live-stream-rain-status">対象 ${rainI+1}/${rain.targets.length}</span><span class="cyc"></span><span class="cyc-note">8s切替</span>`
      : `<span data-testid="live-stream-rain-status">対象 1/1</span>`;
  } else {
    $s('rain-meta').innerHTML = `<span class="quiet" data-testid="live-stream-rain-status">監視中</span>`;
  }
  $s('rain-alerts').innerHTML = rain.alerts.map(a =>
    `<div class="row" data-testid="live-stream-rain-list-item"><span class="sq" style="background:${a.cl}"></span><span class="nm">${a.r}</span><span class="lv" style="background:${a.cl}">${a.lv}</span></div>`
  ).join('') || `<div style="font:10px var(--mono);color:#5d6878;padding-top:8px">発表なし</div>`;
  if (rainOn) {
    // Stream Phase 5-A.1: 小地図の本番Leaflet地図化 (地震子画面と同じ方針)。
    // 対象 id が変わったときだけ flyTo (animated) し、同じ対象のままの再描画では
    // pulse marker だけ更新してカメラは動かさない (無駄な flyTo 再発火を避ける)。
    if (_rainMiniMapView && !_rainMiniMapView.failed) {
      const hasLatLon = rainCur.lat != null && rainCur.lon != null && isFinite(rainCur.lat) && isFinite(rainCur.lon);
      if (hasLatLon) {
        _rainMiniMapView.setPulses(
          [{ id: rainCur.id, category: 'rain', lat: rainCur.lat, lon: rainCur.lon, testid: 'live-stream-rain-mini-pulse' }],
          null
        );
        if (rainCur.id !== _rainMiniMapActiveId) {
          _rainMiniMapActiveId = rainCur.id;
          _rainMiniMapView.focusOn(rainCur.lat, rainCur.lon, 8);
        }
      } else {
        _rainMiniMapView.clearPulses();
        _rainMiniMapActiveId = null;
      }
    } else {
      zoomToTarget(
        $s('rain-map'),
        {zoom:3.1, cx:rainCur.at[0], cy:rainCur.at[1]},
        {rain:rainCur.cells}
      );
    }
    const rainActive = _activeMarkup(rainCur.id, activeEventId);
    // Stream Phase 6-C: 同一地点で複数 hazard (土砂/浸水/洪水/豪雨) が該当する場合、
    // 従来は代表1件しか表示できず「何が危険なのか」が分からなかった。
    // rainCur.hazards (レベル降順、最低1件) を全件展開して表示する。
    const hazardLines = (rainCur.hazards && rainCur.hazards.length ? rainCur.hazards : [{
      label: rainCur.category || '土砂', level: rainCur.level, levelLabel: rainCur.lv, levelColor: rainCur.lvColor,
    }]).map(h => `<div class="l">${_eqEsc(h.label)}災害 ・ <b style="color:${h.levelColor}">${_eqEsc(h.levelLabel)}</b></div>`).join('');
    const updatedLine = rainCur.updatedAt
      ? `<div class="popup-note" data-testid="live-stream-rain-updated">更新 ${_eqEsc(rainCur.updatedAt)}</div>` : '';
    $s('rain-overlay').innerHTML =
      `<div class="popup popup--rain zoomin${rainActive.cls}" data-testid="live-stream-rain-popup" data-event-id="${rainCur.id || ''}"${rainActive.attr}>
        <div class="p" data-testid="live-stream-rain-active">${_eqEsc(rainCur.r)}</div>
        ${hazardLines}
        ${updatedLine}
      </div>`;
  } else {
    _rainMiniMapActiveId = null;
    if (_rainMiniMapView && !_rainMiniMapView.failed) {
      _rainMiniMapView.clearPulses();
      _rainMiniMapView.fitJapan(false);
    } else {
      const rainMapEl = $s('rain-map');
      if (rainMapEl.__raf) { cancelAnimationFrame(rainMapEl.__raf); rainMapEl.__raf = null; }
      renderMap(rainMapEl, {view:FULL_VIEW, graticule:true});
    }
    $s('rain-overlay').innerHTML = `<div class="win-empty"><div class="m">現在 対象なし</div><div class="s">全国を監視中</div></div>`;
  }

  /* ---- 鉄道小窓 (ポップアップなし・路線色カードのみ) ---- */
  {
    // Stream Phase 5-A.1 (railway calm map): 路線図表示は影響路線の有無に依存させない。
    // Leaflet+PMTiles (中央地図と同じ全国路線データ) が使えるときは、初期化時に一度 fixed bounds
    // (STREAM_RAILWAY_DEFAULT_BOUNDS) を適用しておく (「路線図を表示するか」と「影響路線を強調するか」
    // の分離)。強調は main.js → LiveStreamRailwayLayer.setAffectedEvents() が全登録インスタンスへ
    // 既に反映済み。対象1件へのズームイン/アウトは下の _renderRailDetail()/_clearRailDetail() が
    // focus対象の切替に応じて行う (Stream Phase 5-B)。
    // Leaflet 未初期化/失敗時のみ、旧SVGモック(4路線)へフォールバックする。
    if (!_railMiniMapView || _railMiniMapView.failed) {
      const affIds = new Set(rail.affected.map(a => a.mapId || a.id));
      const railGeom = RAIL_LINES_BASE.map(l => affIds.has(l.id)
        ? {points:l.points, color:l.color, w:l.id==='yamanote' ? 6 : 5, o:1}
        : {points:l.points, color:'#37445a', w:3, o:.55});
      renderMap($s('rail-map'), {view:{zoom:3.4, cx:552, cy:478}, rail:railGeom});
    }

    if (typeof LiveStreamRuntime !== 'undefined' && LiveStreamRuntime.setRailwayMiniMapDiagnostics) {
      const usingLeaflet = !!(_railMiniMapView && !_railMiniMapView.failed);
      const leafletMap = usingLeaflet ? _railMiniMapView.map : null;
      LiveStreamRuntime.setRailwayMiniMapDiagnostics({
        loaded: usingLeaflet ? LiveStreamRailwayLayer.isInstanceLoaded('rail-mini') : false,
        defaultBoundsApplied: usingLeaflet,
        routeCount: usingLeaflet && LiveStreamRailwayLayer.getKnownRouteCount ? LiveStreamRailwayLayer.getKnownRouteCount() : null,
        affectedCount: rail.status === 'error' ? 0 : rail.affected.length,
        highlightedCount: rail.status === 'error' ? 0 : rail.affected.length,
        // Stream Phase 5-B: 対象路線へのズームイン/アウト (fitTo) が実際に地図へ反映されたかを
        // E2E から確認できるようにする (現在の中心座標・ズームレベル)。
        // Stream Phase 6-H: 「1件の代表点への固定ズーム」から「障害路線 *全件* の統合bounds」へ
        // 変更したため、単一の zoomedEventId では表現しきれない。後方互換として、fit対象がちょうど
        // 1件のときだけ zoomedEventId にその id を入れる (0件/複数件は null)。fittedLineIds は
        // 直近の fit に含まれた全 event id (複数件でも全件を検証できるようにするための新フィールド)。
        zoomedEventId: _railFittedIds.length === 1 ? _railFittedIds[0] : null,
        fittedLineIds: _railFittedIds.slice(),
        zoom: leafletMap ? leafletMap.getZoom() : null,
        center: leafletMap ? { lat: leafletMap.getCenter().lat, lng: leafletMap.getCenter().lng } : null,
        lastError: null,
      });
    }

    if (rail.status === 'error') {
      $s('rail-meta').innerHTML = `<span class="quiet">一時的に取得不可</span>`;
      $s('rail-side').innerHTML = `<div class="rail-empty" data-testid="live-stream-rail-unavailable" style="color:#5d6878"><div class="m">一時的に取得不可</div><div class="s">鉄道情報を取得できません</div></div>`;
    } else if (railOn) {
      $s('rail-meta').innerHTML = rail.affected.length > 1
        ? `<span data-testid="live-stream-rail-target-status">対象 ${railI + 1}/${rail.affected.length}</span><span class="cyc"></span><span class="cyc-note">8s切替</span>`
        : `<span data-testid="live-stream-rail-target-status">影響 1路線</span>`;
      $s('rail-side').innerHTML = rail.affected.map(c => {
        const mapId   = c.mapId || c.id;
        const geo     = RAIL_LINES_BASE.find(g => g.id === mapId) || {};
        const barClr  = c.lineColor || geo.color || '#7888a0';
        const updLine = c.updatedAt ? `<span class="upd" style="font:9px var(--mono);color:#5d6878;margin-left:auto">${c.updatedAt}</span>` : '';
        const railActive = _activeMarkup(c.id, activeEventId);
        return `<div class="rail-card${railActive.cls}" data-testid="live-stream-rail-list-item" data-event-id="${c.id || ''}"${railActive.attr}>
           <span class="bar" style="background:${barClr}"></span>
           <div class="body">
             <div class="nm" data-testid="live-stream-rail-line-name">${c.name}</div>
             <div class="note" data-testid="live-stream-rail-section">${c.note}</div>
           </div>
           <span class="st" style="background:${c.stColor}" data-testid="live-stream-rail-status">${c.status}</span>
           ${updLine}
         </div>`;
      }).join('');
    } else {
      $s('rail-meta').innerHTML = `<span class="quiet" style="color:#7ee0a0">平常運転</span>`;
      $s('rail-side').innerHTML = `<div class="rail-empty" data-testid="live-stream-rail-empty"><i></i><div class="m">影響路線なし</div><div class="s">平常運転</div></div>`;
    }

    if (focusedRailLine) _renderRailDetail(focusedRailLine);
    else _clearRailDetail();
  }

  /* ---- 潮位小窓 (2拠点を同時表示、8秒で次の2拠点へ巡回) ---- */
  {
    const N = tide.stations.length;
    if (tide.status === 'error') {
      $s('tide-meta').innerHTML = `<span class="quiet" data-testid="live-stream-tide-status">一時的に取得不可</span>`;
      $s('tide-body').innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#5d6878;font:11px var(--mono)">一時的に取得不可</div>`;
    } else if (N === 0) {
      $s('tide-meta').innerHTML = `<span class="quiet" data-testid="live-stream-tide-status">監視中</span>`;
      $s('tide-body').innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%"><div style="color:#5d6878;font:12px var(--mono)">現在、表示対象なし</div><div style="color:#3d4a5a;font:10px var(--mono);margin-top:4px">潮位データを監視中</div></div>`;
    } else {
      const pairStart = (Math.floor(tick / 8) * 2) % N;
      // Stream Phase 6-G: ペアが切り替わった瞬間だけスライドインを再生する (毎秒の
      // innerHTML再構築のたびに再生すると単調解消どころか常時チラつくだけになるため)。
      const isNewPair = pairStart !== _tidePairStart;
      _tidePairStart = pairStart;
      const shown = [0, 1].map(j => tide.stations[(pairStart + j) % N]).filter(Boolean);
      $s('tide-meta').innerHTML = N > 2
        ? `<span data-testid="live-stream-tide-status">拠点 ${(pairStart%N)+1}・${((pairStart+1)%N)+1}/${N}</span><span class="cyc"></span><span class="cyc-note">8s巡回</span>`
        : `<span data-testid="live-stream-tide-status">拠点 ${shown.length}/${N}</span>`;
      const curHF = LiveStreamClock.getCurrentHourFloat();
      const slideCls = isNewPair ? ' tide-slide-in' : '';
      $s('tide-body').innerHTML = shown.map((s, i) => {
        const isReal = !!s.source;
        const rawCm = isReal
          ? _interpolateFromRecords(s.records || [], curHF)
          : _tideLvl(s, curHF);
        const curCmStr = rawCm != null && isFinite(rawCm) ? String(Math.round(rawCm)) : '--';
        const devStr = s.dev != null ? `偏差${s.dev}` : '';
        const tideActive = _activeMarkup(`tide-${s.name}`, activeEventId);
        return `<div class="tide-cell${s.alert ? ' alert' : ''}${tideActive.cls}${slideCls}" data-testid="live-stream-tide-station" data-event-id="tide-${s.name}"${tideActive.attr} style="--tide-slide-delay:${i * 70}ms">
           <div class="tide-info">
             <div class="tide-name" data-testid="live-stream-tide-station-name"><span class="dot"></span>${s.name}${s.alert ? '<span class="tide-flag">高潮警戒</span>' : ''}</div>
             <div class="tide-now" data-testid="live-stream-tide-current"><b>${curCmStr}</b><span>cm</span></div>
             <div class="tide-hl">
               <span class="hi" data-testid="live-stream-tide-high">▲${s.high}</span>
               <span class="lo" data-testid="live-stream-tide-low">▼${s.low}</span>
               ${devStr ? `<span class="dv" data-testid="live-stream-tide-deviation">${devStr}</span>` : ''}
             </div>
             ${isReal ? `<div class="tide-src" data-testid="live-stream-tide-source" style="font:9px var(--mono);color:#3d4a5a;margin-top:2px">気象庁潮位表</div>` : ''}
           </div>
           <div class="tide-chart" id="tide-chart-${i}"></div>
         </div>`;
      }).join('');
      shown.forEach((s, i) => {
        const el = $s('tide-chart-' + i);
        if (!el) return;
        if (s.source) {
          renderTideFromRecords(el, s, curHF);
        } else {
          renderTide(el, s, curHF);
        }
      });
    }
  }

  /* ---- テロップ (ticker本文が変わったときのみDOM更新してmarqueeをリセット) ----
     本番データモード (mapEvents が配列) では中央マップと同じ正規化イベント配列からテロップを
     生成する。demo/calm は従来通り scene ベース (Stream Phase 3-C: 地図とテロップの内容統一)。
     Stream Phase 4-A: 自動巡回中の注目 event を「注目」ラベルで先頭に差し込む (方式A)。 */
  {
    const dataState = (typeof LiveStreamEventStore !== 'undefined') ? LiveStreamEventStore.getSummary().dataState : undefined;
    let items = mapEvents ? buildTickerItemsFromEvents(mapEvents) : buildTickerItems(scene);
    const focusEvent = focusState && focusState.mode === 'focus' ? focusState.activeEvent : null;
    items = mergeFocusIntoTickerItems(items, focusEvent);
    const tickerText = buildTickerText(items, mapEvents ? dataState : undefined);
    if (tickerText !== _lastTickerText) {
      _lastTickerText = tickerText;
      const a = $s('ticker-a'); if (a) a.textContent = tickerText;
      const b = $s('ticker-b'); if (b) b.textContent = tickerText;
    }
    // Stream Phase 4-B: 「注目」項目の event id をコンテナ属性に反映する (span化しない簡易対応)。
    // focus が外れた瞬間に空へ戻すため、テキスト変化の有無に関わらず毎回更新する。
    const tickerBodyEl = document.querySelector('[data-testid="live-stream-ticker-body"]');
    if (tickerBodyEl) tickerBodyEl.dataset.focusEventId = focusEvent ? focusEvent.id : '';
  }
}
