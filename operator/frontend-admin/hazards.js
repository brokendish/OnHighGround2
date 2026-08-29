/**
 * hazards.js — 管理画面ロジック（read-only）
 *
 * backend の /api/admin/* エンドポイントからデータを取得し、
 * テーブルと詳細パネルを描画する。
 */

// ── API ───────────────────────────────────────────────────────────────────

const API_BASE = '/api/admin';

async function fetchJSON(path) {
    const resp = await fetch(API_BASE + path);
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} (${path})`);
    return resp.json();
}

// ── バッジ描画ヘルパー ─────────────────────────────────────────────────────

function statusBadge(status) {
    const map = {
        active:  ['badge-active',  'active'],
        warning: ['badge-warning', 'warning'],
        planned: ['badge-planned', 'planned'],
        error:   ['badge-error',   'error'],
        disabled:['badge-planned', 'disabled'],
    };
    const [cls, label] = map[status] || ['badge-planned', status];
    return `<span class="badge ${cls}">${label}</span>`;
}

function deliveryBadge(main) {
    const map = {
        vector_tile: ['badge-vt',      'vector tile'],
        api:         ['badge-api',     'api'],
        geojson:     ['badge-geojson', 'geojson'],
        none:        ['badge-none',    'none'],
    };
    const [cls, label] = map[main] || ['badge-none', main];
    return `<span class="badge ${cls}">${label}</span>`;
}

function boolCell(val) {
    return val
        ? '<span class="bool-yes">Yes</span>'
        : '<span class="bool-no">No</span>';
}

function runtimeCell(rt) {
    if (rt === 'ok')            return '<span class="rt-ok">✓ ok</span>';
    if (rt === 'tiles_missing') return '<span class="rt-warning">⚠ tiles missing</span>';
    if (rt === 'api_only')      return '<span class="rt-warning">~ api only</span>';
    if (rt === 'not_configured')return '<span class="rt-bad">✗ not configured</span>';
    if (rt === 'error')         return '<span class="rt-bad">✗ error</span>';
    return `<span class="rt-bad">${rt}</span>`;
}

// ── サマリーカード ─────────────────────────────────────────────────────────

function renderSummary(data) {
    const catalogOk = data.catalog_ok;
    document.getElementById('card-active').textContent   = data.active_layers ?? '—';
    document.getElementById('card-vt').textContent       = data.vector_tile_layers ?? '—';
    document.getElementById('card-fallback').textContent = data.fallback_capable_layers ?? '—';
    document.getElementById('card-planned').textContent  = data.planned_layers ?? '—';

    const catalogCard = document.getElementById('catalog-card');
    const catalogBadge = document.getElementById('catalog-badge');
    catalogCard.className = 'summary-card ' + (catalogOk ? 'catalog-ok' : 'catalog-warn');
    catalogBadge.className = 'catalog-badge ' + (catalogOk ? 'ok' : 'warn');
    catalogBadge.textContent = catalogOk ? 'online' : 'unreachable';

    const tilesets = data.tilesets || [];
    document.getElementById('catalog-tilesets').textContent =
        tilesets.length > 0 ? tilesets.length + ' tileset(s)' : '—';
}

// ── テーブル ───────────────────────────────────────────────────────────────

function renderTable(layers) {
    const tbody = document.getElementById('layer-tbody');
    tbody.innerHTML = '';

    layers.forEach(layer => {
        const tr = document.createElement('tr');
        tr.dataset.key = layer.layer_key;
        tr.innerHTML = `
            <td>
                <div class="layer-name">${escapeHtml(layer.name)}</div>
                <div class="layer-key">${escapeHtml(layer.layer_key)}</div>
            </td>
            <td>${statusBadge(layer.status)}</td>
            <td>${deliveryBadge(layer.main_delivery)}</td>
            <td>${boolCell(layer.fallback)}</td>
            <td>${boolCell(layer.severity)}</td>
            <td style="font-size:11px; font-family:monospace; color:#475569">
                ${layer.tileset_id ? escapeHtml(layer.tileset_id) : '—'}
            </td>
            <td>${runtimeCell(layer.runtime_state)}</td>
        `;
        tr.addEventListener('click', () => selectLayer(layer.layer_key, tr));
        tbody.appendChild(tr);
    });
}

// ── 行選択と詳細パネル ────────────────────────────────────────────────────

let _selectedKey = null;

function selectLayer(layerKey, trEl) {
    // 行ハイライト
    document.querySelectorAll('#layer-tbody tr').forEach(r => r.classList.remove('active'));
    if (trEl) trEl.classList.add('active');
    _selectedKey = layerKey;
    loadDetail(layerKey);
}

async function loadDetail(layerKey) {
    const body = document.getElementById('detail-body');
    const placeholder = document.getElementById('detail-placeholder');
    body.classList.remove('visible');
    placeholder.textContent = '読み込み中...';
    placeholder.style.display = 'block';

    try {
        const data = await fetchJSON('/hazards/' + encodeURIComponent(layerKey));
        renderDetail(data);
        placeholder.style.display = 'none';
        body.classList.add('visible');
    } catch (err) {
        placeholder.textContent = `詳細取得エラー: ${err.message}`;
    }
}

function renderDetail(d) {
    document.getElementById('detail-name').textContent = d.name;
    document.getElementById('detail-key').textContent  = d.layer_key;

    // バッジ
    document.getElementById('detail-badges').innerHTML =
        statusBadge(d.status) + ' ' + deliveryBadge(d.main_delivery);

    // 属性テーブル
    const rows = [
        ['Type',          d.type || '—'],
        ['Region',        d.region || '—'],
        ['Tileset ID',    d.tileset_id || '—'],
        ['API URL',       d.api_url || '—'],
        ['Runtime state', d.runtime_state || '—'],
        ['Catalog',       d.catalog_present === true ? '✓ present' : d.catalog_present === false ? '✗ absent' : '—'],
        ['Severity',      d.severity ? 'Yes' : 'No'],
        ['Fallback',      d.fallback ? 'Yes' : 'No'],
    ];
    document.getElementById('detail-attrs').innerHTML = rows.map(([k, v]) =>
        `<div class="detail-row"><span class="dk">${k}</span><span class="dv">${escapeHtml(String(v))}</span></div>`
    ).join('');

    // パス
    const pathRows = [
        ['Source GeoJSON', d.source_path || '—'],
        ['Runtime tiles',  d.runtime_tiles_path || '—'],
    ];
    document.getElementById('detail-paths').innerHTML = pathRows.map(([k, v]) =>
        `<div class="detail-row"><span class="dk">${k}</span><span class="dv">${escapeHtml(String(v))}</span></div>`
    ).join('');

    // ノート
    const notes = Array.isArray(d.notes) ? d.notes : (d.notes ? [d.notes] : []);
    document.getElementById('detail-notes').innerHTML = notes.length
        ? '<ul>' + notes.map(n => `<li>${escapeHtml(n)}</li>`).join('') + '</ul>'
        : '<span style="color:#94a3b8;font-size:12px">—</span>';

    // ドキュメントリンク
    const docs = d.docs || [];
    document.getElementById('detail-docs').innerHTML = docs.length
        ? docs.map(doc => `<a href="/${escapeHtml(doc)}" target="_blank">${escapeHtml(doc)}</a>`).join('')
        : '<span style="color:#94a3b8;font-size:12px">—</span>';
}

// ── エラー表示 ─────────────────────────────────────────────────────────────

function showError(msg) {
    const bar = document.getElementById('error-bar');
    bar.textContent = msg;
    bar.classList.add('visible');
}

// ── ユーティリティ ─────────────────────────────────────────────────────────

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── 初期化 ─────────────────────────────────────────────────────────────────

async function init() {
    try {
        const [summary, layersResp] = await Promise.all([
            fetchJSON('/runtime/summary'),
            fetchJSON('/hazards'),
        ]);
        renderSummary(summary);
        const layers = layersResp.layers || [];
        renderTable(layers);

        // 先頭行を自動選択
        if (layers.length > 0) {
            const firstTr = document.querySelector('#layer-tbody tr');
            selectLayer(layers[0].layer_key, firstTr);
        }
    } catch (err) {
        showError('データ取得エラー: ' + err.message);
        // テーブルのローディング行を差し替え
        const tbody = document.getElementById('layer-tbody');
        tbody.innerHTML = `<tr class="loading-row"><td colspan="7">読み込みに失敗しました。バックエンドが起動しているか確認してください。</td></tr>`;
    }
}

document.addEventListener('DOMContentLoaded', init);
