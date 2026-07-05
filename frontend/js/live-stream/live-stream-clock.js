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
//
// Stream Phase 5-B.1: streamer container (VPS配信用、OS timezoneがUTCの場合が多い) でも
// 画面表示は必ずJSTになるようにする。Date の getHours()/getDate() 等はブラウザ/OSの
// ローカルタイムゾーン依存のため使わず、UTC+9 オフセットを明示的に加算してから
// getUTCXxx() で値を取り出す (TideStreamAdapter._jstHour() 等と同じ方式)。

const LiveStreamClock = (function () {
  const JST_OFFSET_MS = 9 * 60 * 60 * 1000;

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

  /** now (実時刻 or demoNow固定) を JST の暦・時刻要素に変換する。 */
  function _toJstParts(now) {
    const jst = new Date(now.getTime() + JST_OFFSET_MS);
    return {
      year:    jst.getUTCFullYear(),
      month:   jst.getUTCMonth() + 1,
      date:    jst.getUTCDate(),
      day:     jst.getUTCDay(),
      hours:   jst.getUTCHours(),
      minutes: jst.getUTCMinutes(),
      seconds: jst.getUTCSeconds(),
    };
  }

  /**
   * 現在時刻を JST "時間単位の小数" で返す。潮位カーブの現在位置算出に使用。
   * TideStreamAdapter._jstHour() と同じ JST 基準とするため明示的に UTC+9 で計算する。
   * 例: 2026-06-30T19:42:00+09:00 → 19.7
   */
  function getCurrentHourFloat() {
    const p = _toJstParts(getNow());
    return p.hours + p.minutes / 60 + p.seconds / 3600;
  }

  /** ヘッダー時計: HH:MM:SS (JST) */
  function formatHeaderTime(now) {
    const p = _toJstParts(now);
    return `${_p(p.hours)}:${_p(p.minutes)}:${_p(p.seconds)}`;
  }

  /** ヘッダー日付行: YYYY.MM.DD DAY · JST */
  function formatDateLine(now) {
    const p = _toJstParts(now);
    return `${p.year}.${_p(p.month)}.${_p(p.date)} ${_DAYS[p.day]} · JST`;
  }

  /** 中央地図内時計: HH:MM (JST) */
  function formatMapTime(now) {
    const p = _toJstParts(now);
    return `${_p(p.hours)}:${_p(p.minutes)}`;
  }

  /** 中央地図内日付: YYYY.MM.DD 現在 (JST) */
  function formatMapDate(now) {
    const p = _toJstParts(now);
    return `${p.year}.${_p(p.month)}.${_p(p.date)} 現在`;
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
