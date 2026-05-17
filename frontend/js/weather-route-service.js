'use strict';

/**
 * weather-route-service.js — ルート気象リスク取得・ナビバナー表示 (Phase2-D)
 *
 * ナビゲーション中にルート前方の気象リスクを定期評価し、
 * #nav-route-weather-banner に警告を表示する。
 *
 * DOM:
 *   #nav-route-weather-banner — 地図下部のルート気象バナー（ナビ中のみ）
 *
 * 外部から呼ぶ:
 *   _weatherRouteUpdate(route, lat, lon) — 位置更新時に呼ぶ（ナビ中のみ）
 *   _weatherRouteClear()                 — ルート終了・クリア時に呼ぶ
 *
 * 抑制設計:
 *   - 60秒フェッチ間隔（フロント側TTL）
 *   - 同一リスクレベルの繰り返しバナーは 90s クールダウン
 *   - ルート変更検出でクールダウン・dismissed をリセット
 *   - riskLevel=none/unknown はバナー非表示
 *   - emergency は dismissed 無効（常時表示）
 */

const _WRR_FETCH_TTL_MS  = 60_000;  // フロント側フェッチ間隔
const _WRR_COOLDOWN_MS   = 90_000;  // 同一レベル繰り返し抑制

let _wrrLastFetchAt  = 0;
let _wrrLastLevel    = 'none';
let _wrrLastLevelAt  = 0;
let _wrrRouteHash    = null;
let _wrrDismissed    = false;

function _wrrBanner() {
    return document.getElementById('nav-route-weather-banner');
}

function _wrrComputeRouteHash(route) {
    if (!route || !Array.isArray(route.coordinates) || route.coordinates.length === 0) return null;
    const coords = route.coordinates;
    const n      = coords.length;
    const pts    = [coords[0], coords[Math.floor(n / 2)], coords[n - 1]];
    return pts.map(p => `${(p.lat || 0).toFixed(4)},${(p.lng || 0).toFixed(4)}`).join('|');
}

function _wrrToGeoCoords(route) {
    if (!route || !Array.isArray(route.coordinates)) return null;
    return route.coordinates.map(c => [c.lng, c.lat]);  // [[lon, lat], ...]
}

function _wrrCurrentSegmentIndex(lat, lon, route) {
    if (!route || !Array.isArray(route.coordinates)) return 0;
    const coords = route.coordinates;
    let minDist = Infinity;
    let minIdx  = 0;
    for (let i = 0; i < coords.length; i++) {
        const dlat = coords[i].lat - lat;
        const dlng = coords[i].lng - lon;
        const d = dlat * dlat + dlng * dlng;
        if (d < minDist) { minDist = d; minIdx = i; }
    }
    return minIdx;
}

function _wrrHideBanner() {
    const banner = _wrrBanner();
    if (!banner) return;
    banner.style.display = 'none';
    banner.className = 'nav-route-weather-banner';
    banner.innerHTML = '';
}

function _wrrDefaultText(riskLevel) {
    if (riskLevel === 'emergency') return '進行方向で危険な降水を検出';
    if (riskLevel === 'warning')   return '進行方向で強雨リスク';
    if (riskLevel === 'advisory')  return '進行方向に雨域接近';
    return null;
}

function _wrrShowBanner(riskLevel, summary) {
    const banner = _wrrBanner();
    if (!banner) return;

    const text = (summary && summary.headline) || _wrrDefaultText(riskLevel);
    if (!text) { _wrrHideBanner(); return; }

    banner.className = 'nav-route-weather-banner nrw-banner--' + riskLevel;
    banner.innerHTML = '';

    const msg = document.createElement('span');
    msg.className = 'nrw-banner-text';
    msg.textContent = text;
    banner.appendChild(msg);

    if (riskLevel !== 'emergency') {
        const btn = document.createElement('button');
        btn.className = 'nrw-banner-close';
        btn.textContent = '×';
        btn.setAttribute('aria-label', '閉じる');
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            _wrrDismissed = true;
            _wrrHideBanner();
        });
        banner.appendChild(btn);
    }

    banner.style.display = 'flex';
}

async function _weatherRouteUpdate(route, lat, lon) {
    const hash = _wrrComputeRouteHash(route);
    if (!hash) { _wrrHideBanner(); return; }

    // ルート変更検出 → クールダウン・dismissed リセット
    if (hash !== _wrrRouteHash) {
        _wrrRouteHash   = hash;
        _wrrLastLevel   = 'none';
        _wrrLastLevelAt = 0;
        _wrrDismissed   = false;
        _wrrLastFetchAt = 0;  // 新ルートは即時フェッチ
    }

    const now = Date.now();
    if (now - _wrrLastFetchAt < _WRR_FETCH_TTL_MS) return;
    _wrrLastFetchAt = now;

    const geoCoords  = _wrrToGeoCoords(route);
    if (!geoCoords) return;
    const currentIdx = _wrrCurrentSegmentIndex(lat, lon, route);

    let data;
    try {
        const res = await fetch('/api/weather/risk/route', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ coordinates: geoCoords, current_segment_index: currentIdx }),
        });
        if (!res.ok) return;
        data = await res.json();
    } catch (err) {
        console.warn('[weather-route-service] fetch error:', err);
        return;
    }

    const riskLevel = (data || {}).risk_level || 'none';
    const summary   = (data || {}).summary    || {};

    if (riskLevel === 'none' || riskLevel === 'unknown') {
        _wrrHideBanner();
        _wrrLastLevel = riskLevel;
        return;
    }

    // 同一レベルのクールダウン（emergency は常時表示）
    if (riskLevel === _wrrLastLevel && riskLevel !== 'emergency') {
        if (now - _wrrLastLevelAt < _WRR_COOLDOWN_MS) return;
    }

    // レベル変化 → dismissed リセット
    if (riskLevel !== _wrrLastLevel) {
        _wrrDismissed = false;
    }

    _wrrLastLevel   = riskLevel;
    _wrrLastLevelAt = now;

    if (_wrrDismissed && riskLevel !== 'emergency') return;

    _wrrShowBanner(riskLevel, summary);
}

function _weatherRouteClear() {
    _wrrHideBanner();
    _wrrLastFetchAt  = 0;
    _wrrLastLevel    = 'none';
    _wrrLastLevelAt  = 0;
    _wrrRouteHash    = null;
    _wrrDismissed    = false;
}
