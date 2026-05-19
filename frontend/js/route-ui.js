'use strict';

/**
 * route-ui.js — ルート比較UI (Phase3-A)
 *
 * 評価済み route candidates を受け取り、#lip-route-weather-compare に比較カードを表示する。
 *
 * 重要:
 *   - 自動 reroute は行わない（比較提示のみ）
 *   - unknown を none に倒さない
 *
 * 外部から呼ぶ:
 *   _routeUiFetchAndShow(origin, destination, selectedIdx) — 後方互換stub（独立fetch禁止）
 *   _routeUiClearComparison()                              — 比較クリア
 *   _routeUiOnRouteSelected(selectedIdx)                   — 選択変更時の再描画
 */

let _ruiLastFetchAt       = 0;
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

    const selectedRouteId = data.selected_route_id;
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
        const isSelected = selectedRouteId !== undefined && selectedRouteId !== null
            ? route.route_id === selectedRouteId
            : (route.selected === true || i === selectedIdx);
        const isRecommended = route.recommended || i === recIdx;
        if (isSelected)      row.classList.add('rui-compare-row--selected');
        if (isRecommended)   row.classList.add('rui-compare-row--recommended');

        // ルートラベル（ルート選択ボタンの「候補N」と統一）
        const badge = route.label || `候補${i + 1}`;
        const riskLabel = _RUI_RISK_LABEL[route.risk_level] || route.risk_level;
        const riskColor = _RUI_RISK_COLOR[route.risk_level] || '#64748b';
        const scoreText = typeof formatRouteSafetyScore === 'function'
            ? formatRouteSafetyScore(route.safety_score)
            : String(route.safety_score ?? '');

        console.log('[route-ui]', {
            surface: 'comparison',
            route_id: route.route_id,
            label: badge,
            score: route.safety_score,
            risk_level: route.risk_level,
            selected: isSelected,
            recommended: isRecommended,
        });

        const topLine = document.createElement('div');
        topLine.className = 'rui-compare-topline';
        topLine.innerHTML =
            `<span class="rui-compare-badge">${String.fromCharCode(65 + i)}: ${badge}</span>` +
            `<span class="rui-compare-score">安全度 ${scoreText || '—'}</span>` +
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
    console.warn('[route-ui] _routeUiFetchAndShow is disabled; use routeUiShowFromCandidates(routeCandidates, selectedIdx).');
    if (_ruiComparison) {
        _ruiRender(_ruiComparison, selectedIdx);
        return;
    }
    _ruiHide();
}

function _routeUiOnRouteSelected(selectedIdx) {
    if (!_ruiComparison) return;
    const selectedRoute = _ruiComparison.routes?.[selectedIdx] || null;
    if (selectedRoute) {
        _ruiComparison.selected_route_id = selectedRoute.route_id;
        _ruiComparison.routes.forEach(route => {
            route.selected = route.route_id === selectedRoute.route_id;
        });
    }
    _ruiRender(_ruiComparison, selectedIdx);
}

function _routeUiClearComparison() {
    _ruiHide();
    _ruiLastFetchAt     = 0;
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

    const selectedRoute = candidateRoutes[selectedIdx] || null;
    const selectedBaseModel = typeof createRoutePresentationModel === 'function'
        ? createRoutePresentationModel(selectedRoute, { index: selectedIdx, selectedRouteIndex: selectedIdx })
        : null;
    const selectedRouteId = selectedBaseModel?.route_id ?? selectedIdx;
    const routes = candidateRoutes.map((route, i) => (
        typeof createRoutePresentationModel === 'function'
            ? createRoutePresentationModel(route, { index: i, selectedRouteId })
            : {
                route_id: i,
                label: `候補${i + 1}`,
                distance_m: Number(route?.summary?.totalDistance ?? route?.totalDistance),
                duration_s: Number(route?.summary?.totalTime ?? route?.totalTime),
                risk_level: route?.__riskSummary?.risk_level || 'unknown',
                safety_score: route?.__riskSummary?.safety_score ?? null,
                risk_summary: route?.__riskSummary?.risk_summary?.notes || [],
                selected: i === selectedIdx,
                recommended: i === 0,
            }
    ));
    const recommendedIndex = routes.findIndex(route => route.recommended);

    const data = {
        status:                  'ok',
        selected_route_id:       selectedRouteId,
        recommended_route_index: recommendedIndex >= 0 ? recommendedIndex : 0,
        routes,
    };

    _ruiComparison  = data;
    _ruiLastFetchAt = Date.now();
    _ruiRender(data, selectedIdx);
}
