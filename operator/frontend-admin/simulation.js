'use strict';

// ── キキクルシナリオ定義 ─────────────────────────────────────────────────────
const _KKK_SIM_SCENARIOS = {
    none:         { label: 'なし',         status: 'ok',          values: { inund: 'none',    flood: 'none',    land: 'none' } },
    inund_caution:{ label: '浸水 注意',    status: 'ok',          values: { inund: 'caution', flood: 'none',    land: 'none' } },
    inund_danger: { label: '浸水 危険',    status: 'ok',          values: { inund: 'danger',  flood: 'none',    land: 'none' } },
    flood_caution:{ label: '洪水 注意',    status: 'ok',          values: { inund: 'none',    flood: 'caution', land: 'none' } },
    flood_danger: { label: '洪水 危険',    status: 'ok',          values: { inund: 'none',    flood: 'danger',  land: 'none' } },
    land_caution: { label: '土砂 注意',    status: 'ok',          values: { inund: 'none',    flood: 'none',    land: 'caution' } },
    land_danger:  { label: '土砂 危険',    status: 'ok',          values: { inund: 'none',    flood: 'none',    land: 'danger' } },
    three_caution:{ label: '3種同時 注意', status: 'ok',          values: { inund: 'caution', flood: 'caution', land: 'caution' } },
    three_danger: { label: '3種同時 危険', status: 'ok',          values: { inund: 'danger',  flood: 'danger',  land: 'danger' } },
    unavailable:  { label: '取得不可',     status: 'unavailable', values: null },
    unknown:      { label: '判定不可',     status: 'unknown',     values: null },
    current_danger_dest_caution: {
        label: '現在地危険 / 目的地注意',
        status: 'ok',
        values: { inund: 'none', flood: 'danger', land: 'none' },
        situation: {
            current: { inund: 'none', flood: 'danger', land: 'none' },
            destination: { inund: 'none', flood: 'caution', land: 'none' },
            route: '注意',
            action: 'move',
            reason: '現在地周辺の危険度が上昇しています',
        },
    },
    current_caution_dest_danger: {
        label: '現在地注意 / 目的地危険',
        status: 'ok',
        values: { inund: 'none', flood: 'danger', land: 'none' },
        situation: {
            current: { inund: 'none', flood: 'caution', land: 'none' },
            destination: { inund: 'none', flood: 'danger', land: 'none' },
            route: '注意',
            action: 'wait',
            reason: '目的地周辺で洪水リスクが高まっています',
        },
    },
    improve_20min: {
        label: '20分後改善',
        status: 'ok',
        values: { inund: 'none', flood: 'caution', land: 'none' },
        situation: {
            current: { inund: 'none', flood: 'caution', land: 'none' },
            destination: { inund: 'none', flood: 'caution', land: 'none' },
            rain: '強い雨',
            time: '20分後: 雨が弱まる予測',
            action: 'wait',
            reason: '雨が20分後に弱まる予測があります',
        },
    },
    strong_rain_continues: {
        label: '強雨継続',
        status: 'ok',
        values: { inund: 'caution', flood: 'none', land: 'none' },
        situation: {
            current: { inund: 'caution', flood: 'none', land: 'none' },
            destination: { inund: 'caution', flood: 'none', land: 'none' },
            rain: '強い雨',
            time: '20分後も強い雨の見込み',
        },
    },
};

const _KKK_LEVEL_LABEL = { none: 'なし', caution: '注意', danger: '危険', unavailable: '取得不可', unknown: '判定不可' };

let _kkkSimState = null;
let _kkkPreviewRequestToken = 0;

// ── リスク色・ラベル ──────────────────────────────────────────────────────────
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

// ── 地図初期化 ────────────────────────────────────────────────────────────────
let _mapAvailable = false;

function initMap() {
    // マップコントロールボタンのイベント登録は地図の有無に関わらず行う
    document.querySelectorAll('.sim-map-ctrl-btn[data-mode]').forEach(btn => {
        btn.addEventListener('click', () => {
            const mode = btn.dataset.mode;
            const isActive = btn.classList.contains('active');
            document.querySelectorAll('.sim-map-ctrl-btn[data-mode]').forEach(b => b.classList.remove('active'));
            if (isActive) {
                if (_mapAvailable) SimMap.setClickMode(null);
            } else {
                btn.classList.add('active');
                if (_mapAvailable) SimMap.setClickMode(mode);
            }
        });
    });

    document.getElementById('btn-fit-map').addEventListener('click', () => {
        if (_mapAvailable) SimMap.fitToMarkers();
    });

    document.getElementById('btn-inspect-close').addEventListener('click', () => {
        document.getElementById('sim-inspect-panel').style.display = 'none';
        if (_mapAvailable) SimMap.clearInspect();
    });

    // Leaflet 地図初期化 (失敗してもその他の UI は動作させる)
    try {
        SimMap.init('sim-map', {
            onMarkerUpdate: (type, lat, lon) => {
                if (type === 'start') {
                    document.getElementById('p-origin-lat').value = lat.toFixed(6);
                    document.getElementById('p-origin-lon').value = lon.toFixed(6);
                    if (_mapAvailable && _kkkSimState) SimMap.drawKikikuruOverlay(_kkkSimState);
                } else if (type === 'goal') {
                    document.getElementById('p-dest-lat').value = lat.toFixed(6);
                    document.getElementById('p-dest-lon').value = lon.toFixed(6);
                }
                _kkkRouteRiskPreview();
            },
            onInspect: (lat, lon) => {
                runPointInspect(lat, lon);
            },
        });

        const oLon = parseFloat(document.getElementById('p-origin-lon').value);
        const oLat = parseFloat(document.getElementById('p-origin-lat').value);
        const dLon = parseFloat(document.getElementById('p-dest-lon').value);
        const dLat = parseFloat(document.getElementById('p-dest-lat').value);
        if (oLat && oLon) SimMap.placeMarker('start', oLat, oLon);
        if (dLat && dLon) SimMap.placeMarker('goal',  dLat, dLon);

        _mapAvailable = true;
    } catch (err) {
        console.warn('SimMap init failed, continuing without map:', err);
        const mapEl = document.getElementById('sim-map');
        if (mapEl) mapEl.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:13px;">地図の読み込みに失敗しました</div>';
    }
}

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

    // 地図マーカー更新
    if (_mapAvailable) {
        const oLon = parseFloat((sc.origin || [])[0]);
        const oLat = parseFloat((sc.origin || [])[1]);
        const dLon = parseFloat((sc.destination || [])[0]);
        const dLat = parseFloat((sc.destination || [])[1]);
        if (oLat && oLon) SimMap.placeMarker('start', oLat, oLon);
        if (dLat && dLon) SimMap.placeMarker('goal',  dLat, dLon);
        SimMap.fitToMarkers();
    }

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

function buildWeatherBody() {
    return {
        alert_severity:         document.getElementById('p-alert-severity').value,
        current_intensity:      document.getElementById('p-current-intensity').value,
        forecast_max_intensity: document.getElementById('p-forecast-intensity').value,
        forecast_minutes:       30,
        unknown:                document.getElementById('p-weather-unknown').checked,
    };
}

function buildHazardBody() {
    return {
        lowland:      document.getElementById('p-h-lowland').checked,
        flood:        document.getElementById('p-h-flood').checked,
        inland_flood: document.getElementById('p-h-inland-flood').checked,
        landslide:    document.getElementById('p-h-landslide').checked,
        tsunami:      document.getElementById('p-h-tsunami').checked,
        storm_surge:  document.getElementById('p-h-storm-surge').checked,
        unavailable:  document.getElementById('p-hazard-unavailable').checked,
    };
}

// ── シミュレーション実行 ──────────────────────────────────────────────────────
async function runSimulation() {
    const btn = document.getElementById('run-btn');
    btn.disabled = true;
    btn.textContent = '実行中…';

    const resultsEl = document.getElementById('sim-results');
    resultsEl.innerHTML = '<div class="sim-loading">シミュレーション実行中…</div>';

    // フォーム値でマーカーを同期
    if (_mapAvailable) {
        const oLon = parseFloat(document.getElementById('p-origin-lon').value);
        const oLat = parseFloat(document.getElementById('p-origin-lat').value);
        const dLon = parseFloat(document.getElementById('p-dest-lon').value);
        const dLat = parseFloat(document.getElementById('p-dest-lat').value);
        if (oLat && oLon) SimMap.placeMarker('start', oLat, oLon);
        if (dLat && dLon) SimMap.placeMarker('goal',  dLat, dLon);
        SimMap.clearRoutes();
    }

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

        // ルートを地図に描画
        if (_mapAvailable) {
            if (data.status === 'ok' && Array.isArray(data.routes)) {
                SimMap.drawRoutes(data.routes, data.recommended_route_index);
                SimMap.fitToMarkers();
            } else {
                SimMap.clearRoutes();
            }
        }
    } catch (err) {
        resultsEl.innerHTML = `<div class="sim-error">エラー: ${escHtml(err.message)}</div>`;
        if (_mapAvailable) SimMap.clearRoutes();
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

    const cardsWrap = document.createElement('div');
    cardsWrap.className = 'sim-route-cards';
    data.routes.forEach(route => {
        cardsWrap.appendChild(buildRouteCard(route, data.recommended_route_index));
    });
    grid.appendChild(cardsWrap);

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

    const header = document.createElement('div');
    header.className = 'sim-route-card-header';
    header.innerHTML = `
        <span class="sim-route-label">${escHtml(route.label)}${isRec ? ' <span class="sim-rec-badge">推奨</span>' : ''}${route.is_shortest ? ' <span class="sim-shortest-badge">最短</span>' : ''}</span>
        <span class="sim-route-score">安全度 <strong>${route.safety_score}</strong></span>
        <span class="sim-route-risk" style="color:${color};">${escHtml(riskLabel)}</span>
    `;
    card.appendChild(header);

    const meta = document.createElement('div');
    meta.className = 'sim-route-meta';
    meta.textContent = `${distKm} / 約${durMin}分`;
    card.appendChild(meta);

    if (Array.isArray(route.risk_summary) && route.risk_summary.length > 0) {
        const sum = document.createElement('div');
        sum.className = 'sim-route-summary';
        sum.style.color = color;
        sum.textContent = route.risk_summary.join(' / ');
        card.appendChild(sum);
    }

    if (route.recommendation_reason) {
        const reason = document.createElement('div');
        reason.className = 'sim-route-reason';
        reason.textContent = route.recommendation_reason;
        card.appendChild(reason);
    }

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

// ── ポイント検査 ───────────────────────────────────────────────────────────────
async function runPointInspect(lat, lon) {
    const panel = document.getElementById('sim-inspect-panel');
    const body  = document.getElementById('sim-inspect-body');
    panel.style.display = 'block';
    body.innerHTML = '<div class="sim-loading">検査中…</div>';

    // クリックモードボタンの active を解除
    document.querySelectorAll('.sim-map-ctrl-btn[data-mode]').forEach(b => b.classList.remove('active'));
    if (_mapAvailable) SimMap.setClickMode(null);

    try {
        const res = await fetch('/api/simulation/point-inspect', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                lat,
                lon,
                weather:         buildWeatherBody(),
                hazards:         buildHazardBody(),
                use_real_hazard: true,
            }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderPointInspection(body, data);
    } catch (err) {
        body.innerHTML = `<div class="sim-error">検査エラー: ${escHtml(err.message)}</div>`;
    }
}

function renderPointInspection(container, data) {
    const color    = _SIM_RISK_COLOR[data.risk_level] || '#64748b';
    const riskLbl  = _SIM_RISK_LABEL[data.risk_level] || data.risk_level;
    const srcBadge = data.data_source === 'real'
        ? '<span class="sim-inspect-source sim-inspect-source--real">実データ</span>'
        : '<span class="sim-inspect-source sim-inspect-source--sim">モック</span>';

    let html = `
        <div class="sim-inspect-coord">${data.lat.toFixed(5)}, ${data.lon.toFixed(5)} ${srcBadge}</div>
        <div class="sim-inspect-risk" style="color:${color};">${escHtml(riskLbl)}</div>
        <div class="sim-inspect-score">安全度: <strong>${data.safety_score}</strong></div>
    `;

    // 複合リスク
    if (Array.isArray(data.combined_risks) && data.combined_risks.length > 0) {
        html += `<div class="sim-inspect-risks-title">リスク要因</div>`;
        html += `<ul class="sim-inspect-risks-list">`;
        data.combined_risks.forEach(r => {
            html += `<li>${escHtml(r)}</li>`;
        });
        html += `</ul>`;
    }

    // ペナルティ
    if (Array.isArray(data.penalties) && data.penalties.length > 0) {
        html += `<div class="sim-penalty-breakdown">`;
        html += `<div class="sim-penalty-title">ペナルティ内訳</div>`;
        data.penalties.forEach(p => {
            if (p.points > 0) {
                html += `<div class="sim-penalty-item"><span class="sim-penalty-pts">+${p.points}</span><span class="sim-penalty-reason">${escHtml(p.reason)}</span></div>`;
            } else {
                html += `<div class="sim-penalty-item"><span class="sim-penalty-note">${escHtml(p.reason)}</span></div>`;
            }
        });
        html += `</div>`;
    }

    container.innerHTML = html;
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

    // JSON エクスポートボタン
    html += `<div style="margin-bottom:10px;">
        <button class="sim-json-export-btn" id="btn-export-json" type="button">JSONをダウンロード</button>
    </div>`;

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

    // JSON エクスポートボタンにクリックハンドラを付ける
    const exportBtn = container.querySelector('#btn-export-json');
    if (exportBtn) {
        exportBtn.addEventListener('click', () => _downloadJson(data, 'simulation_auto_run.json'));
    }
}

function _downloadJson(obj, filename) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

// ── シナリオ保存 ───────────────────────────────────────────────────────────────
async function saveScenario() {
    const id    = document.getElementById('save-scenario-id').value.trim();
    const title = document.getElementById('save-scenario-title').value.trim();
    if (!id || !title) { alert('ID とタイトルを入力してください'); return; }

    const btn = document.getElementById('save-btn');
    btn.disabled = true;
    try {
        const body = buildRequestBody(id);
        const res = await fetch('/api/simulation/scenarios/save', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ ...body, title }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.status === 'ok') {
            alert(`保存しました: ${id}`);
            document.getElementById('save-scenario-id').value = '';
            document.getElementById('save-scenario-title').value = '';
        } else {
            alert(`保存失敗: ${data.message || 'unknown error'}`);
        }
    } catch (err) {
        alert(`保存エラー: ${err.message}`);
    } finally {
        btn.disabled = false;
    }
}

// ── 保存済みシナリオ読み込み ───────────────────────────────────────────────────
async function openSavedScenariosModal() {
    const modal = document.getElementById('saved-scenarios-modal');
    const body  = document.getElementById('saved-modal-body');
    body.innerHTML = '<div class="sim-loading">読み込み中…</div>';
    modal.style.display = 'flex';

    try {
        const res = await fetch('/api/simulation/scenarios/saved');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const scenarios = (data || {}).scenarios || [];

        if (scenarios.length === 0) {
            body.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:20px;">保存済みシナリオはありません</p>';
            return;
        }

        let html = '<div class="sim-saved-list">';
        scenarios.forEach(sc => {
            html += `
                <div class="sim-saved-item" data-sc='${JSON.stringify(sc).replace(/'/g, '&#39;')}'>
                    <div class="sim-saved-id">[${escHtml(sc.scenario_id)}]</div>
                    <div class="sim-saved-title">${escHtml(sc.title)}</div>
                </div>
            `;
        });
        html += '</div>';
        body.innerHTML = html;

        body.querySelectorAll('.sim-saved-item').forEach(item => {
            item.addEventListener('click', () => {
                const sc = JSON.parse(item.dataset.sc);
                applyScenario(sc);
                modal.style.display = 'none';
            });
        });
    } catch (err) {
        body.innerHTML = `<div class="sim-error">読み込みエラー: ${escHtml(err.message)}</div>`;
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// キキクル Simulation Mode (Phase 3-D)
// ══════════════════════════════════════════════════════════════════════════════

function _kkkBuildPanel() {
    const container = document.getElementById('kkk-scenario-buttons');
    if (!container) return;
    Object.entries(_KKK_SIM_SCENARIOS).forEach(([key, sc]) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'kkk-scenario-btn';
        btn.dataset.key = key;
        btn.textContent = sc.label;
        btn.addEventListener('click', () => _kkkApplyScenario(key));
        container.appendChild(btn);
    });
}

function _kkkApplyScenario(key) {
    const preset = _KKK_SIM_SCENARIOS[key];
    if (!preset) return;
    _kkkSimState = { key, ...preset };
    document.querySelectorAll('.kkk-scenario-btn').forEach(b => b.classList.remove('active'));
    const btn = document.querySelector(`.kkk-scenario-btn[data-key="${key}"]`);
    if (btn) btn.classList.add('active');
    if (_mapAvailable) SimMap.drawKikikuruOverlay(_kkkSimState);
    _kkkUpdateDisplay();
    _kkkRouteRiskPreview();
}

function _kkkClearScenario() {
    _kkkSimState = null;
    _kkkPreviewRequestToken += 1;
    document.querySelectorAll('.kkk-scenario-btn').forEach(b => b.classList.remove('active'));
    if (_mapAvailable) SimMap.clearKikikuruOverlay();
    const preview = document.getElementById('kkk-adj-preview');
    if (preview) preview.innerHTML = '';
    _kkkUpdateDisplay();
}

function _kkkUpdateDisplay() {
    const section = document.getElementById('kkk-adj-section');
    if (!section) return;
    if (!_kkkSimState) {
        section.style.display = 'none';
        _phase4UpdatePreviews();
        return;
    }
    section.style.display = 'block';
    const disp = document.getElementById('kkk-adj-display');
    if (!disp) return;

    let html = `<div class="kkk-sim-scenario-label">${escHtml(_kkkSimState.label)}</div>`;

    if (_kkkSimState.status === 'unavailable') {
        html += `<div class="kkk-sim-status kkk-sim-status--neutral">取得不可 — 補正なし（安全を意味しません）</div>`;
    } else if (_kkkSimState.status === 'unknown') {
        html += `<div class="kkk-sim-status kkk-sim-status--neutral">判定不可 — 補正なし（安全を意味しません）</div>`;
    } else if (_kkkSimState.values) {
        const v = _kkkSimState.values;
        const kinds = [
            { label: '浸水キキクル', key: 'inund' },
            { label: '洪水キキクル', key: 'flood' },
            { label: '土砂キキクル', key: 'land' },
        ];
        html += '<table class="kkk-sim-kinds-table">';
        kinds.forEach(({ label, key }) => {
            const val = v[key] || 'none';
            html += `<tr><td>${label}</td><td class="kkk-kind-val kkk-kind-val--${val}">${_KKK_LEVEL_LABEL[val] || val}</td></tr>`;
        });
        html += '</table>';
    }
    disp.innerHTML = html;
    _kkkUpdateSummaries();
    _phase4UpdatePreviews();
}

function _kkkUpdateSummaries() {
    const targets = [
        document.getElementById('kkk-summary-current'),
        document.getElementById('kkk-summary-destination'),
        document.getElementById('kkk-summary-route'),
    ].filter(Boolean);
    if (targets.length === 0 || !_kkkSimState) return;

    let html;
    if (_kkkSimState.status === 'unavailable') {
        html = '<span class="kkk-summary-value--neutral">取得不可（安全を意味しません）</span>';
    } else if (_kkkSimState.status === 'unknown') {
        html = '<span class="kkk-summary-value--neutral">判定不可（安全を意味しません）</span>';
    } else {
        const kindLabel = { inund: '浸水', flood: '洪水', land: '土砂' };
        const active = Object.entries(_kkkSimState.values || {})
            .filter(([, level]) => level === 'caution' || level === 'danger')
            .map(([kind, level]) => {
                const dangerClass = level === 'danger' ? ' kkk-summary-risk--danger' : '';
                return `<span class="kkk-summary-risk${dangerClass}">${kindLabel[kind] || escHtml(kind)} ${_KKK_LEVEL_LABEL[level]}</span>`;
            });
        html = active.length > 0 ? active.join(' / ') : '対象リスクなし';
    }
    targets.forEach(target => { target.innerHTML = html; });
}

function _phase4RiskText(values) {
    const kindLabel = { inund: '浸水キキクル', flood: '洪水キキクル', land: '土砂キキクル' };
    const active = Object.entries(values || {})
        .filter(([, level]) => level === 'caution' || level === 'danger')
        .map(([kind, level]) => `${kindLabel[kind]}: ${_KKK_LEVEL_LABEL[level]}`);
    return active.length > 0 ? active.join(' / ') : '該当リスク検出なし';
}

function _phase4HazardNames(values) {
    const kindLabel = { inund: '浸水', flood: '洪水', land: '土砂' };
    return Object.entries(values || {})
        .filter(([, level]) => level === 'caution' || level === 'danger')
        .map(([kind]) => kindLabel[kind] || kind)
        .join('・');
}

function _phase4MaxLevel(values) {
    return Object.values(values || {}).includes('danger')
        ? 'danger'
        : Object.values(values || {}).includes('caution') ? 'caution' : 'none';
}

function _phase4UpdatePreviews(adj = null) {
    const warningEl = document.getElementById('phase4-forward-preview');
    const situationEl = document.getElementById('phase4-situation-preview');
    if (!warningEl || !situationEl) return;
    if (!_kkkSimState) {
        warningEl.innerHTML = '';
        situationEl.innerHTML = '';
        return;
    }

    const state = _kkkSimState;
    const neutral = state.status === 'unavailable' || state.status === 'unknown';
    if (neutral) {
        const text = state.status === 'unavailable' ? '取得不可' : '判定不可';
        warningEl.innerHTML = `
            <div class="phase4-preview-title">ナビ中警告</div>
            <div class="phase4-forward-neutral">前方ルート: ${text}</div>
            <div class="phase4-preview-note">安全を意味するものではありません</div>`;
        situationEl.innerHTML = `
            <div class="phase4-preview-title">状況理解</div>
            <div class="phase4-sit-row"><span>現在地</span><strong>${text}</strong></div>
            <div class="phase4-sit-row"><span>目的地</span><strong>${text}</strong></div>
            <div class="phase4-preview-note">情報を確認できず、安全・危険を断定できません</div>`;
        return;
    }

    const forwardLevel = adj?.max_level || _phase4MaxLevel(state.values);
    if (forwardLevel === 'none') {
        warningEl.innerHTML = `
            <div class="phase4-preview-title">ナビ中警告</div>
            <div class="phase4-preview-note">警告表示なし（安全確定を意味しません）</div>`;
    } else {
        const overlap = Array.isArray(adj?.matched_hazards) && adj.matched_hazards.length > 0;
        const hazardNames = _phase4HazardNames(state.values);
        warningEl.innerHTML = `
            <div class="phase4-preview-title">ナビ中警告</div>
            <div class="phase4-forward-alert phase4-forward-alert--${forwardLevel}">
              <strong>この先 約250m先</strong>
              <div>${escHtml(hazardNames)}リスクが上昇しています</div>
              ${overlap ? '<div>固定ハザードとキキクルが重なっています</div>' : ''}
              <small>周囲の状況に注意してください</small>
            </div>`;
    }

    const sit = state.situation || {
        current: state.values,
        destination: state.values,
        route: forwardLevel === 'danger' ? '注意' : '問題なし',
    };
    const actionLabel = sit.action === 'wait'
        ? '待機検討'
        : sit.action === 'move' ? '早めの移動検討' : '';
    situationEl.innerHTML = `
        <div class="phase4-preview-title">状況理解${actionLabel ? `<b class="phase4-action phase4-action--${sit.action}">${actionLabel}</b>` : ''}</div>
        <div class="phase4-sit-row"><span>現在地</span><strong>${escHtml(_phase4RiskText(sit.current))}</strong></div>
        <div class="phase4-sit-row"><span>目的地</span><strong>${escHtml(_phase4RiskText(sit.destination))}</strong></div>
        ${sit.route ? `<div class="phase4-sit-row"><span>ルート</span><strong>${escHtml(sit.route)}</strong></div>` : ''}
        ${sit.rain ? `<div class="phase4-sit-row"><span>降水</span><strong>${escHtml(sit.rain)}</strong></div>` : ''}
        ${sit.time ? `<div class="phase4-time">${escHtml(sit.time)}</div>` : ''}
        ${sit.reason ? `<div class="phase4-reason">${escHtml(sit.reason)}<br>可能であれば${sit.action === 'wait' ? '待機' : '早めの移動'}を検討してください</div>` : ''}`;
}

async function _kkkRouteRiskPreview() {
    const adjEl = document.getElementById('kkk-adj-preview');
    if (!adjEl) return;
    if (!_kkkSimState) { adjEl.innerHTML = ''; return; }
    const requestToken = ++_kkkPreviewRequestToken;

    const oLon = parseFloat(document.getElementById('p-origin-lon').value);
    const oLat = parseFloat(document.getElementById('p-origin-lat').value);
    const dLon = parseFloat(document.getElementById('p-dest-lon').value);
    const dLat = parseFloat(document.getElementById('p-dest-lat').value);
    if (!oLat || !oLon || !dLat || !dLon) { adjEl.innerHTML = ''; return; }

    adjEl.innerHTML = '<div class="kkk-adj-preview--loading">補正計算中…</div>';

    let kikikuruPayload;
    if (_kkkSimState.status === 'unavailable') {
        kikikuruPayload = { status: 'unavailable' };
    } else if (_kkkSimState.status === 'unknown') {
        kikikuruPayload = { status: 'unknown' };
    } else {
        kikikuruPayload = { status: 'ok', ...(_kkkSimState.values || {}) };
    }

    try {
        const res = await fetch('/api/route-risk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                coordinates: [[oLat, oLon], [dLat, dLon]],
                sample_count: 10,
                kikikuru: kikikuruPayload,
            }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (requestToken !== _kkkPreviewRequestToken || !_kkkSimState) return;
        const adjustment = data.kikikuru_adjustment || null;
        _kkkRenderAdjPreview(adjEl, adjustment);
    } catch (err) {
        if (requestToken !== _kkkPreviewRequestToken || !_kkkSimState) return;
        adjEl.innerHTML = `<div class="kkk-adj-preview--error">補正取得エラー: ${escHtml(err.message)}</div>`;
    }
}

function _kkkRenderAdjPreview(container, adj) {
    if (!adj) { container.innerHTML = ''; return; }

    let html = '<div class="kkk-adj-preview-header">route-risk 補正プレビュー</div>';

    if (!adj.enabled) {
        html += '<div class="kkk-adj-preview--none">補正無効</div>';
    } else if (adj.status === 'unavailable') {
        html += '<div class="kkk-adj-preview--neutral">キキクル取得不可（補正なし）</div>';
    } else if (adj.status === 'unknown') {
        html += '<div class="kkk-adj-preview--neutral">キキクル判定不可（補正なし）</div>';
    } else if (adj.penalty > 0) {
        const isOverlap = (adj.matched_hazards || []).length > 0;
        html += `<div class="kkk-adj-preview--active${isOverlap ? ' kkk-adj-preview--overlap' : ''}">`;
        html += `<div class="kkk-adj-preview-label">リアルタイム補正</div>`;
        if (_kkkSimState && _kkkSimState.values) {
            const kindLabel = { inund: '浸水', flood: '洪水', land: '土砂' };
            const active = Object.entries(_kkkSimState.values)
                .filter(([, v]) => v === 'caution' || v === 'danger')
                .map(([k]) => kindLabel[k] || k);
            if (active.length > 0) {
                html += `<div class="kkk-adj-preview-main">${active.join('・')}リスクが上昇しています</div>`;
            }
        }
        if (isOverlap) {
            html += `<div class="kkk-adj-preview-context">固定ハザードとキキクルが重なっています</div>`;
        }
        html += `<div class="kkk-adj-preview-detail">補正: -${adj.penalty}pt　最大レベル: ${adj.max_level === 'danger' ? '危険' : '注意'}</div>`;
        html += '</div>';
    } else {
        html += '<div class="kkk-adj-preview--none">補正なし（レベルなし）</div>';
    }

    container.innerHTML = html;
    _phase4UpdatePreviews(adj);
}

window.setKikikuruSimulationScenario = function(config) {
    if (!config || config.enabled === false) {
        _kkkClearScenario();
        return;
    }
    const key = (config.scenario || '').replace(/-/g, '_');
    if (key && _KKK_SIM_SCENARIOS[key]) {
        _kkkApplyScenario(key);
        return;
    }
    if (config.values) {
        const status = config.unavailable ? 'unavailable' : (config.values ? 'ok' : 'unknown');
        _kkkSimState = { key: 'custom', label: 'カスタム', status, values: config.values };
        if (_mapAvailable) SimMap.drawKikikuruOverlay(_kkkSimState);
        _kkkUpdateDisplay();
        _kkkRouteRiskPreview();
    }
};

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
    initMap();
    loadScenarios();
    _kkkBuildPanel();

    // URL param ?kikikuruScenario=xxx でシナリオ自動選択 (E2E 注入用)
    const _urlParams = new URLSearchParams(window.location.search);
    const _urlKkkScenario = _urlParams.get('kikikuruScenario');
    if (_urlKkkScenario) _kkkApplyScenario(_urlKkkScenario.replace(/-/g, '_'));

    // キキクルクリアボタン
    const kkkClearBtn = document.getElementById('kkk-clear-btn');
    if (kkkClearBtn) kkkClearBtn.addEventListener('click', _kkkClearScenario);

    document.getElementById('run-btn').addEventListener('click', runSimulation);
    document.getElementById('auto-run-btn').addEventListener('click', runAuto);
    document.getElementById('save-btn').addEventListener('click', saveScenario);
    document.getElementById('load-btn').addEventListener('click', openSavedScenariosModal);

    document.getElementById('auto-run-modal-close').addEventListener('click', () => {
        document.getElementById('auto-run-modal').style.display = 'none';
    });
    document.getElementById('auto-run-modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) e.currentTarget.style.display = 'none';
    });

    document.getElementById('saved-modal-close').addEventListener('click', () => {
        document.getElementById('saved-scenarios-modal').style.display = 'none';
    });
    document.getElementById('saved-scenarios-modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) e.currentTarget.style.display = 'none';
    });
});
