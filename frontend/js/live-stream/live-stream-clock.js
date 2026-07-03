// /live/stream — 時刻管理 (LiveStreamClock)
//
// ?demoNow=ISO8601 が URL に指定されている場合は固定時刻を返す（E2E・スクリーンショット安定化用）。
// 指定がない場合は実時刻 (new Date()) を返す。
//
// 例:
//   ?demoNow=2026-06-30T19:42:00%2B09:00  → 固定 19:42:00 JST
//   未指定                                  → 実時刻
//
// URL の '+' はブラウザが ' '(スペース) にデコードする場合があるため replace で補正する。

const LiveStreamClock = (function () {
  const _raw   = new URLSearchParams(location.search).get('demoNow');
  const _fixed = _raw ? new Date(_raw.replace(/ /g, '+')) : null;
  const _valid = _fixed && !isNaN(_fixed.getTime());

  const _DAYS = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  const _p = n => String(n).padStart(2, '0');

  /** demoNow が有効か */
  function isFixedDemoTime() { return _valid; }

  /** 現在の Date オブジェクトを返す (demoNow 固定 or 実時刻) */
  function getNow() {
    return _valid ? new Date(_fixed.getTime()) : new Date();
  }

  /**
   * 現在時刻を JST "時間単位の小数" で返す。潮位カーブの現在位置算出に使用。
   * TideStreamAdapter._jstHour() と同じ JST 基準とするため明示的に UTC+9 で計算する。
   * 例: 2026-06-30T19:42:00+09:00 → 19.7
   */
  function getCurrentHourFloat() {
    const JST_OFFSET_MS = 9 * 60 * 60 * 1000;
    const now = getNow();
    const jst = new Date(now.getTime() + JST_OFFSET_MS);
    return jst.getUTCHours() + jst.getUTCMinutes() / 60 + jst.getUTCSeconds() / 3600;
  }

  /** ヘッダー時計: HH:MM:SS */
  function formatHeaderTime(now) {
    return `${_p(now.getHours())}:${_p(now.getMinutes())}:${_p(now.getSeconds())}`;
  }

  /** ヘッダー日付行: YYYY.MM.DD DAY · JST */
  function formatDateLine(now) {
    return `${now.getFullYear()}.${_p(now.getMonth() + 1)}.${_p(now.getDate())} ${_DAYS[now.getDay()]} · JST`;
  }

  /** 中央地図内時計: HH:MM */
  function formatMapTime(now) {
    return `${_p(now.getHours())}:${_p(now.getMinutes())}`;
  }

  /** 中央地図内日付: YYYY.MM.DD 現在 */
  function formatMapDate(now) {
    return `${now.getFullYear()}.${_p(now.getMonth() + 1)}.${_p(now.getDate())} 現在`;
  }

  return { isFixedDemoTime, getNow, getCurrentHourFloat, formatHeaderTime, formatDateLine, formatMapTime, formatMapDate };
})();

// 時計 DOM を更新する — main.js から毎秒呼ぶ。
// demoNow 固定時は同一表示を繰り返す（アニメーションリセット防止のため呼び出し自体は継続）。
function updateClock() {
  const now = LiveStreamClock.getNow();
  const clockEl      = document.getElementById('clock');
  const dateEl       = document.getElementById('date');
  const clockShortEl = document.getElementById('clock-short');
  const dateShortEl  = document.getElementById('date-short');
  if (clockEl)      clockEl.textContent      = LiveStreamClock.formatHeaderTime(now);
  if (dateEl)       dateEl.textContent       = LiveStreamClock.formatDateLine(now);
  if (clockShortEl) clockShortEl.textContent = LiveStreamClock.formatMapTime(now);
  if (dateShortEl)  dateShortEl.textContent  = LiveStreamClock.formatMapDate(now);
}
