'use strict';

/**
 * Phase 4-A: ナビ中前方危険警告パネル
 *
 * 公開API:
 *   navForwardWarningUpdate(riskSummary, sampledPoints) — ルートリスク評価後に呼ぶ
 *   navForwardWarningClear()                            — ナビ停止時に呼ぶ
 *   navForwardWarningDismiss()                          — 閉じるボタンから呼ぶ
 */

// 簡易 haversine（メートル返却）
function _nfwDistM(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const φ1 = lat1 * Math.PI / 180, φ2 = lat2 * Math.PI / 180;
    const dφ = (lat2 - lat1) * Math.PI / 180;
    const dλ = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(dλ / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function _nfwFormatDist(m) {
    if (m < 150)  return '約100m以内';
    if (m < 375)  return '約250m先';
    if (m < 750)  return '約500m先';
    if (m < 1500) return '約1km先';
    return `約${Math.round(m / 500) * 500 / 1000}km先`;
}

function _nfwNearestDangerM(sampledPoints) {
    // currentLocation は navigation.js / app.js のグローバル変数
    const pos = typeof currentLocation !== 'undefined' ? currentLocation : null;
    if (!pos || !Array.isArray(sampledPoints) || sampledPoints.length === 0) return null;
    let minD = Infinity;
    for (const pt of sampledPoints) {
        if (!pt || typeof pt.lat !== 'number' || typeof pt.lon !== 'number') continue;
        if (Object.values(pt.hazards || {}).includes('inside')) {
            const d = _nfwDistM(pos.lat, pos.lon, pt.lat, pt.lon);
            if (d < minD) minD = d;
        }
    }
    return isFinite(minD) ? minD : null;
}

function _nfwEsc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// sampled_points から inside のハザード種別名を返す（露出度降順）
function _nfwActiveHazardNames(sampledPoints) {
    if (!Array.isArray(sampledPoints)) return [];
    const counts = {};
    for (const pt of sampledPoints) {
        for (const [h, v] of Object.entries(pt.hazards || {})) {
            if (v === 'inside') counts[h] = (counts[h] || 0) + 1;
        }
    }
    return Object.keys(counts)
        .sort((a, b) => counts[b] - counts[a])
        .map(h => typeof getHazardDisplayName === 'function' ? getHazardDisplayName(h) : h);
}

// 警告レベルを決定: null=非表示 / 'unavailable' / 'unknown' / 'caution' / 'danger'
function _nfwDetermineLevel(riskSummary) {
    if (!riskSummary) return null;
    const rl  = riskSummary.risk_level;
    const adj = riskSummary.kikikuru_adjustment;

    let level = null;
    if (rl === 'danger')  level = 'danger';
    else if (rl === 'caution') level = 'caution';

    if (adj?.enabled) {
        if ((adj.status === 'unavailable' || adj.status === 'unknown') && !level) {
            level = adj.status;
        } else if (adj.penalty > 0) {
            const adjLvl = adj.max_level === 'danger' ? 'danger' : 'caution';
            if (!level || (adjLvl === 'danger' && level !== 'danger')) level = adjLvl;
        }
    }
    return level;
}

function _nfwBuildHtml(level, riskSummary, sampledPoints) {
    const adj         = riskSummary.kikikuru_adjustment;
    const dist        = _nfwNearestDangerM(sampledPoints);
    const distText    = dist != null ? `この先 ${_nfwFormatDist(dist)}` : '前方ルート上';
    const hazardNames = _nfwActiveHazardNames(sampledPoints);

    let html = '<div class="nfw-inner">';
    html += '<button class="nfw-close" onclick="navForwardWarningDismiss()" aria-label="閉じる">✕</button>';

    if (level === 'unavailable' || level === 'unknown') {
        html += '<div class="nfw-title">⚠ キキクル判定不可</div>';
        html += `<div class="nfw-dist">${_nfwEsc(distText)}</div>`;
        html += `<div class="nfw-msg">${level === 'unavailable'
            ? 'キキクル情報を取得できませんでした'
            : 'キキクル情報を判定できませんでした'}</div>`;
        html += '<div class="nfw-note">安全を意味するものではありません</div>';
    } else {
        const isDanger = level === 'danger';
        html += `<div class="nfw-title">${isDanger
            ? '⚠ 前方で危険度が高まっています'
            : '⚠ 前方に注意が必要です'}</div>`;
        html += `<div class="nfw-dist">${_nfwEsc(distText)}</div>`;

        // 主要ハザード説明
        if (hazardNames.length > 0) {
            html += `<div class="nfw-msg">${_nfwEsc(hazardNames.slice(0, 2).join('・'))}リスクが上昇しています</div>`;
        } else if (isDanger) {
            html += '<div class="nfw-msg">ルート上で危険度が高い区間があります</div>';
        } else {
            html += '<div class="nfw-msg">ルート上で注意が必要な区間があります</div>';
        }

        // キキクル重複説明
        const hasKkkOverlap = adj?.enabled && adj.penalty > 0 &&
            Array.isArray(adj.matched_hazards) && adj.matched_hazards.length > 0;
        if (hasKkkOverlap) {
            const kkkHazards = adj.matched_hazards
                .map(h => typeof getHazardDisplayName === 'function' ? getHazardDisplayName(h) : h)
                .join('・');
            html += `<div class="nfw-overlap">固定ハザード（${_nfwEsc(kkkHazards)}）とキキクルが重なっています</div>`;
        } else if (adj?.enabled && adj.penalty > 0) {
            html += '<div class="nfw-overlap">リアルタイム危険度情報が反映されています</div>';
        }

        html += `<div class="nfw-note">${isDanger
            ? '安全を確認しながら移動してください'
            : '周囲の状況に注意してください'}</div>`;
    }

    html += '</div>';
    return html;
}

let _nfwCurrentRisk   = null;
let _nfwCurrentPoints = null;
let _nfwDismissed     = false;

function _nfwIsNavigating() {
    return typeof navigationMode !== 'undefined'
        && ['navigation_active', 'navigation_warning', 'navigation_paused'].includes(navigationMode);
}

function _nfwRender() {
    const el = document.getElementById('nav-forward-warning');
    if (!el) return;

    const level = _nfwDetermineLevel(_nfwCurrentRisk);
    if (!level || _nfwDismissed || !_nfwIsNavigating()) {
        el.style.display = 'none';
        return;
    }

    el.className  = `nav-fwd-warning nav-fwd-warning--${level}`;
    el.innerHTML  = _nfwBuildHtml(level, _nfwCurrentRisk, _nfwCurrentPoints);
    el.style.display = 'block';
    el.setAttribute('role', 'alert');
}

// ── 公開API ───────────────────────────────────────────────────────────────────

function navForwardWarningUpdate(riskSummary, sampledPoints) {
    const prevLevel = _nfwDetermineLevel(_nfwCurrentRisk);
    _nfwCurrentRisk   = riskSummary   || null;
    _nfwCurrentPoints = sampledPoints || null;
    // 警告レベルが変わったら dismiss 解除（新しい状況を伝える）
    if (_nfwDetermineLevel(_nfwCurrentRisk) !== prevLevel) _nfwDismissed = false;
    _nfwRender();
}

function navForwardWarningClear() {
    _nfwCurrentRisk   = null;
    _nfwCurrentPoints = null;
    _nfwDismissed     = false;
    const el = document.getElementById('nav-forward-warning');
    if (el) { el.style.display = 'none'; el.innerHTML = ''; }
}

function navForwardWarningDismiss() {
    _nfwDismissed = true;
    const el = document.getElementById('nav-forward-warning');
    if (el) el.style.display = 'none';
}

function navForwardWarningRefresh() {
    _nfwRender();
}
