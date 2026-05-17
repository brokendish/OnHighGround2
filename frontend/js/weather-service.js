'use strict';

/**
 * weather-service.js — 気象警報・注意報 + 降水予測 + 複合リスクの取得とキャッシュ
 *
 * UIが JMA raw payload に直接触れないようにする中間サービス層。
 * weather-card.js / weather-alert-ui.js がこのモジュールを利用する。
 *
 * 外部API:
 *   GET /api/weather/alerts/current?lat=&lon=
 *   GET /api/weather/precipitation/summary?lat=&lon=
 *   GET /api/weather/risk/context?lat=&lon=        ← Phase2-C 追加
 *
 * 公開関数:
 *   _weatherAlertFetch(lat, lon)      — 警報・注意報取得（120秒キャッシュ）
 *   _weatherPrecipFetch(lat, lon)     — 降水予測取得（60秒キャッシュ）
 *   _weatherRiskContextFetch(lat,lon) — 複合リスクコンテキスト（60秒キャッシュ）
 *   _weatherServiceUpdate(lat, lon)   — 3並列取得してコールバック呼び出し
 *   _weatherServiceSetCallback(fn)    — データ更新時コールバック登録
 *                                       fn(alerts, precip, riskInfo) の3引数
 */

const _WS_ALERT_TTL_MS   = 120_000;  // 120秒
const _WS_PRECIP_TTL_MS  =  60_000;  // 60秒
const _WS_CONTEXT_TTL_MS =  60_000;  // 60秒

let _wsAlertCache   = null;  // { lat, lon, data, fetchedAt }
let _wsPrecipCache  = null;
let _wsContextCache = null;
let _wsCallback     = null;  // fn(alerts, precip, riskInfo) | null

function _weatherServiceSetCallback(fn) {
    _wsCallback = fn;
}

function _wsCacheHit(cache, lat, lon, ttlMs) {
    if (!cache) return false;
    if (Math.abs(cache.lat - lat) > 0.05) return false;
    if (Math.abs(cache.lon - lon) > 0.05) return false;
    return (Date.now() - cache.fetchedAt) < ttlMs;
}

async function _weatherAlertFetch(lat, lon) {
    if (_wsCacheHit(_wsAlertCache, lat, lon, _WS_ALERT_TTL_MS)) {
        return _wsAlertCache.data;
    }
    try {
        const res = await fetch(`/api/weather/alerts/current?lat=${lat}&lon=${lon}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _wsAlertCache = { lat, lon, data, fetchedAt: Date.now() };
        return data;
    } catch (err) {
        console.warn('[weather-service] alerts fetch error:', err);
        if (_wsAlertCache) return _wsAlertCache.data;
        return { status: 'unavailable', severity: 'none', alerts: [], message: '気象情報を取得できません' };
    }
}

async function _weatherPrecipFetch(lat, lon) {
    if (_wsCacheHit(_wsPrecipCache, lat, lon, _WS_PRECIP_TTL_MS)) {
        return _wsPrecipCache.data;
    }
    try {
        const res = await fetch(`/api/weather/precipitation/summary?lat=${lat}&lon=${lon}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _wsPrecipCache = { lat, lon, data, fetchedAt: Date.now() };
        return data;
    } catch (err) {
        console.warn('[weather-service] precip fetch error:', err);
        if (_wsPrecipCache) return _wsPrecipCache.data;
        return { status: 'unavailable', severity: 'none', summary: '降水情報を取得できません',
                 current: { label: '不明', intensity: 'unknown' }, forecast: [] };
    }
}

async function _weatherRiskContextFetch(lat, lon) {
    if (_wsCacheHit(_wsContextCache, lat, lon, _WS_CONTEXT_TTL_MS)) {
        return _wsContextCache.data;
    }
    try {
        const res = await fetch(`/api/weather/risk/context?lat=${lat}&lon=${lon}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _wsContextCache = { lat, lon, data, fetchedAt: Date.now() };
        return data;
    } catch (err) {
        console.warn('[weather-service] risk context fetch error:', err);
        if (_wsContextCache) return _wsContextCache.data;
        return { status: 'unavailable', risk_level: 'unknown',
                 combined: [], hazards: { data_available: false } };
    }
}

// ── リスクレベル統合 (Phase2-B + Phase2-C) ────────────────────────────────────

const _WS_SEVERITY_RANK = { emergency: 4, warning: 3, advisory: 2, none: 0, unknown: 0 };

function _wsRankOf(sev) {
    return _WS_SEVERITY_RANK[sev] ?? 0;
}

/**
 * 警報・降水・複合リスクコンテキストを統合してリスクレベルを返す。
 * - 降水は最大 warning（emergency は警報専用）
 * - context の risk_level は加算ソース（backend が計算した combined を反映）
 * - 'unknown' は none より安全側に扱うが既知リスクを上書きしない
 */
function _computeRiskLevel(alertsData, precipData, contextData) {
    const alertRank   = _wsRankOf((alertsData  || {}).severity);
    const precipRank  = Math.min(_wsRankOf((precipData  || {}).severity), 3); // max=warning
    const ctxRank     = _wsRankOf((contextData || {}).risk_level || 'none');
    const maxRank     = Math.max(alertRank, precipRank, ctxRank);
    if (maxRank >= 4) return 'emergency';
    if (maxRank === 3) return 'warning';
    if (maxRank === 2) return 'advisory';
    // 'unknown' の伝播: backend が unknown と判定し、かつ既知リスクが0のとき
    if ((contextData || {}).risk_level === 'unknown') return 'unknown';
    return 'none';
}

/**
 * 降水予測データから現在・予測最大を構造化して返す。
 */
function _buildPrecipInfo(precipData) {
    if (!precipData || precipData.status === 'unavailable') {
        return { current: null, forecastStrongest: null, forecast: [] };
    }
    const current  = precipData.current || null;
    const forecast = precipData.forecast || [];
    const RANK = { severe: 4, strong: 3, moderate: 2, weak: 1, none: 0, unknown: -1 };
    let forecastStrongest = null;
    let maxRank = -2;
    for (const f of forecast) {
        const rank = RANK[f.intensity] ?? -1;
        if (rank > maxRank) { maxRank = rank; forecastStrongest = f; }
    }
    return { current, forecastStrongest, forecast };
}

// ── メイン更新 ────────────────────────────────────────────────────────────────

async function _weatherServiceUpdate(lat, lon) {
    const [alerts, precip, context] = await Promise.all([
        _weatherAlertFetch(lat, lon),
        _weatherPrecipFetch(lat, lon),
        _weatherRiskContextFetch(lat, lon),
    ]);
    const riskLevel     = _computeRiskLevel(alerts, precip, context);
    const precipInfo    = _buildPrecipInfo(precip);
    const precipUnknown = (precip || {}).severity === 'unknown';
    const riskInfo = {
        riskLevel,
        precipInfo,
        precipUnknown,
        combined: (context || {}).combined  || [],
        hazards:  (context || {}).hazards   || { data_available: false },
    };
    if (typeof _wsCallback === 'function') {
        try {
            _wsCallback(alerts, precip, riskInfo);
        } catch (err) {
            console.warn('[weather-service] callback error:', err);
        }
    }
    return { alerts, precip, context, riskInfo };
}
