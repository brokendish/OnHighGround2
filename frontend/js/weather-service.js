'use strict';

/**
 * weather-service.js — 気象警報・注意報 + 降水予測サマリーの取得とキャッシュ
 *
 * UIが JMA raw payload に直接触れないようにする中間サービス層。
 * weather-card.js / weather-alert-ui.js がこのモジュールを利用する。
 *
 * 外部API:
 *   GET /api/weather/alerts/current?lat=&lon=
 *   GET /api/weather/precipitation/summary?lat=&lon=
 *
 * 公開関数:
 *   _weatherAlertFetch(lat, lon)      — 警報・注意報取得（60秒キャッシュ）
 *   _weatherPrecipFetch(lat, lon)     — 降水予測取得（60秒キャッシュ）
 *   _weatherServiceUpdate(lat, lon)   — 両方取得してコールバック呼び出し
 *   _weatherServiceSetCallback(fn)    — データ更新時コールバック登録
 */

const _WS_ALERT_TTL_MS  = 120_000;  // 120秒
const _WS_PRECIP_TTL_MS =  60_000;  // 60秒

let _wsAlertCache  = null;  // { lat, lon, data, fetchedAt }
let _wsPrecipCache = null;  // { lat, lon, data, fetchedAt }
let _wsCallback    = null;  // fn(alerts, precip) | null

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
        if (_wsAlertCache) return _wsAlertCache.data;  // stale fallback
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
        if (_wsPrecipCache) return _wsPrecipCache.data;  // stale fallback
        return { status: 'unavailable', severity: 'none', summary: '降水情報を取得できません', current: { label: '不明', intensity: 'unknown' }, forecast: [] };
    }
}

async function _weatherServiceUpdate(lat, lon) {
    const [alerts, precip] = await Promise.all([
        _weatherAlertFetch(lat, lon),
        _weatherPrecipFetch(lat, lon),
    ]);
    if (typeof _wsCallback === 'function') {
        try {
            _wsCallback(alerts, precip);
        } catch (err) {
            console.warn('[weather-service] callback error:', err);
        }
    }
    return { alerts, precip };
}
