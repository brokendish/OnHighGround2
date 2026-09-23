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
 *
 * 取得状態 contract（各 fetch の戻り値 status）:
 *   ok          — 最新取得成功
 *   stale       — 最新取得に失敗し、同一地点の前回取得データを返している（値は前回値・最新を保証しない）
 *   unavailable — 最新取得に失敗し、利用できる前回データもない
 * status は取得状態、severity / risk_level は内容（none = 正常取得の結果「なし」）であり混同しない。
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

function _wsCacheNear(cache, lat, lon) {
    if (!cache) return false;
    if (Math.abs(cache.lat - lat) > 0.05) return false;
    if (Math.abs(cache.lon - lon) > 0.05) return false;
    return true;
}

function _wsCacheHit(cache, lat, lon, ttlMs) {
    if (!_wsCacheNear(cache, lat, lon)) return false;
    return (Date.now() - cache.fetchedAt) < ttlMs;
}

/**
 * 再取得失敗時の前回データ fallback。
 * 保存済み cache を変更せず、返却用コピーに status='stale' を付けて返す。
 * 同一地点の cache がなければ null（呼び出し側で unavailable を返す）。
 * 前回データ自体が unavailable（backend 側の取得失敗応答）の場合は unavailable のまま返す。
 */
function _wsStaleFallback(cache, lat, lon, extra) {
    if (!_wsCacheNear(cache, lat, lon)) return null;
    const copy = JSON.parse(JSON.stringify(cache.data));  // API JSON 由来のため JSON clone で十分
    if (copy.status === 'unavailable') return copy;
    copy.status = 'stale';
    return Object.assign(copy, extra || {});
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
        const stale = _wsStaleFallback(_wsAlertCache, lat, lon, {
            message: '最新の気象情報を取得できません（前回取得データを表示中）',  // backend stale 応答と同文言
        });
        if (stale) return stale;
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
        const stale = _wsStaleFallback(_wsPrecipCache, lat, lon);
        if (stale) return stale;
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
        const stale = _wsStaleFallback(_wsContextCache, lat, lon);
        if (stale) return stale;
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
 * - 警報・降水の取得失敗（status='unavailable'）は none ではなく 'unknown'（判定不能）
 *   backend weather_risk_context_service._compute_risk_level と同じ判定順
 * - status='stale'（前回取得データ）は前回値で評価する（backend stale policy と同じ）。
 *   stale であることは riskInfo / 表示側で明示する
 */
function _computeRiskLevel(alertsData, precipData, contextData) {
    const alertRank   = _wsRankOf((alertsData  || {}).severity);
    const precipRank  = Math.min(_wsRankOf((precipData  || {}).severity), 3); // max=warning
    const ctxRank     = _wsRankOf((contextData || {}).risk_level || 'none');
    const maxRank     = Math.max(alertRank, precipRank, ctxRank);
    if (maxRank >= 4) return 'emergency';
    if (maxRank === 3) return 'warning';
    if (maxRank === 2) return 'advisory';
    // 'unknown' の伝播: 既知リスクが0のとき
    //   - 未分類コードの警報・注意報のみ発表中（alerts severity=unknown）→ none と断定しない
    //   - backend context が unknown と判定
    if ((alertsData  || {}).severity   === 'unknown') return 'unknown';
    //   - 警報・降水の取得失敗 → 「なし」と断定しない
    if ((alertsData  || {}).status     === 'unavailable') return 'unknown';
    if ((precipData  || {}).status     === 'unavailable') return 'unknown';
    if ((contextData || {}).risk_level === 'unknown') return 'unknown';
    return 'none';
}

/**
 * 降水予測データから現在・予測最大を構造化して返す。
 */
function _buildPrecipInfo(precipData) {
    if (!precipData || precipData.status === 'unavailable') {
        // unavailable: 取得失敗（「降水なし」とは区別して表示側へ伝える）
        return { current: null, forecastStrongest: null, forecast: [], unavailable: true };
    }
    const stale    = precipData.status === 'stale';  // 前回取得データ（値は表示するが最新ではない）
    const current  = precipData.current || null;
    const forecast = precipData.forecast || [];
    const RANK = { severe: 4, strong: 3, moderate: 2, weak: 1, none: 0, unknown: -1 };
    let forecastStrongest = null;
    let maxRank = -2;
    for (const f of forecast) {
        const rank = RANK[f.intensity] ?? -1;
        if (rank > maxRank) { maxRank = rank; forecastStrongest = f; }
    }
    return { current, forecastStrongest, forecast, stale };
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
        contextStale: (context || {}).status === 'stale',
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
