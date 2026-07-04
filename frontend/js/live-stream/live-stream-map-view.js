'use strict';
// /live/stream — 中央メイン地図 本番地図ラッパー (Stream Phase 3-A)
// Leaflet を使った「見るだけ地図」。操作無効・日本全土表示・パルス描画のみを担う。
// 通常 /live の地図処理 (frontend/js/live/live-map.js) とは完全に独立したモジュール。
// Leaflet 未ロード/初期化失敗時は failed=true を立て、呼び出し側 (panels.js) が
// 旧SVGモック地図 (renderMap) へフォールバックする。

const JAPAN_BOUNDS = [
  [24.0, 122.0],
  [46.0, 146.5],
];

const LS_PULSE_COLOR = {
  earthquake: 'var(--c-eq)',
  rain:       'var(--c-rain-2)',
  rail:       'var(--c-rail)',
  tide:       'var(--c-tide-2)',
};

// Stream Phase 5-A.1: Leaflet 地図の初期化直後、同じ .win-map/.ls-center 内にある兄弟の
// ポップアップ要素 (#eq-overlay 配下の .popup 等) が、Leaflet 内部pane (tile=200, marker=600,
// tooltip=650, popup=700 など) の背後に隠れて描画されてしまう現象が確認された。
// 実機検証の結果、原因は「地図コンテナ自身が z-index:auto のスタッキングコンテキストを
// 確立しないため、内部pane の明示的 z-index (最大700) が親の比較にそのまま漏れ出す」ことと
// 判明した。対処には次の両方が必要 (実機で確認済み):
//   1. 値は Leaflet 内部paneの最大値(700)を確実に上回ること (2 等の小さい値では効果なし)
//   2. ページ読み込み時の静的CSS/addInitScript としてではなく、地図初期化後に
//      JavaScript から新しい <style> 要素を差し込むこと (class切替や既存要素への
//      z-index代入だけでは Chromium の合成レイヤー確定が正しく再計算されず効果がない)
// 対象 (.popup) はページ全体で共通のクラスのため、一度だけ適用すればよい。
let _popupStackingFixApplied = false;
function _applyPopupStackingFix() {
  if (_popupStackingFixApplied || typeof document === 'undefined') return;
  _popupStackingFixApplied = true;
  const style = document.createElement('style');
  style.textContent = '.popup { z-index: 1000 !important; }';
  document.head.appendChild(style);
}
// タイル読み込みが失敗/極端に遅い場合のフォールバック (ページ読み込みから一定時間後に必ず1回適用する)。
if (typeof window !== 'undefined') {
  setTimeout(_applyPopupStackingFix, 4000);
}

class LiveStreamMapView {
  constructor(options) {
    const opts = options || {};
    this.containerId = opts.containerId;
    this.mode        = opts.mode || 'center';
    this.interactive = !!opts.interactive;
    this.map          = null;
    this.failed       = false;
    this._pulseLayer  = null;
    this._markerLayer = null;
    this._eventLayer  = null;
    this._intensityLayer = null; // Stream Phase 5-A bundle: 地震子画面 市区町村震度マーカー用 (mini map)
  }

  initialize() {
    const container = typeof this.containerId === 'string'
      ? document.getElementById(this.containerId)
      : this.containerId;
    if (!container || typeof L === 'undefined') {
      this.failed = true;
      console.warn('[LiveStreamMapView] Leaflet unavailable — falling back to legacy map');
      return false;
    }
    try {
      this.map = L.map(container, {
        zoomControl:        false,
        attributionControl: true,
        dragging:            this.interactive,
        scrollWheelZoom:     this.interactive,
        doubleClickZoom:     this.interactive,
        boxZoom:             this.interactive,
        keyboard:            this.interactive,
        tap:                 this.interactive,
        touchZoom:           this.interactive,
        preferCanvas:        true,
      });

      const baseTileLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains:  'abcd',
        maxZoom:     19,
      }).addTo(this.map);
      // 初回タイル読み込み完了直後に popup スタッキング修正を適用する (詳細は _applyPopupStackingFix 参照)。
      baseTileLayer.once('load', _applyPopupStackingFix);

      // 雨雲(降水ナウキャスト)レイヤーは中央メイン地図・キキクル/豪雨子画面小地図 (rain-mini) の
      // 両方に載せる (Stream Phase 5-A.1: 「場所の特定が困難」なモック地図から本番地図へ移行)。
      // LiveStreamRainLayer 側で key ごとの多重init防止・API取得共有を行う。
      if ((this.mode === 'center' || this.mode === 'rain-mini') && typeof LiveStreamRainLayer !== 'undefined') {
        LiveStreamRainLayer.init(this.map, { key: this.mode });
      }
      // 鉄道路線レイヤーは中央メイン地図・鉄道子画面小地図 (rail-mini) の両方に載せる
      // (Stream Phase 5-A.1 railway calm map: 平常時も路線図を表示するため)。
      // LiveStreamRailwayLayer 側で key ごとの多重init防止・affected共有描画を行う。
      if ((this.mode === 'center' || this.mode === 'rail-mini') && typeof LiveStreamRailwayLayer !== 'undefined') {
        LiveStreamRailwayLayer.init(this.map, { key: this.mode });
      }

      this._pulseLayer  = L.layerGroup().addTo(this.map);
      this._markerLayer = L.layerGroup().addTo(this.map);
      this._eventLayer  = L.layerGroup().addTo(this.map);
      this._intensityLayer = L.layerGroup().addTo(this.map);

      this.fitJapan();
      return true;
    } catch (e) {
      console.warn('[LiveStreamMapView] initialize failed:', e.message);
      this.failed = true;
      return false;
    }
  }

  // @param {boolean} [animate]  Stream Phase 4-B — focus からの復帰 (returning) を滑らかにする場合は true。
  //   初期表示 (initialize() からの呼び出し) は従来通り animate なしで即座に全体表示する。
  fitJapan(animate) {
    if (!this.map) return;
    const reduced = typeof window !== 'undefined' && window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.map.fitBounds(JAPAN_BOUNDS, { padding: [8, 8], animate: !!animate && !reduced, duration: 1.0 });
  }

  // Stream Phase 4-A/4-B — 注目 event の緯度経度へ地図を移動する (自動巡回の focus 表示)。
  // 見るだけ地図のユーザー操作は無効のままだが、プログラムによる移動 (flyTo) は許可する。
  focusOn(lat, lng, zoom) {
    if (!this.map || lat == null || lng == null || !isFinite(lat) || !isFinite(lng)) return;
    const reduced = typeof window !== 'undefined' && window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      this.map.setView([lat, lng], zoom || 7, { animate: false });
      return;
    }
    this.map.flyTo([lat, lng], zoom || 7, { animate: true, duration: 1.0, easeLinearity: 0.25 });
  }

  _pulseIcon(p, isActive) {
    const color  = LS_PULSE_COLOR[p.category] || '#7ee0a0';
    const testid = p.testid || `live-stream-pulse-${p.category}`;
    const label  = p.label ? `<span class="ls-pulse-label">${p.label}</span>` : '';
    const idAttr = p.id ? ` data-event-id="${p.id}"` : '';
    const activeClass = isActive ? ' ls-pulse--active' : '';
    const activeAttr  = isActive ? ' data-active="true"' : '';
    const html = `<div class="ls-pulse ls-pulse--${p.category}${activeClass}" data-testid="${testid}"${idAttr}${activeAttr} style="--pulse-color:${color}">
      <span class="ls-pulse-ring"></span><span class="ls-pulse-core"></span>${label}
    </div>`;
    return L.divIcon({ html, className: 'ls-pulse-icon', iconSize: [0, 0] });
  }

  // @param {string|null} activeEventId  Stream Phase 4-A — この id と一致する pulse に active class/属性を付与する。
  setPulses(pulses, activeEventId) {
    if (!this.map || !this._pulseLayer) return;
    this._pulseLayer.clearLayers();
    (pulses || []).forEach(p => {
      if (p.lat == null || p.lon == null || !isFinite(p.lat) || !isFinite(p.lon)) return;
      L.marker([p.lat, p.lon], {
        icon:        this._pulseIcon(p, !!(activeEventId && p.id === activeEventId)),
        interactive: false,
        keyboard:    false,
      }).addTo(this._pulseLayer);
    });
  }

  clearPulses() {
    if (this._pulseLayer) this._pulseLayer.clearLayers();
  }

  setMarkers(markers) {
    if (!this.map || !this._markerLayer) return;
    this._markerLayer.clearLayers();
    (markers || []).forEach(m => {
      if (m.lat == null || m.lon == null || !isFinite(m.lat) || !isFinite(m.lon)) return;
      const testidAttr = m.testid ? ` data-testid="${m.testid}"` : '';
      const icon = L.divIcon({
        html:      `<div class="ls-marker"${testidAttr}></div>`,
        className: 'ls-marker-icon',
        iconSize:  [0, 0],
      });
      L.marker([m.lat, m.lon], { icon, interactive: false, keyboard: false }).addTo(this._markerLayer);
    });
  }

  clearMarkers() {
    if (this._markerLayer) this._markerLayer.clearLayers();
  }

  // Stream Phase 3-B — 本番データ由来の正規化イベント ({id,type,severity,lat,lng,title,...}) を描画する。
  // demo用パルス (setPulses) とは別レイヤーで管理し、通常モードでは pulses 側を使わない。
  // Stream Phase 4-A: isActive で自動巡回中の注目 event を強調する。
  _eventIcon(e, isActive) {
    const testid = `live-stream-map-event-${e.type}`;
    const staleClass = e.stale ? ' stream-map-event--stale' : '';
    const activeClass = isActive ? ' stream-map-event--active' : '';
    const activeAttr  = isActive ? ' data-active="true"' : '';
    const titleAttr = (e.title || '').replace(/"/g, '&quot;');
    const html = `<div class="stream-map-event stream-map-event--${e.type} stream-map-event--${e.severity}${staleClass}${activeClass}"
      data-testid="${testid}" data-event-type="${e.type}" data-event-id="${e.id}"${activeAttr} title="${titleAttr}">
    </div>`;
    return L.divIcon({ html, className: 'stream-map-event-icon', iconSize: [16, 16] });
  }

  // @param {string|null} activeEventId  Stream Phase 4-A — この id と一致する event に active class/属性を付与する。
  setEvents(events, activeEventId) {
    if (!this.map || !this._eventLayer) return;
    this._eventLayer.clearLayers();
    (events || []).forEach(e => {
      if (e.lat == null || e.lng == null || !isFinite(e.lat) || !isFinite(e.lng)) return;
      L.marker([e.lat, e.lng], {
        icon:        this._eventIcon(e, !!(activeEventId && e.id === activeEventId)),
        interactive: false,
        keyboard:    false,
      }).addTo(this._eventLayer);
    });
  }

  clearEvents() {
    if (this._eventLayer) this._eventLayer.clearLayers();
  }

  // Stream Phase 5-A bundle: 任意の緯度経度点群が収まる bounds へ fit する汎用メソッド。
  // 地震子画面の市区町村震度マーカー範囲 (fit/tour) 用。JAPAN_BOUNDS 固定の fitJapan() とは別に、
  // 呼び出し側が計算した任意の点群に対応する。
  // @param {Array<[number,number]>} latlngs
  // @param {object} [opts] { animate, padding }
  fitTo(latlngs, opts) {
    if (!this.map || !latlngs || latlngs.length === 0) return;
    const o = opts || {};
    const reduced = typeof window !== 'undefined' && window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (latlngs.length === 1) {
      const zoom = o.singleZoom || 9;
      if (reduced || o.animate === false) this.map.setView(latlngs[0], zoom, { animate: false });
      else this.map.flyTo(latlngs[0], zoom, { animate: true, duration: 0.8, easeLinearity: 0.25 });
      return;
    }
    const bounds = L.latLngBounds(latlngs);
    this.map.fitBounds(bounds, {
      padding: o.padding || [20, 20],
      animate: !!o.animate && !reduced,
      duration: 0.8,
      maxZoom: o.maxZoom || 10,
    });
  }

  // Stream Phase 5-A bundle: 市区町村震度マーカー (地震子画面 mini map 専用)。
  // divIcon には既存 (SVG版) と同じ data-testid/data-intensity/data-pref/data-city を持たせ、
  // E2E からの参照方法を変えない (Phase 5-A.1 の既存 spec をそのまま再利用できるようにする)。
  // @param {Array} markers  [{lat,lng,intensity,pref,city,clsSuffix,label,isActive}, ...]
  setIntensityMarkers(markers) {
    if (!this.map || !this._intensityLayer) return;
    this._intensityLayer.clearLayers();
    (markers || []).forEach(m => {
      if (m.lat == null || m.lng == null || !isFinite(m.lat) || !isFinite(m.lng)) return;
      const activeClass = m.isActive ? ' stream-eq-intensity-marker--active' : '';
      const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, ch => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]));
      const html = `<div class="stream-eq-intensity-marker stream-eq-intensity-marker--${m.clsSuffix || '0'}${activeClass}"
        data-testid="live-stream-earthquake-municipal-marker" data-intensity="${esc(m.intensity)}" data-pref="${esc(m.pref)}" data-city="${esc(m.city)}"
      >${esc(m.label != null ? m.label : m.intensity)}</div>`;
      const icon = L.divIcon({ html, className: 'stream-eq-intensity-marker-icon', iconSize: [18, 18], iconAnchor: [9, 9] });
      L.marker([m.lat, m.lng], { icon, interactive: false, keyboard: false, zIndexOffset: 200 }).addTo(this._intensityLayer);
    });
  }

  clearIntensityMarkers() {
    if (this._intensityLayer) this._intensityLayer.clearLayers();
  }

  invalidateSize() {
    if (this.map) this.map.invalidateSize();
  }

  // Stream Phase 5-A: 長時間運用の診断用。marker/layerが増殖していないか外部から確認できる。
  getDiagnostics() {
    return {
      mapInitialized: !!this.map,
      failed:         this.failed,
      eventMarkerCount:  this._eventLayer  ? this._eventLayer.getLayers().length  : 0,
      pulseMarkerCount:  this._pulseLayer  ? this._pulseLayer.getLayers().length  : 0,
      markerCount:       this._markerLayer ? this._markerLayer.getLayers().length : 0,
      intensityMarkerCount: this._intensityLayer ? this._intensityLayer.getLayers().length : 0,
    };
  }

  destroy() {
    if (this.map) {
      this.map.remove();
      this.map = null;
    }
  }
}

window.LiveStreamMapView = LiveStreamMapView;
