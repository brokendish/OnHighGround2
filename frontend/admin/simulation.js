'use strict';

// ── リスク色 ────────────────────────────────────────────────────────────────
const _SIM_RISK_COLOR = {
    none:      '#2e7d32',
    advisory:  '#b45309',
    warning:   '#c62828',
    emergency: '#b71c1c',
    unknown:   '#546e7a',
};
const _SIM_RISK_LABEL = {
    none:      '安全',
    advisory:  '注意',
    warning:   '警戒',
    emergency: '危険',
    unknown:   '判定不能',
};

// ── 定義済みシナリオ読み込み ─────────────────────────────────────────────────
async function loadScenarios() {
    const container = document.getElementById('scenario-buttons');
    try {
        const res = await fetch('/api/simulation/scenarios');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const scenarios = (data || {}).scenarios || [];
        container.innerHTML = '';
        scenarios.forEach(sc => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'sim-scenario-btn';
            btn.dataset.scenarioId = sc.scenario_id;
            btn.textContent = `[${sc.scenario_id}] ${sc.title}`;
            btn.addEventListener('click', () => applyScenario(sc));
            container.appendChild(btn);
        });
    } catch (err) {
        container.innerHTML = `<span style="color:#ef4444;font-size:12px;">シナリオ読み込みエラー: ${err.message}</span>`;
    }
}

function applyScenario(sc) {
    document.getElementById('p-origin-lon').value  = (sc.origin || [])[0] ?? '';
    document.getElementById('p-origin-lat').value  = (sc.origin || [])[1] ?? '';
    document.getElementById('p-dest-lon').value    = (sc.destination || [])[0] ?? '';
    document.getElementById('p-dest-lat').value    = (sc.destination || [])[1] ?? '';

    const w = sc.weather || {};
    document.getElementById('p-current-intensity').value  = w.current_intensity  || 'none';
    document.getElementById('p-forecast-intensity').value = w.forecast_max_intensity || 'none';
    document.getElementById('p-alert-severity').value     = w.alert_severity     || 'none';
    document.getElementById('p-weather-unknown').checked  = !!w.unknown;

    const h = sc.hazards || {};
    document.getElementById('p-h-lowland').checked      = !!h.lowland;
    document.getElementById('p-h-flood').checked        = !!h.flood;
    document.getElementById('p-h-inland-flood').checked = !!h.inland_flood;
    document.getElementById('p-h-landslide').checked    = !!h.landslide;
    document.getElementById('p-h-tsunami').checked      = !!h.tsunami;
    document.getElementById('p-h-storm-surge').checked  = !!h.storm_surge;
    document.getElementById('p-hazard-unavailable').checked = !!h.unavailable;

    // ハイライト
    document.querySelectorAll('.sim-scenario-btn').forEach(b => b.classList.remove('active'));
    const btn = document.querySelector(`.sim-scenario-btn[data-scenario-id="${sc.scenario_id}"]`);
    if (btn) btn.classList.add('active');
}

// ── フォームから request body を構築 ──────────────────────────────────────────
function buildRequestBody(scenarioId = 'manual') {
    return {
        scenario_id: scenarioId,
        origin:      [
            parseFloat(document.getElementById('p-origin-lon').value),
            parseFloat(document.getElementById('p-origin-lat').value),
        ],
        destination: [
            parseFloat(document.getElementById('p-dest-lon').value),
            parseFloat(document.getElementById('p-dest-lat').value),
        ],
        weather: {
            alert_severity:          document.getElementById('p-alert-severity').value,
            current_intensity:       document.getElementById('p-current-intensity').value,
            forecast_max_intensity:  document.getElementById('p-forecast-intensity').value,
            forecast_minutes:        30,
            unknown:                 document.getElementById('p-weather-unknown').checked,
        },
        hazards: {
            lowland:      document.getElementById('p-h-lowland').checked,
            flood:        document.getElementById('p-h-flood').checked,
            inland_flood: document.getElementById('p-h-inland-flood').checked,
            landslide:    document.getElementById('p-h-landslide').checked,
            tsunami:      document.getElementById('p-h-tsunami').checked,
            storm_surge:  document.getElementById('p-h-storm-surge').checked,
            unavailable:  document.getElementById('p-hazard-unavailable').checked,
        },
    };
}

// ── シミュレーション実行 ──────────────────────────────────────────────────────
async function runSimulation() {
    const btn = document.getElementById('run-btn');
    btn.disabled = true;
    btn.textContent = '実行中…';

    const resultsEl = document.getElementById('sim-results');
    resultsEl.innerHTML = '<div class="sim-loading">シミュレーション実行中…</div>';

    try {
        const body = buildRequestBody();
        const res = await fetch('/api/simulation/run', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderResults(resultsEl, data);
    } catch (err) {
        resultsEl.innerHTML = `<div class="sim-error">エラー: ${escHtml(err.message)}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'シミュレーション実行';
    }
}

// ── 結果レンダリング ──────────────────────────────────────────────────────────
function renderResults(container, data) {
    container.innerHTML = '';

    if (!data || data.status !== 'ok' || !Array.isArray(data.routes) || data.routes.length === 0) {
        const msg = (data && data.summary && data.summary.headline) || 'ルートを取得できません';
        container.innerHTML = `<div class="sim-unavailable">${escHtml(msg)}</div>`;
        return;
    }

    // サマリーバナー
    if (data.summary) {
        const banner = document.createElement('div');
        banner.className = 'sim-summary-banner';
        banner.innerHTML = `
            <div class="sim-summary-headline">${escHtml(data.summary.headline || '')}</div>
            <div class="sim-summary-message">${escHtml(data.summary.message || '')}</div>
        `;
        container.appendChild(banner);
    }

    const grid = document.createElement('div');
    grid.className = 'sim-result-grid';

    // ルートカード
    const cardsWrap = document.createElement('div');
    cardsWrap.className = 'sim-route-cards';
    data.routes.forEach(route => {
        cardsWrap.appendChild(buildRouteCard(route, data.recommended_route_index));
    });
    grid.appendChild(cardsWrap);

    // レイヤースタック
    if (Array.isArray(data.layer_stack) && data.layer_stack.length > 0) {
        grid.appendChild(buildLayerStack(data.layer_stack));
    }

    container.appendChild(grid);
}

function buildRouteCard(route, recIdx) {
    const isRec = route.index === recIdx;
    const color = _SIM_RISK_COLOR[route.risk_level] || '#64748b';
    const riskLabel = _SIM_RISK_LABEL[route.risk_level] || route.risk_level;
    const distKm = route.distance_m >= 1000
        ? `${(route.distance_m / 1000).toFixed(1)} km`
        : `${Math.round(route.distance_m)} m`;
    const durMin = Math.round(route.duration_s / 60);

    const card = document.createElement('div');
    card.className = 'sim-route-card' + (isRec ? ' sim-route-card--rec' : '');

    // ヘッダー行
    const header = document.createElement('div');
    header.className = 'sim-route-card-header';
    header.innerHTML = `
        <span class="sim-route-label">${escHtml(route.label)}${isRec ? ' <span class="sim-rec-badge">推奨</span>' : ''}${route.is_shortest ? ' <span class="sim-shortest-badge">最短</span>' : ''}</span>
        <span class="sim-route-score">安全度 <strong>${route.safety_score}</strong></span>
        <span class="sim-route-risk" style="color:${color};">${escHtml(riskLabel)}</span>
    `;
    card.appendChild(header);

    // 距離・時間
    const meta = document.createElement('div');
    meta.className = 'sim-route-meta';
    meta.textContent = `${distKm} / 約${durMin}分`;
    card.appendChild(meta);

    // リスクサマリー
    if (Array.isArray(route.risk_summary) && route.risk_summary.length > 0) {
        const sum = document.createElement('div');
        sum.className = 'sim-route-summary';
        sum.style.color = color;
        sum.textContent = route.risk_summary.join(' / ');
        card.appendChild(sum);
    }

    // 推奨理由
    if (route.recommendation_reason) {
        const reason = document.createElement('div');
        reason.className = 'sim-route-reason';
        reason.textContent = route.recommendation_reason;
        card.appendChild(reason);
    }

    // ペナルティ内訳
    if (Array.isArray(route.penalties) && route.penalties.length > 0) {
        const breakdown = document.createElement('div');
        breakdown.className = 'sim-penalty-breakdown';

        const title = document.createElement('div');
        title.className = 'sim-penalty-title';
        title.textContent = 'ペナルティ内訳';
        breakdown.appendChild(title);

        let totalPenalty = 0;
        route.penalties.forEach(p => {
            totalPenalty += p.points || 0;
            const row = document.createElement('div');
            row.className = 'sim-penalty-item';
            row.innerHTML = p.points > 0
                ? `<span class="sim-penalty-pts">+${p.points}</span><span class="sim-penalty-reason">${escHtml(p.reason)}</span>`
                : `<span class="sim-penalty-note">${escHtml(p.reason)}</span>`;
            breakdown.appendChild(row);
        });

        if (totalPenalty > 0) {
            const total = document.createElement('div');
            total.className = 'sim-penalty-total';
            total.innerHTML = `<span>= 安全度 ${route.safety_score}</span><span style="color:#64748b;font-size:11px;"> (100 - ${totalPenalty.toFixed(1)})</span>`;
            breakdown.appendChild(total);
        }

        card.appendChild(breakdown);
    }

    return card;
}

function buildLayerStack(layerStack) {
    const wrap = document.createElement('div');
    wrap.className = 'sim-layer-stack';

    const title = document.createElement('div');
    title.className = 'sim-layer-stack-title';
    title.textContent = 'Layer Stack';
    wrap.appendChild(title);

    layerStack.forEach(layer => {
        const row = document.createElement('div');
        row.className = 'sim-layer-row';
        const icon = layer.active === true ? '✓' : layer.active === false ? '–' : '?';
        const cls = layer.active === true ? 'sim-layer-on' : layer.active === false ? 'sim-layer-off' : 'sim-layer-unknown';
        row.innerHTML = `<span class="sim-layer-icon ${cls}">${icon}</span><span class="sim-layer-label">${escHtml(layer.label)}</span>`;
        wrap.appendChild(row);
    });

    return wrap;
}

// ── Auto-Run ─────────────────────────────────────────────────────────────────
async function runAuto() {
    const btn = document.getElementById('auto-run-btn');
    btn.disabled = true;
    btn.textContent = '実行中…';

    const modal = document.getElementById('auto-run-modal');
    const body  = document.getElementById('auto-run-modal-body');
    body.innerHTML = '<div class="sim-loading">一括実行中…</div>';
    modal.style.display = 'flex';

    try {
        const res = await fetch('/api/simulation/auto-run', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    '{}',
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderAutoRunResult(body, data);
    } catch (err) {
        body.innerHTML = `<div class="sim-error">エラー: ${escHtml(err.message)}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = '一括実行 (Auto-Run)';
    }
}

function renderAutoRunResult(container, data) {
    const passed = data.passed ?? 0;
    const failed = data.failed ?? 0;
    const total  = data.total  ?? 0;

    let html = `
        <div class="sim-autorun-summary ${failed === 0 ? 'sim-autorun-pass' : 'sim-autorun-fail'}">
            <strong>${failed === 0 ? '✅ ALL PASS' : `❌ ${failed} FAIL`}</strong>
            &nbsp; ${passed}/${total} PASS
        </div>
    `;

    if (data.report_path) {
        html += `<div class="sim-autorun-report">レポート: <code>${escHtml(data.report_path)}</code></div>`;
    }

    if (Array.isArray(data.results)) {
        html += '<table class="sim-autorun-table"><thead><tr><th>ID</th><th>タイトル</th><th>結果</th><th>risk_level</th><th>備考</th></tr></thead><tbody>';
        data.results.forEach(r => {
            const icon = r.status === 'pass' ? '✅' : r.status === 'fail' ? '❌' : '⏭';
            html += `<tr class="sim-autorun-row--${r.status}">
                <td>${escHtml(r.scenario_id)}</td>
                <td>${escHtml(r.title)}</td>
                <td>${icon} ${r.status}</td>
                <td>${escHtml(r.risk_level || '--')}</td>
                <td style="font-size:11px;color:#64748b;">${escHtml(r.fail_reason || '')}</td>
            </tr>`;
        });
        html += '</tbody></table>';
    }

    container.innerHTML = html;
}

// ── ユーティリティ ─────────────────────────────────────────────────────────────
function escHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── イベント登録 ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadScenarios();

    document.getElementById('run-btn').addEventListener('click', runSimulation);
    document.getElementById('auto-run-btn').addEventListener('click', runAuto);
    document.getElementById('auto-run-modal-close').addEventListener('click', () => {
        document.getElementById('auto-run-modal').style.display = 'none';
    });
    document.getElementById('auto-run-modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) e.currentTarget.style.display = 'none';
    });
});
