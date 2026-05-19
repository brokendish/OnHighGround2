'use strict';

/**
 * route-ui.js — ルート比較UI (Phase3-A)
 *
 * POST /api/navigation/route/compare からの気象×ハザード比較結果を受け取り、
 * #lip-route-weather-compare に比較カードを表示する。
 *
 * 重要:
 *   - 自動 reroute は行わない（比較提示のみ）
 *   - unknown を none に倒さない
 *   - route churn 抑制: safety_score 差 < 10 の場合は推奨変更しない
 *
 * 外部から呼ぶ:
 *   _routeUiFetchAndShow(origin, destination, selectedIdx) — 比較取得・表示
 *   _routeUiClearComparison()                              — 比較クリア
 *   _routeUiOnRouteSelected(selectedIdx)                   — 選択変更時の再描画
 */

const _RUI_COOLDOWN_MS      = 60_000;  // フェッチ間隔
const _RUI_CHURN_THRESHOLD  = 10;      // 推奨変更のスコア差閾値

let _ruiLastFetchAt       = 0;
let _ruiLastRecommended   = null;
let _ruiLastRecScore      = null;
let _ruiComparison        = null;  // 最新の比較データ

function _ruiSection() {
    return document.getElementById('lip-route-weather-compare');
}

function _ruiHide() {
    const el = _ruiSection();
    if (!el) return;
    el.innerHTML = '';
    el.style.display = 'none';
}

// /api/route-risk 語彙（safe/caution/danger）と
// /api/navigation/route/compare 語彙（none/advisory/warning/emergency）を両方サポート
const _RUI_RISK_COLOR = {
    none:      '#2e7d32', safe:    '#2e7d32',
    advisory:  '#b45309', caution: '#b45309',
    warning:   '#c62828', danger:  '#c62828',
    emergency: '#b71c1c',
    unknown:   '#64748b',
};

const _RUI_RISK_LABEL = {
    none:      '安全', safe:    '安全',
    advisory:  '注意', caution: '注意',
    warning:   '警戒', danger:  '警戒',
    emergency: '危険',
    unknown:   '判定不能',
};

function _ruiRender(data, selectedIdx) {
    const el = _ruiSection();
    if (!el) return;

    if (!data || data.status === 'unavailable' || !Array.isArray(data.routes) || data.routes.length === 0) {
        _ruiHide();
        return;
    }

    const routes     = data.routes;
    const recIdx     = data.recommended_route_index ?? 0;

    // 全ルートが同一リスク・スコア差小さい場合はカード非表示（静かにする）
    const _SAFE_LEVELS = new Set(['none', 'safe', 'unknown']);
    const hasRisk    = routes.some(r => !_SAFE_LEVELS.has(r.risk_level));
    const shortest   = routes.reduce((a, b) => (a.distance_m <= b.distance_m ? a : b));
    const recRoute   = routes[recIdx];
    const isChurning = routes.length <= 1;
    if (!hasRisk && !isChurning && recIdx === shortest.index) {
        _ruiHide();
        return;
    }

    el.innerHTML = '';

    // ヘッダー
    const header = document.createElement('div');
    header.className = 'rui-compare-header';
    header.textContent = 'ルート気象・ハザード比較';
    el.appendChild(header);

    routes.forEach((route, i) => {
        const row = document.createElement('div');
        row.className = 'rui-compare-row';
        if (i === selectedIdx)   row.classList.add('rui-compare-row--selected');
        if (i === recIdx)        row.classList.add('rui-compare-row--recommended');

        // ルートラベル（ルート選択ボタンの「候補N」と統一）
        const badge = `候補${i + 1}`;
        const riskLabel = _RUI_RISK_LABEL[route.risk_level] || route.risk_level;
        const riskColor = _RUI_RISK_COLOR[route.risk_level] || '#64748b';

        const topLine = document.createElement('div');
        topLine.className = 'rui-compare-topline';
        topLine.innerHTML =
            `<span class="rui-compare-badge">${String.fromCharCode(65 + i)}: ${badge}</span>` +
            `<span class="rui-compare-score">安全度 ${Math.round(route.safety_score)}</span>` +
            `<span class="rui-compare-risk" style="color:${riskColor};">${riskLabel}</span>`;
        row.appendChild(topLine);

        if (Array.isArray(route.risk_summary) && route.risk_summary.length > 0) {
            const summaryEl = document.createElement('div');
            summaryEl.className = 'rui-compare-summary';
            summaryEl.style.color = riskColor;
            summaryEl.textContent = route.risk_summary.join(' / ');
            row.appendChild(summaryEl);
        }

        el.appendChild(row);
    });

    // 推奨が最短でなく、かつリスク差がある場合のみ補足メッセージ
    if (recRoute && recIdx !== shortest.index && hasRisk) {
        const distDiff = Math.round(((recRoute.distance_m - shortest.distance_m) / 10)) * 10;
        if (distDiff > 0) {
            const msg = document.createElement('div');
            msg.className = 'rui-compare-msg';
            msg.textContent = `推奨ルートは最短より${distDiff}m長いですが、安全寄りです`;
            el.appendChild(msg);
        }
    }

    el.style.display = '';
}

async function _routeUiFetchAndShow(origin, destination, selectedIdx) {
    if (!Array.isArray(origin) || origin.length < 2) return;
    if (!Array.isArray(destination) || destination.length < 2) return;

    const now = Date.now();

    // フェッチ間隔チェック（ただし origin/destination が変わった場合はリセット済み）
    if (now - _ruiLastFetchAt < _RUI_COOLDOWN_MS) {
        if (_ruiComparison) _ruiRender(_ruiComparison, selectedIdx);
        return;
    }
    _ruiLastFetchAt = now;

    let data;
    try {
        const res = await fetch('/api/navigation/route/compare', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ origin, destination }),
        });
        if (!res.ok) return;
        data = await res.json();
    } catch (err) {
        console.warn('[route-ui] comparison fetch error:', err);
        return;
    }

    if (!data || data.status === 'unavailable') {
        _ruiHide();
        _ruiComparison = null;
        return;
    }

    // Churn 抑制: 推奨が変わるがスコア差が閾値未満 → 推奨を維持
    const newRec = data.recommended_route_index ?? 0;
    if (_ruiLastRecommended !== null && newRec !== _ruiLastRecommended) {
        const newScore = (data.routes[newRec] || {}).safety_score ?? 0;
        const oldScore = _ruiLastRecScore ?? 0;
        if (Math.abs(newScore - oldScore) < _RUI_CHURN_THRESHOLD) {
            data.recommended_route_index = _ruiLastRecommended;
        }
    }

    _ruiLastRecommended = data.recommended_route_index;
    _ruiLastRecScore    = (data.routes[data.recommended_route_index] || {}).safety_score ?? null;
    _ruiComparison      = data;

    _ruiRender(data, selectedIdx);
}

function _routeUiOnRouteSelected(selectedIdx) {
    if (_ruiComparison) _ruiRender(_ruiComparison, selectedIdx);
}

function _routeUiClearComparison() {
    _ruiHide();
    _ruiLastFetchAt     = 0;
    _ruiLastRecommended = null;
    _ruiLastRecScore    = null;
    _ruiComparison      = null;
}

/**
 * navigation.js が評価済みの route candidates から直接比較カードを描画する。
 * /api/navigation/route/compare への独立フェッチを行わず、
 * route.__riskSummary（/api/route-risk 結果）を単一ソースとして使用。
 * これにより「ルート選択」と「ルート気象・ハザード比較」のスコアが必ず一致する。
 *
 * @param {object[]} candidateRoutes - _lipRouteSelection.routes 相当のルート配列
 * @param {number}   selectedIdx     - 現在選択中のルートインデックス
 */
function routeUiShowFromCandidates(candidateRoutes, selectedIdx) {
    if (!Array.isArray(candidateRoutes) || candidateRoutes.length < 2) {
        _ruiHide();
        return;
    }

    const routes = candidateRoutes.map((route, i) => {
        const rs    = route?.__riskSummary || {};
        const notes = rs.risk_summary?.notes || [];
        const score = typeof rs.safety_score === 'number' ? rs.safety_score : 100;
        const level = rs.risk_level || 'safe';
        const dist  = Math.round(Number(route?.summary?.totalDistance ?? route?.totalDistance ?? 0));
        const dur   = Math.round(Number(route?.summary?.totalTime    ?? route?.totalTime    ?? 0));

        console.log('[route-ui] candidate', i, {
            route_id:   i,
            score,
            risk_level: level,
            selected:   i === selectedIdx,
        });

        return {
            index:        i,
            distance_m:   dist,
            duration_s:   dur,
            risk_level:   level,
            safety_score: score,
            risk_summary: notes,
            status:       rs.risk_level ? 'ok' : 'unknown',
        };
    });

    const data = {
        status:                  'ok',
        recommended_route_index: 0,  // navigation.js ランク済み: index 0 が推奨
        routes,
    };

    _ruiComparison  = data;
    _ruiLastFetchAt = Date.now();
    _ruiRender(data, selectedIdx);
}
