'use strict';
// live-stream-weather-widget.js — 全国気象ミニテロップ (Phase 8-A)
//
// /api/live/weather/jma/prefectures (backend proxy 経由の Open-Meteo Forecast) を取得し、
// 右カラム最上部の小型テロップに描画する。地震・豪雨・鉄道・潮位とは独立した補助情報であり、
// 主要イベントストア (LiveStreamEventStore) / 自動巡回 (LiveStreamFocusController) には
// 一切関与しない。
//
// 取得失敗時も他パネルを巻き込まないよう、DOM 操作・fetch はすべてこのモジュール内で完結する。

(function () {

  const API_URL          = '/api/live/weather/jma/prefectures';
  const FETCH_TIMEOUT_MS = 5000;
  // 3列 x 2行 = 6件/ページ。YouTube配信で判読できるよう鉄道情報と同じ文字サイズに拡大した分、
  // 1ページの表示件数を9→6に減らしている（frontend/css/live/live-weather-ticker.css参照）。
  const PAGE_SIZE   = 6;

  // ?weatherSpeed=test: E2E高速化用 (他モジュールの focusSpeed/runtimeSpeed と同じ命名規則)。
  // 通常運用の間隔 (fetch 10分・ページ送り10秒) 自体は変更しない。
  const _isTestSpeed = new URLSearchParams(location.search).get('weatherSpeed') === 'test';
  const FETCH_INTERVAL_MS = _isTestSpeed ? 1000 : 10 * 60 * 1000;
  const PAGE_INTERVAL_MS  = _isTestSpeed ? 300 : 10000;

  const _JST_OFFSET_MS = 9 * 60 * 60 * 1000;

  const _WEATHER_BADGE_CLASS = {
    sunny:   'wm-badge--sunny',
    cloudy:  'wm-badge--cloudy',
    rain:    'wm-badge--rain',
    snow:    'wm-badge--snow',
    thunder: 'wm-badge--thunder',
    fog:     'wm-badge--fog',
    unknown: 'wm-badge--unknown',
  };

  let _data      = null;   // 直近の /api/live/weather/jma/prefectures レスポンス
  let _pages     = [];
  let _pageIndex = 0;
  let _pageTimer = null;

  function _el(id) { return document.getElementById(id); }

  // ── JST 時刻フォーマット (ブラウザのタイムゾーンに依存しない) ─────────────────
  function _fmtHM(isoStr) {
    if (!isoStr) return '--:--';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return '--:--';
      const jst = new Date(d.getTime() + _JST_OFFSET_MS);
      const hh = String(jst.getUTCHours()).padStart(2, '0');
      const mm = String(jst.getUTCMinutes()).padStart(2, '0');
      return `${hh}:${mm}`;
    } catch (_) {
      return '--:--';
    }
  }

  // ── fetch (timeout付き) ────────────────────────────────────────────────────
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

  function _chunk(items, size) {
    const pages = [];
    for (let i = 0; i < items.length; i += size) pages.push(items.slice(i, i + size));
    return pages.length ? pages : [[]];
  }

  // ── 出典バッジ (backendの source をそのまま表示。ハードコードして再度乖離させない) ──
  function _renderSource() {
    const srcEl = _el('weather-source');
    if (!srcEl || !_data || !_data.source) return;
    srcEl.textContent = _data.source;
  }

  // ── ヘッダー (更新時刻) ─────────────────────────────────────────────────────
  function _renderMeta() {
    const metaEl = _el('weather-meta');
    if (!metaEl) return;

    if (!_data) {
      metaEl.innerHTML = `<span class="wm-status wm-status--pending">取得中...</span>`;
      return;
    }

    if (_data.cache_status === 'unavailable') {
      const prev = _data.fetched_at
        ? ` / 前回 ${_fmtHM(_data.fetched_at)}取得`
        : '';
      metaEl.innerHTML = `<span class="wm-status wm-status--unavailable">更新停止中${prev}</span>`;
      return;
    }

    const forecastHm = _fmtHM(_data.forecast_time);
    const fetchedHm  = _fmtHM(_data.fetched_at);
    let html = `${forecastHm}時点 / ${fetchedHm}取得`;
    if (_data.cache_status === 'stale') {
      html += ' <span class="wm-status wm-status--stale">更新遅延</span>';
    }
    metaEl.innerHTML = html;
  }

  // ── 地点セル ────────────────────────────────────────────────────────────────
  function _pointCellHtml(item) {
    const badgeClass = _WEATHER_BADGE_CLASS[item.weather_category] || _WEATHER_BADGE_CLASS.unknown;
    const temp = item.temperature_c != null ? `${Math.round(item.temperature_c)}℃` : '--℃';
    const humidity = item.humidity_percent != null ? `湿${Math.round(item.humidity_percent)}` : '湿--';
    const precip = item.precipitation_probability_percent != null
      ? `雨${Math.round(item.precipitation_probability_percent)}`
      : '雨--';
    const flags = item.flags || {};

    const tempClass = flags.temperature_hot ? ' wm-flag-temp-hot'
      : (flags.temperature_cold ? ' wm-flag-temp-cold' : '');
    const humidityClass = flags.humidity_high ? ' wm-flag-humidity-high' : '';
    const precipClass = flags.precipitation_high ? ' wm-flag-precip-high' : '';

    return `
      <div class="wm-point" data-testid="live-stream-weather-point" data-point-id="${item.id}">
        <div class="wm-point-row">
          <span class="wm-point-name">${item.point_name}</span>
          <span class="wm-badge ${badgeClass}">${item.weather_label}</span>
          <span class="wm-temp${tempClass}">${temp}</span>
        </div>
        <div class="wm-point-sub">
          <span class="wm-humidity${humidityClass}">${humidity}</span>
          <span class="wm-precip${precipClass}">${precip}</span>
        </div>
      </div>`;
  }

  function _renderPage() {
    const bodyEl = _el('weather-body');
    if (!bodyEl) return;

    if (!_pages.length || !_pages[0].length) {
      let msg = '表示対象なし';
      let testId = null;
      if (!_data) {
        msg = '取得中...';
      } else if (_data.cache_status === 'unavailable') {
        msg = '全国気象データを取得できません';
        testId = 'live-stream-weather-unavailable';
      }
      bodyEl.innerHTML = `<div class="wm-empty"${testId ? ` data-testid="${testId}"` : ''}>${msg}</div>`;
      return;
    }

    const page = _pages[_pageIndex % _pages.length];
    bodyEl.innerHTML = page.map(_pointCellHtml).join('');
  }

  function _render() {
    _renderSource();
    _renderMeta();
    const items = (_data && Array.isArray(_data.items)) ? _data.items : [];
    _pages = _chunk(items, PAGE_SIZE);
    if (_pageIndex >= _pages.length) _pageIndex = 0;
    _renderPage();
  }

  function _startPaging() {
    if (_pageTimer) return;
    _pageTimer = setInterval(() => {
      if (!_pages.length) return;
      _pageIndex = (_pageIndex + 1) % _pages.length;
      _renderPage();
    }, PAGE_INTERVAL_MS);
  }

  // ── データ取得 ────────────────────────────────────────────────────────────
  async function _fetchWeather() {
    try {
      const json = await _fetchJson(API_URL);
      _data = json;
      _pageIndex = 0;
      _render();
    } catch (e) {
      console.warn('[live-stream-weather] 取得失敗:', e.message);
      // backend に到達できない場合のみ、既存データがなければ unavailable 扱いにする。
      // 既存データがある場合は前回状態を維持し、console error を出し続けない。
      if (!_data) {
        _data = {
          status: 'unavailable', source: 'Open-Meteo Forecast',
          forecast_time: null, fetched_at: null,
          cache_status: 'unavailable', items: [],
        };
        _render();
      }
    }
  }

  function init() {
    if (!_el('weather-body')) return; // 対象DOMがなければ何もしない
    _render();
    _startPaging();
    _fetchWeather();
    setInterval(_fetchWeather, FETCH_INTERVAL_MS);
  }

  init();

  window.LiveStreamWeatherWidget = { fetchNow: _fetchWeather };

})();
