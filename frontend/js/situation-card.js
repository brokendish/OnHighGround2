'use strict';

/**
 * Phase 4-B: リアルタイム災害状況理解カード
 *
 * 公開API:
 *   situationCardOnKkkUpdate()               — キキクルリスク更新時（kikikuru-layer.js から）
 *   situationCardOnWeatherUpdate(precipInfo)  — 気象データ更新時（weather-card.js から）
 *   situationCardOnRouteUpdate(riskSummary)   — ルートリスク更新時（navigation.js から）
 *   situationCardClear()                      — ルートクリア時
 */

// ── 定数 ─────────────────────────────────────────────────────────────────────

const _SC_LEVEL_RANK = { danger: 4, caution: 3, none: 2, unavailable: 1, unknown: 1, off: 0 };

const _SC_PRECIP_RANK = { severe: 5, strong: 4, moderate: 3, weak: 2, none: 1, unknown: 0 };

const _SC_KIND_LABEL = { inund: '浸水キキクル', flood: '洪水キキクル', land: '土砂キキクル' };
const _SC_RISK_LEVEL_LABEL = { danger: '危険', caution: '注意' };
const _SC_ROUTE_LABEL = { safe: '問題なし', caution: '注意', danger: '危険', unknown: '不明' };

// ── ユーティリティ ─────────────────────────────────────────────────────────────

function _scEsc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// リスクオブジェクトから最大危険度レベルを返す
function _scMaxLevel(risk) {
    if (!risk || risk.status === 'off' || risk.status === 'loading') return 'off';
    if (risk.status === 'unavailable' || risk.status === 'unknown') return risk.status;
    let maxRank = 0;
    let maxLevel = 'none';
    for (const k of ['inund', 'flood', 'land']) {
        const lv = risk[k] || 'none';
        if ((_SC_LEVEL_RANK[lv] || 0) > maxRank) {
            maxRank = _SC_LEVEL_RANK[lv];
            maxLevel = lv;
        }
    }
    return maxLevel;
}

// 危険/注意のあるキキクル種別を「浸水キキクル: 危険」形式で返す
function _scActiveKindTexts(risk) {
    if (!risk || risk.status !== 'ok') return [];
    return Object.entries(_SC_KIND_LABEL)
        .filter(([k]) => risk[k] === 'danger' || risk[k] === 'caution')
        .map(([k, label]) => `${label}: ${_SC_RISK_LEVEL_LABEL[risk[k]]}`);
}

function _scLevelClass(level) {
    if (level === 'danger')      return 'sit-level--danger';
    if (level === 'caution')     return 'sit-level--caution';
    if (level === 'unavailable' || level === 'unknown') return 'sit-level--unavailable';
    return 'sit-level--none';
}

// ── 行動判断ロジック ─────────────────────────────────────────────────────────

function _scDetermineAction(currentLevel, destLevel, routeLevel, precipInfo) {
    const curRank  = _SC_LEVEL_RANK[currentLevel]  || 0;
    const destRank = _SC_LEVEL_RANK[destLevel]     || 0;

    const precipCur      = precipInfo?.current?.intensity || 'unknown';
    const precipFore     = precipInfo?.forecastStrongest  || null;
    const strongRain     = (_SC_PRECIP_RANK[precipCur] || 0) >= _SC_PRECIP_RANK.strong;
    const precipImproves = precipFore
        && (_SC_PRECIP_RANK[precipFore.intensity] || 0) < (_SC_PRECIP_RANK[precipCur] || 0)
        && precipFore.minutes <= 30;

    // 現在地が危険 + 目的地が注意以下 + ルートが通行可能 → 早めの移動
    if (currentLevel === 'danger'
            && destRank <= _SC_LEVEL_RANK.caution
            && routeLevel !== 'danger') {
        return { action: 'move', reason: '現在地周辺の危険度が上昇しています' };
    }

    // 目的地が危険 + 現在地が注意以下 → 待機を検討
    if (destLevel === 'danger' && curRank <= _SC_LEVEL_RANK.caution) {
        return { action: 'wait', reason: '目的地周辺で危険度が高まっています' };
    }

    // 強雨 + 近時間内に改善予測 → 待機を検討
    if (strongRain && precipImproves) {
        return {
            action: 'wait',
            reason: `雨が${precipFore.minutes}分後に弱まる予測があります`,
        };
    }

    // ルートが危険 + 現在地が注意以下 → 待機を検討
    if (routeLevel === 'danger' && curRank <= _SC_LEVEL_RANK.caution) {
        return { action: 'wait', reason: '現在のルートで危険度が高い区間があります' };
    }

    return null;
}

// ── 状態 ─────────────────────────────────────────────────────────────────────

let _scPrecipInfo = null;
let _scRouteRisk  = null;

// ── レンダリング ─────────────────────────────────────────────────────────────

function _scRender() {
    const section = document.getElementById('sit-card-section');
    if (!section) return;

    // キキクルスナップショット取得
    const snap = typeof kikikuruGetRiskSnapshot === 'function'
        ? kikikuruGetRiskSnapshot()
        : { current: { status: 'off' }, dest: { status: 'off' }, route: { status: 'off' } };

    const currentRisk = snap.current;
    const destRisk    = snap.dest;

    const currentLevel = _scMaxLevel(currentRisk);
    const destLevel    = _scMaxLevel(destRisk);
    const routeLevel   = _scRouteRisk?.risk_level || null;
    const kkkAdj       = _scRouteRisk?.kikikuru_adjustment || null;

    // ルートまたは目的地が設定されていなければ非表示
    const hasRoute = routeLevel !== null || destRisk.status !== 'off';
    if (!hasRoute) {
        section.style.display = 'none';
        return;
    }
    section.style.display = '';

    // 行動推奨
    const action = _scDetermineAction(currentLevel, destLevel, routeLevel, _scPrecipInfo);

    // ── ヘッダーバッジ ───────────────────────────────────────────────────────
    const badge = document.getElementById('sit-action-badge');
    if (badge) {
        if (action?.action === 'wait') {
            badge.textContent = '待機検討';
            badge.className   = 'sit-action-badge sit-badge--wait';
            badge.style.display = '';
        } else if (action?.action === 'move') {
            badge.textContent = '早めの移動検討';
            badge.className   = 'sit-action-badge sit-badge--move';
            badge.style.display = '';
        } else {
            badge.style.display = 'none';
        }
    }

    // ── 本文 ────────────────────────────────────────────────────────────────
    const body = document.getElementById('sit-card-body');
    if (!body) return;
    let html = '';

    // 現在地行
    html += _scRowHtml('現在地', currentRisk, currentLevel);

    // 目的地行（設定済みの場合のみ）
    if (destRisk.status !== 'off') {
        html += _scRowHtml('目的地', destRisk, destLevel);
    }

    // ルート行
    if (routeLevel) {
        const routeClass = _scLevelClass(routeLevel === 'safe' ? 'none' : routeLevel === 'unknown' ? 'unavailable' : routeLevel);
        html += `<div class="sit-row">`;
        html += `<span class="sit-row-label">ルート</span>`;
        html += `<span class="sit-row-val ${routeClass}">${_scEsc(_SC_ROUTE_LABEL[routeLevel] || routeLevel)}</span>`;
        html += '</div>';
    }

    // 降水行
    if (_scPrecipInfo?.current) {
        const cur    = _scPrecipInfo.current;
        const fore   = _scPrecipInfo.forecastStrongest;
        const pIntensity = cur.intensity || 'none';
        const pClass  = ['strong', 'severe'].includes(pIntensity) ? 'sit-level--danger'
                      : pIntensity === 'moderate' ? 'sit-level--caution' : 'sit-level--none';
        html += '<div class="sit-row">';
        html += '<span class="sit-row-label">降水</span>';
        html += `<span class="sit-row-val ${pClass}">${_scEsc(cur.label || cur.intensity || '不明')}</span>`;
        if (fore) {
            html += `<span class="sit-precip-forecast">${fore.minutes}分後: ${_scEsc(fore.label || fore.intensity)}</span>`;
        }
        if (_scPrecipInfo.stale) {
            // 前回取得データ: 最新値と誤認させない
            html += '<span class="sit-precip-stale">（前回取得データ）</span>';
        }
        html += '</div>';
    } else if (_scPrecipInfo?.unavailable) {
        // 降水の取得失敗: 行ごと消さず「取得できません」を明示（降水なしと区別）
        html += '<div class="sit-row">';
        html += '<span class="sit-row-label">降水</span>';
        html += '<span class="sit-row-val sit-level--unavailable">取得できません</span>';
        html += '</div>';
    }

    // キキクル重複情報
    if (kkkAdj?.enabled && kkkAdj.penalty > 0
            && Array.isArray(kkkAdj.matched_hazards) && kkkAdj.matched_hazards.length > 0) {
        const names = kkkAdj.matched_hazards
            .map(h => typeof getHazardDisplayName === 'function' ? getHazardDisplayName(h) : h)
            .join('・');
        html += `<div class="sit-overlap">固定ハザード（${_scEsc(names)}）とキキクルが重なっています</div>`;
    }

    // 行動推奨ブロック
    if (action) {
        const actionLabel = action.action === 'wait'
            ? '可能であれば待機を検討してください'
            : '可能であれば早めの移動を検討してください';
        html += `<div class="sit-action-block sit-action--${action.action}">`;
        html += `<div class="sit-action-reason">${_scEsc(action.reason)}</div>`;
        html += `<div class="sit-action-label">${actionLabel}</div>`;
        html += '</div>';
    }

    body.innerHTML = html;
}

function _scRowHtml(label, risk, level) {
    const kinds = _scActiveKindTexts(risk);
    let valHtml;
    if (risk.status === 'off' || risk.status === 'loading') {
        valHtml = '<span class="sit-row-val sit-level--none">取得前</span>';
    } else if (level === 'unavailable') {
        valHtml = '<span class="sit-row-val sit-level--unavailable">取得不可（安全を意味しません）</span>';
    } else if (level === 'unknown') {
        valHtml = '<span class="sit-row-val sit-level--unavailable">判定不可（安全を意味しません）</span>';
    } else if (kinds.length > 0) {
        valHtml = `<span class="sit-row-val ${_scLevelClass(level)}">${_scEsc(kinds.join(' / '))}</span>`;
    } else {
        valHtml = '<span class="sit-row-val sit-level--none">リスク検出なし</span>';
    }
    return `<div class="sit-row"><span class="sit-row-label">${_scEsc(label)}</span>${valHtml}</div>`;
}

// ── 公開API ───────────────────────────────────────────────────────────────────

function situationCardOnKkkUpdate() {
    _scRender();
}

function situationCardOnWeatherUpdate(precipInfo) {
    _scPrecipInfo = precipInfo || null;
    _scRender();
}

function situationCardOnRouteUpdate(riskSummary) {
    _scRouteRisk = riskSummary || null;
    _scRender();
}

function situationCardClear() {
    _scRouteRisk  = null;
    _scPrecipInfo = null;
    const section = document.getElementById('sit-card-section');
    if (section) section.style.display = 'none';
    const badge = document.getElementById('sit-action-badge');
    if (badge) badge.style.display = 'none';
}
