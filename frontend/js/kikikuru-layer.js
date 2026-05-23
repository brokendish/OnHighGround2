'use strict';

/**
 * kikikuru-layer.js — 気象庁キキクル（危険度分布）表示レイヤー
 *
 * 外部エントリポイント:
 *   _kikikuruSetVisible(kind, visible)  — kind: 'inund'|'flood'|'land'
 *   refreshKikikuru()                   — 最新時刻に更新（手動・自動共用）
 *
 * タイルURL形式:
 *   https://www.jma.go.jp/bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/{elem}/{z}/{x}/{y}.png
 *
 * 時刻管理:
 *   https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json
 *   更新間隔: 10分
 */

const _KIKIKURU_TIMES_URL = 'https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json';
const _KIKIKURU_TILE_BASE  = 'https://www.jma.go.jp/bosai/jmatile/data/risk';

// キキクルの各レイヤー定義
// flood: flood_mesh を第一候補。利用できない環境では elem を 'flood' に変更する。
const _KIKIKURU_KINDS = {
    inund: { label: '浸水キキクル', elem: 'inund',      zIndex: 440 },
    flood: { label: '洪水キキクル', elem: 'flood_mesh', zIndex: 442 },
    land:  { label: '土砂キキクル', elem: 'land',       zIndex: 441 },
};

// 危険度凡例（気象庁の危険度色に準拠）
const _KIKIKURU_LEGEND = [
    { color: '#7b00d4', label: '災害切迫（レベル5）' },
    { color: '#ff2800', label: '危険（レベル4）'     },
    { color: '#ff9900', label: '警戒（レベル3）'     },
    { color: '#f0e000', label: '注意（レベル2）'     },
    { color: '#00aa00', label: '今後の情報等に留意'  },
];

// 共通取得状態
let _kikikuruCurrentEntry = null;   // targetTimesの最新エントリ
let _kikikuruLastUpdated  = null;   // 最終取得成功時刻（Date）
let _kikikuruTimer        = null;
let _kikikuruRefreshPromise = null; // 同時ON時の時刻取得を束ねる

// 種別ごとの状態: 'off'|'checking'|'ok'|'error'
const _kikikuruKindStatus = { inund: 'off', flood: 'off', land: 'off' };

// レイヤーインスタンス（kind → TileLayer | null）
const _kikikuruLayers = { inund: null, flood: null, land: null };
// 有効フラグ（kind → bool）
const _kikikuruEnabled = { inund: false, flood: false, land: false };

// ── カスタム TileLayer（偶数ズーム clamp）───────────────────────────────────

const _KikikuruTileLayer = L.TileLayer.extend({
    _clampZoom: function (zoom) {
        var z = L.TileLayer.prototype._clampZoom.call(this, zoom);
        if (z % 2 !== 0) z = Math.max(z - 1, 4);
        return z;
    },
});

// ── タイルURLを構築 ──────────────────────────────────────────────────────────

function _kikikuruTileUrl(entry, elem) {
    return `${_KIKIKURU_TILE_BASE}/${entry.basetime}/${entry.member}/${entry.validtime}/surf/${elem}/{z}/{x}/{y}.png`;
}

// ── targetTimes.json 取得 ───────────────────────────────────────────────────

async function _kikikuruFetchLatest() {
    const res = await fetch(`${_KIKIKURU_TIMES_URL}?_=${Date.now()}`);
    if (!res.ok) throw new Error(`kikikuru targetTimes ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data) || !data.length) throw new Error('kikikuru: empty targetTimes');
    return data[0];  // 最新 = immed0
}

// ── レイヤー更新 ────────────────────────────────────────────────────────────

function _kikikuruUpdateLayer(kind) {
    if (!_kikikuruEnabled[kind] || !_kikikuruCurrentEntry) return;

    const entry = _kikikuruCurrentEntry;
    const def   = _KIKIKURU_KINDS[kind];
    const url   = _kikikuruTileUrl(entry, def.elem);

    const opts = {
        opacity:       0.6,
        attribution:   '気象庁 キキクル（危険度分布）',
        minZoom:       4,
        maxNativeZoom: 11,
        maxZoom:       19,
        tileSize:      256,
        zIndex:        def.zIndex,
    };

    if (_kikikuruLayers[kind]) {
        _kikikuruLayers[kind].setUrl(url);
    } else {
        _kikikuruLayers[kind] = new _KikikuruTileLayer(url, opts).addTo(map);
    }
}

function _kikikuruRemoveLayer(kind) {
    if (_kikikuruLayers[kind]) {
        try { map.removeLayer(_kikikuruLayers[kind]); } catch (_) {}
        _kikikuruLayers[kind] = null;
    }
}

// ── 公開 ON/OFF ──────────────────────────────────────────────────────────────

function _kikikuruSetVisible(kind, visible) {
    if (!(kind in _kikikuruEnabled)) return;
    _kikikuruEnabled[kind] = visible;
    _kikikuruUpdateToggleBtnState(kind, visible);

    if (visible) {
        _kikikuruKindStatus[kind] = 'checking';
        _kikikuruUpdateKindStatusUI(kind);
        if (!_kikikuruCurrentEntry) {
            refreshKikikuru();
        } else {
            const def = _KIKIKURU_KINDS[kind];
            const avail = _kikikuruCurrentEntry.elements
                && _kikikuruCurrentEntry.elements.includes(def.elem);
            _kikikuruKindStatus[kind] = avail ? 'ok' : 'error';
            _kikikuruUpdateKindStatusUI(kind);
            if (avail) _kikikuruUpdateLayer(kind);
        }
    } else {
        _kikikuruKindStatus[kind] = 'off';
        _kikikuruUpdateKindStatusUI(kind);
        _kikikuruRemoveLayer(kind);
    }

    _kikikuruSyncPanelVisibility();
    _kikikuruLegendUpdateKinds();
}

// ── 更新処理 ────────────────────────────────────────────────────────────────

function refreshKikikuru() {
    if (_kikikuruRefreshPromise) return _kikikuruRefreshPromise;

    _kikikuruRefreshPromise = _kikikuruRefresh()
        .finally(() => { _kikikuruRefreshPromise = null; });
    return _kikikuruRefreshPromise;
}

async function _kikikuruRefresh() {
    // 全有効種別を checking に
    for (const kind of Object.keys(_kikikuruEnabled)) {
        if (_kikikuruEnabled[kind]) {
            _kikikuruKindStatus[kind] = 'checking';
            _kikikuruUpdateKindStatusUI(kind);
        }
    }
    _kikikuruSetSharedStatusUI('checking');

    try {
        const entry = await _kikikuruFetchLatest();

        const isNew = !_kikikuruCurrentEntry
            || entry.basetime !== _kikikuruCurrentEntry.basetime;

        _kikikuruCurrentEntry = entry;
        _kikikuruLastUpdated  = new Date();

        for (const kind of Object.keys(_kikikuruEnabled)) {
            if (_kikikuruEnabled[kind]) {
                const def   = _KIKIKURU_KINDS[kind];
                const avail = entry.elements && entry.elements.includes(def.elem);
                _kikikuruKindStatus[kind] = avail ? 'ok' : 'error';
                _kikikuruUpdateKindStatusUI(kind);
                if (isNew && avail) _kikikuruUpdateLayer(kind);
            }
        }

        _kikikuruSetSharedStatusUI('ok');
        _kkkSampleAll();

    } catch (err) {
        console.warn('[kikikuru] fetch failed:', err);
        for (const kind of Object.keys(_kikikuruEnabled)) {
            if (_kikikuruEnabled[kind]) {
                _kikikuruKindStatus[kind] = _kikikuruCurrentEntry ? 'error' : 'error';
                _kikikuruUpdateKindStatusUI(kind);
            }
        }
        _kkkSetRiskUnavailable('current');
        _kkkSetRiskUnavailable('dest');
        _kkkSetRouteRiskUnavailable();
        _kikikuruSetSharedStatusUI(_kikikuruCurrentEntry ? 'stale' : 'error');
    }
}

function _kikikuruStartAutoRefresh() {
    if (_kikikuruTimer) return;
    _kikikuruTimer = setInterval(refreshKikikuru, 10 * 60 * 1000);
}

function _kikikuruStopAutoRefresh() {
    if (_kikikuruTimer) {
        clearInterval(_kikikuruTimer);
        _kikikuruTimer = null;
    }
}

// ── 共通ステータスUI（更新時刻・バッジ） ─────────────────────────────────────

function _kikikuruSetSharedStatusUI(status) {
    const statusEl = document.getElementById('kkk-status-text');
    const timeEl   = document.getElementById('kkk-updated-time');
    const badgeEl  = document.getElementById('kkk-status-badge');

    const timeStr = _kikikuruLastUpdated
        ? _kikikuruLastUpdated.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
        : '';

    const validtimeStr = _kikikuruCurrentEntry
        ? _kikikuruFmtValidtime(_kikikuruCurrentEntry.validtime)
        : '';

    if (statusEl) {
        switch (status) {
            case 'checking': statusEl.textContent = '更新確認中…'; break;
            case 'ok':       statusEl.textContent = validtimeStr ? `${validtimeStr} 時点` : '取得済み'; break;
            case 'stale':    statusEl.textContent = '情報が古い可能性があります'; break;
            case 'error':    statusEl.textContent = '取得不可'; break;
        }
    }
    if (timeEl) {
        timeEl.textContent = timeStr ? `（取得: ${timeStr}）` : '';
    }
    if (badgeEl) {
        badgeEl.className     = 'kkk-status-badge';
        badgeEl.style.display = '';
        switch (status) {
            case 'ok':       badgeEl.classList.add('kkk-badge--ok');    badgeEl.textContent = '正常'; break;
            case 'checking': badgeEl.classList.add('kkk-badge--check'); badgeEl.textContent = '確認中'; break;
            case 'stale':    badgeEl.classList.add('kkk-badge--stale'); badgeEl.textContent = '古い可能性'; break;
            case 'error':    badgeEl.classList.add('kkk-badge--error'); badgeEl.textContent = '取得不可'; break;
        }
    }

    const legendTime = document.getElementById('kkk-legend-time');
    if (legendTime) legendTime.textContent = validtimeStr ? `${validtimeStr} 時点の危険度` : '';
}

// ── 種別ごとのステータスUI ─────────────────────────────────────────────────

function _kikikuruUpdateKindStatusUI(kind) {
    const span = document.getElementById(`kkk-kind-st-${kind}`);
    if (!span) return;
    const st = _kikikuruKindStatus[kind];
    span.className = `kkk-kind-st kkk-kind-st--${st}`;
    switch (st) {
        case 'ok':       span.textContent = '正常'; break;
        case 'error':    span.textContent = '取得不可'; break;
        case 'checking': span.textContent = '確認中'; break;
        default:         span.textContent = 'OFF'; break;
    }
}

// ── フォーマット ─────────────────────────────────────────────────────────────

function _kikikuruFmtValidtime(vt) {
    if (!vt || vt.length < 12) return '';
    try {
        const d = new Date(Date.UTC(
            parseInt(vt.slice(0, 4), 10),
            parseInt(vt.slice(4, 6), 10) - 1,
            parseInt(vt.slice(6, 8), 10),
            parseInt(vt.slice(8, 10), 10),
            parseInt(vt.slice(10, 12), 10),
        ));
        return d.toLocaleString('ja-JP', {
            month: 'numeric', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
            timeZone: 'Asia/Tokyo',
        });
    } catch (_) { return ''; }
}

function _kikikuruUpdateToggleBtnState(kind, active) {
    const btn = document.getElementById(`kkk-toggle-${kind}`);
    if (btn) btn.classList.toggle('kkk-toggle--active', active);
}

function _kikikuruSyncPanelVisibility() {
    const anyOn = Object.values(_kikikuruEnabled).some(Boolean);
    const mapBtn = document.getElementById('kikikuru-map-btn');
    if (mapBtn) mapBtn.classList.toggle('map-overlay-btn--active', _kikikuruEnabled.inund);

    if (anyOn) {
        if (!_kikikuruTimer) _kikikuruStartAutoRefresh();
        _kkkStartLocationPoll();
    } else {
        _kikikuruStopAutoRefresh();
        _kkkStopLocationPoll();
    }
}

// ── 凡例 ────────────────────────────────────────────────────────────────────

function _kikikuruLegendBuild() {
    const el = document.getElementById('kkk-legend');
    if (!el || el.dataset.built) return;

    const title = document.createElement('div');
    title.className   = 'kkk-legend-title';
    title.textContent = 'キキクル（現在の危険度）';
    el.appendChild(title);

    // 表示中レイヤー一覧（動的更新）
    const kindsEl = document.createElement('div');
    kindsEl.id        = 'kkk-legend-kinds';
    kindsEl.className = 'kkk-legend-kinds';
    el.appendChild(kindsEl);

    const timeEl = document.createElement('div');
    timeEl.id        = 'kkk-legend-time';
    timeEl.className = 'kkk-legend-time';
    el.appendChild(timeEl);

    const rows = document.createElement('div');
    rows.className = 'kkk-legend-rows';
    _KIKIKURU_LEGEND.forEach(entry => {
        const row = document.createElement('div');
        row.className = 'kkk-legend-row';
        row.innerHTML = `<span class="kkk-legend-swatch" style="background:${entry.color}"></span>`
                      + `<span class="kkk-legend-label">${entry.label}</span>`;
        rows.appendChild(row);
    });
    el.appendChild(rows);

    const src = document.createElement('div');
    src.className   = 'kkk-legend-source';
    src.textContent = '表示なしは危険度分布なしまたはデータなし。取得不可時は状態欄で通知します。出典: 気象庁';
    el.appendChild(src);

    // Phase 3-C: 判定の役割を短く説明し、取得不可を安全と誤読させない。
    const explain = document.createElement('div');
    explain.className = 'kkk-legend-explain';
    explain.innerHTML =
        '<div><strong>固定ハザード</strong>: 地形・浸水想定区域などの基本リスク</div>' +
        '<div><strong>キキクル</strong>: 気象庁のリアルタイム危険度分布</div>' +
        '<div><strong>リアルタイム補正</strong>: 固定ハザードと現在の危険度を組み合わせた補正</div>' +
        '<div><strong>取得不可</strong>: 判定できない状態であり、安全を意味しません</div>';
    el.appendChild(explain);

    el.dataset.built = '1';
}

function _kikikuruLegendUpdateKinds() {
    const el = document.getElementById('kkk-legend-kinds');
    if (!el) return;
    // フルJMA公式名で表示（Phase 3-C）
    const activeLabels = Object.entries(_kikikuruEnabled)
        .filter(([, v]) => v)
        .map(([k]) => _KIKIKURU_KINDS[k].label);
    el.textContent = activeLabels.length > 0 ? `表示中: ${activeLabels.join('・')}` : '';
}

function _kikikuruLegendShow() {
    const el = document.getElementById('kkk-legend');
    if (!el) return;
    _kikikuruLegendBuild();
    el.style.display = '';
}

function _kikikuruLegendHide() {
    const el = document.getElementById('kkk-legend');
    if (el) el.style.display = 'none';
}

// バックエンド補正をユーザー向け自然言語HTMLへ変換（Phase 3-C）
function _kkkAdjNaturalHtml(adj) {
    if (!adj?.enabled) return '';

    if (adj.status === 'unavailable') {
        return '<span class="kkk-adj-row kkk-adj-unavail">キキクル取得不可（補正なし）</span>';
    }
    if (adj.penalty <= 0) return '';

    const hasOverlap = Array.isArray(adj.matched_hazards) && adj.matched_hazards.length > 0;
    const hasDanger  = ['inund', 'flood', 'land'].some(k => _kkkRouteRisk[k] === 'danger');

    // 関与しているキキクル種別（caution / danger のもの）
    const activeKinds = ['inund', 'flood', 'land'].filter(k => {
        const lv = _kkkRouteRisk[k];
        return lv === 'caution' || lv === 'danger';
    });
    const kindText = activeKinds.length > 0
        ? activeKinds.map(k => _KIKIKURU_KINDS[k].label.replace('キキクル', '')).join('・')
        : 'キキクル';

    // メインメッセージ
    let mainMsg;
    if (hasOverlap && hasDanger) {
        mainMsg = `${kindText}リスクが上昇しています`;
    } else if (hasOverlap) {
        mainMsg = `${kindText}に注意が必要です`;
    } else if (hasDanger) {
        mainMsg = `${kindText}キキクルで危険を検出`;
    } else {
        mainMsg = `${kindText}に注意が必要です`;
    }

    const blockCls = hasOverlap
        ? 'kkk-adj-block kkk-adj-block--overlap'
        : 'kkk-adj-block';

    let html = `<div class="${blockCls}">`;
    html += `<span class="kkk-adj-label">リアルタイム補正</span>`;
    html += `<span class="kkk-adj-main">${mainMsg}</span>`;
    if (hasOverlap) {
        const hazardNames = adj.matched_hazards
            .map(h => getHazardDisplayName(h))
            .join('・');
        html += `<span class="kkk-adj-context">固定ハザード（${hazardNames}）とキキクルが重なっています</span>`;
    }
    html += '</div>';
    return html;
}

// ── 初期化 ───────────────────────────────────────────────────────────────────

window.addEventListener('load', () => {
    // 地図上ボタン（浸水のみ直接ON/OFF）
    const mapBtn = document.getElementById('kikikuru-map-btn');
    if (mapBtn) {
        mapBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const next = !_kikikuruEnabled.inund;
            _kikikuruSetVisible('inund', next);
            if (next) _kikikuruLegendShow(); else _kikikuruCheckLegendHide();
        });
    }

    // 情報パネル内の各 toggle ボタン
    for (const kind of Object.keys(_KIKIKURU_KINDS)) {
        const btn = document.getElementById(`kkk-toggle-${kind}`);
        if (btn) {
            btn.addEventListener('click', () => {
                const next = !_kikikuruEnabled[kind];
                _kikikuruSetVisible(kind, next);
                if (Object.values(_kikikuruEnabled).some(Boolean)) {
                    _kikikuruLegendShow();
                } else {
                    _kikikuruLegendHide();
                }
            });
        }
    }

    // 手動更新ボタン
    const refreshBtn = document.getElementById('kkk-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => refreshKikikuru());
    }

    _kikikuruLegendBuild();
    _kikikuruLegendHide();
    for (const kind of Object.keys(_KIKIKURU_KINDS)) {
        _kikikuruUpdateKindStatusUI(kind);
    }
    _kkkUpdateRiskUI('current');
    _kkkUpdateRiskUI('dest');
    _kkkUpdateRouteRiskUI();
});

function _kikikuruCheckLegendHide() {
    if (!Object.values(_kikikuruEnabled).some(Boolean)) {
        _kikikuruLegendHide();
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Phase 2 — 現在地・目的地 危険度サンプリング
// ═══════════════════════════════════════════════════════════════════════════════

// JMA危険度色（気象庁公式カラーコードに準拠）
const _KKK_RISK_COLORS = [
    { r: 123, g: 0,   b: 212, level: 'danger'  }, // #7b00d4 レベル5
    { r: 255, g: 40,  b: 0,   level: 'danger'  }, // #ff2800 レベル4
    { r: 255, g: 153, b: 0,   level: 'danger'  }, // #ff9900 レベル3
    { r: 240, g: 224, b: 0,   level: 'caution' }, // #f0e000 レベル2
    { r: 0,   g: 170, b: 0,   level: 'caution' }, // #00aa00 レベル1
];

const _kkkTileCache = new Map();
const _KKK_CACHE_MAX = 40;

// lat/lng → タイル座標 + タイル内ピクセル座標
function _kkkLatLngToTile(lat, lng, zoom) {
    const n = Math.pow(2, zoom);
    const tileX = Math.floor((lng + 180) / 360 * n);
    const latRad = lat * Math.PI / 180;
    const mercY = (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n;
    const tileY = Math.floor(mercY);
    const px = Math.min(255, Math.max(0, Math.floor((mercY - tileY) * 256)));
    const py = Math.min(255, Math.max(0, Math.floor(((lng + 180) / 360 * n - tileX) * 256)));
    return { x: tileX, y: tileY, px: py, py: px };
}

// RGB → risk level（最近傍色マッチング）
function _kkkColorToLevel(r, g, b, a) {
    if (a < 64) return 'none';
    let bestDist = Infinity, bestLevel = 'caution';
    for (const c of _KKK_RISK_COLORS) {
        const d = Math.abs(r - c.r) + Math.abs(g - c.g) + Math.abs(b - c.b);
        if (d < bestDist) { bestDist = d; bestLevel = c.level; }
    }
    // 不透明だがJMA危険度色として読めない色は safe 側へ倒さない。
    return bestDist < 120 ? bestLevel : 'unavailable';
}

// タイル画像をフェッチして ImageData を返す（キャッシュ付き）
function _kkkFetchTilePixels(url) {
    if (_kkkTileCache.has(url)) return Promise.resolve(_kkkTileCache.get(url));
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
            try {
                const canvas = document.createElement('canvas');
                canvas.width = 256; canvas.height = 256;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                const data = ctx.getImageData(0, 0, 256, 256);
                if (_kkkTileCache.size >= _KKK_CACHE_MAX) {
                    _kkkTileCache.delete(_kkkTileCache.keys().next().value);
                }
                _kkkTileCache.set(url, data);
                resolve(data);
            } catch (e) { reject(e); }
        };
        img.onerror = () => reject(new Error(`tile fetch failed: ${url}`));
        img.src = url;
    });
}

// 1地点・1種別のリスクレベルをサンプリング
async function _kkkSampleKind(lat, lng, entry, kind) {
    const def = _KIKIKURU_KINDS[kind];
    if (!entry.elements || !entry.elements.includes(def.elem)) return 'unavailable';
    const zoom = 10; // 偶数ズーム、maxNativeZoom=11 内
    const { x, y, px, py } = _kkkLatLngToTile(lat, lng, zoom);
    const url = `${_KIKIKURU_TILE_BASE}/${entry.basetime}/${entry.member}/${entry.validtime}/surf/${def.elem}/${zoom}/${x}/${y}.png`;
    try {
        const imgData = await _kkkFetchTilePixels(url);
        const idx = (py * 256 + px) * 4;
        const [r, g, b, a] = [
            imgData.data[idx], imgData.data[idx + 1],
            imgData.data[idx + 2], imgData.data[idx + 3],
        ];
        return _kkkColorToLevel(r, g, b, a);
    } catch (_) {
        return 'unavailable';
    }
}

// ── リスク状態 ───────────────────────────────────────────────────────────────

// status: 'off'|'loading'|'ok'|'unavailable'
const _kkkRisk = {
    current: { status: 'off', inund: null, flood: null, land: null },
    dest:    { status: 'off', inund: null, flood: null, land: null },
};
const _kkkRiskSampleVersion = { current: 0, dest: 0 };

function _kkkSetRiskUnavailable(target) {
    ++_kkkRiskSampleVersion[target];
    _kkkRisk[target] = { status: 'unavailable', inund: null, flood: null, land: null };
    _kkkUpdateRiskUI(target);
}

async function _kkkSampleLocation(target, lat, lng) {
    const sampleVersion = ++_kkkRiskSampleVersion[target];
    const entry = _kikikuruCurrentEntry;
    if (!entry) {
        if (sampleVersion === _kkkRiskSampleVersion[target]) {
            _kkkSetRiskUnavailable(target);
        }
        return;
    }
    _kkkRisk[target].status = 'loading';
    _kkkUpdateRiskUI(target);

    try {
        const kinds = Object.keys(_KIKIKURU_KINDS);
        const levels = await Promise.all(
            kinds.map(k => _kkkSampleKind(lat, lng, entry, k))
        );
        if (sampleVersion !== _kkkRiskSampleVersion[target]) return;
        kinds.forEach((k, i) => { _kkkRisk[target][k] = levels[i]; });
        _kkkRisk[target].status = 'ok';
    } catch (_) {
        if (sampleVersion !== _kkkRiskSampleVersion[target]) return;
        _kkkRisk[target].status = 'unavailable';
    }
    _kkkUpdateRiskUI(target);
}

// スロットル管理
let _kkkCurrentSampleLastAt = 0;
const _KKK_THROTTLE_MS = 60_000;

function _kkkTriggerCurrentSample(force) {
    if (typeof currentLocation === 'undefined' || !currentLocation) return;
    const now = Date.now();
    if (!force && now - _kkkCurrentSampleLastAt < _KKK_THROTTLE_MS) return;
    _kkkCurrentSampleLastAt = now;
    _kkkSampleLocation('current', currentLocation.lat, currentLocation.lon).catch(() => {});
}

function _kkkTriggerDestSample() {
    const dest = (typeof navDestination !== 'undefined' && navDestination)
        || (typeof userDestination !== 'undefined' && userDestination)
        || null;
    if (!dest) {
        ++_kkkRiskSampleVersion.dest;
        _kkkRisk.dest.status = 'off';
        _kkkRisk.dest.inund = null;
        _kkkRisk.dest.flood = null;
        _kkkRisk.dest.land = null;
        _kkkUpdateRiskUI('dest');
        return;
    }
    _kkkSampleLocation('dest', dest.lat, dest.lon).catch(() => {});
}

// refreshKikikuru 成功後に呼ぶ — キャッシュを無効化して再サンプリング
function _kkkSampleAll() {
    _kkkTileCache.clear();
    _kkkCurrentSampleLastAt = 0;
    _kkkTriggerCurrentSample(true);
    _kkkTriggerDestSample();
    if (typeof navActiveRoute !== 'undefined' && navActiveRoute
            && Array.isArray(navActiveRoute.coordinates)
            && navActiveRoute.coordinates.length > 0) {
        _kkkSampleRoute(navActiveRoute.coordinates).catch(() => {});
    }
}

// 現在地ポーリング（30秒）
let _kkkLocationPollTimer = null;

function _kkkStartLocationPoll() {
    if (_kkkLocationPollTimer) return;
    _kkkLocationPollTimer = setInterval(() => {
        _kkkTriggerCurrentSample(false);
        _kkkTriggerDestSample();
    }, 30_000);
}

function _kkkStopLocationPoll() {
    if (_kkkLocationPollTimer) {
        clearInterval(_kkkLocationPollTimer);
        _kkkLocationPollTimer = null;
    }
}

// ── リスクUI ─────────────────────────────────────────────────────────────────

function _kkkRiskLabel(level) {
    switch (level) {
        case 'danger':      return { text: '危険',    cls: 'kkk-risk--danger'  };
        case 'caution':     return { text: '注意',    cls: 'kkk-risk--caution' };
        case 'none':        return { text: 'なし',    cls: 'kkk-risk--none'    };
        case 'unavailable': return { text: '取得不可', cls: 'kkk-risk--unavail' };
        default:            return { text: '確認中',  cls: 'kkk-risk--loading' };
    }
}

function _kkkUpdateRiskUI(target) {
    const el = document.getElementById(`kkk-risk-${target}`);
    if (!el) return;
    const rows = el.querySelector('.kkk-risk-rows');
    if (!rows) return;

    if (target === 'dest') {
        const hasDest = (typeof navDestination !== 'undefined' && navDestination)
            || (typeof userDestination !== 'undefined' && userDestination);
        el.style.display = hasDest ? '' : 'none';
        if (!hasDest) return;
    } else {
        el.style.display = '';
    }

    const st = _kkkRisk[target].status;
    if (st === 'off') {
        rows.innerHTML = '<span class="kkk-risk-msg">取得前</span>';
        return;
    }
    if (st === 'unavailable') {
        rows.innerHTML = '<span class="kkk-risk-msg">取得不可</span>';
        return;
    }
    if (st === 'loading') {
        rows.innerHTML = '<span class="kkk-risk-msg">確認中…</span>';
        return;
    }
    rows.innerHTML = Object.keys(_KIKIKURU_KINDS).map(kind => {
        const kindLabel = _KIKIKURU_KINDS[kind].label.replace('キキクル', '');
        const { text, cls } = _kkkRiskLabel(_kkkRisk[target][kind]);
        return `<span class="kkk-risk-item">${kindLabel}:<span class="kkk-risk-badge ${cls}">${text}</span></span>`;
    }).join('');
}

// 公開: 目的地変更時に外部から呼べるフック
function kikikuruOnDestinationChange() {
    _kkkTriggerDestSample();
}

// ═══════════════════════════════════════════════════════════════════════════════
// Phase 3-A — ルート周辺 危険度サンプリング
// ═══════════════════════════════════════════════════════════════════════════════

// 危険度集約（最悪レベル優先）
const _KKK_LEVEL_ORDER = { unavailable: 4, danger: 3, caution: 2, none: 1 };

function _kkkWorseLevel(a, b) {
    return (_KKK_LEVEL_ORDER[a] || 0) >= (_KKK_LEVEL_ORDER[b] || 0) ? a : b;
}

// ルート座標を最大 maxPts 点に均等間引き（現在地があれば前方優先）
function _kkkSubsampleRoute(coords, maxPts) {
    if (!coords.length) return [];
    let startIdx = 0;
    if (typeof currentLocation !== 'undefined' && currentLocation) {
        let bestDist = Infinity;
        for (let i = 0; i < coords.length; i++) {
            const dlat = coords[i].lat - currentLocation.lat;
            const dlng = coords[i].lng - currentLocation.lon;
            const d = dlat * dlat + dlng * dlng;
            if (d < bestDist) { bestDist = d; startIdx = i; }
        }
    }
    const pool = coords.slice(startIdx);
    if (pool.length <= maxPts) return pool;
    const step = pool.length / maxPts;
    return Array.from({ length: maxPts }, (_, i) =>
        pool[Math.min(Math.floor(i * step), pool.length - 1)]
    );
}

// ルートリスク状態
const _kkkRouteRisk = { status: 'off', inund: null, flood: null, land: null };
let _kkkRouteVersion = 0;

function _kkkSetRouteRiskUnavailable() {
    ++_kkkRouteVersion;
    _kkkRouteRisk.status = 'unavailable';
    _kkkRouteRisk.inund = null;
    _kkkRouteRisk.flood = null;
    _kkkRouteRisk.land = null;
    _kkkUpdateRouteRiskUI();
}

async function _kkkSampleRoute(coords) {
    const version = ++_kkkRouteVersion;
    _kkkBackendAdj = null;
    _kkkRouteRisk.status = 'loading';
    _kkkUpdateRouteRiskUI();

    const entry = _kikikuruCurrentEntry;
    if (!entry) {
        if (version === _kkkRouteVersion) {
            _kkkRouteRisk.status = 'unavailable';
            _kkkUpdateRouteRiskUI();
        }
        return;
    }

    const sample = _kkkSubsampleRoute(coords, 12);
    const kinds = Object.keys(_KIKIKURU_KINDS);
    const worst = { inund: null, flood: null, land: null };

    for (const pt of sample) {
        if (version !== _kkkRouteVersion) return; // 新しいルートに切り替わった
        const levels = await Promise.all(kinds.map(k => _kkkSampleKind(pt.lat, pt.lng, entry, k)));
        kinds.forEach((k, i) => {
            worst[k] = worst[k] === null ? levels[i] : _kkkWorseLevel(worst[k], levels[i]);
        });
    }

    if (version !== _kkkRouteVersion) return;
    Object.assign(_kkkRouteRisk, worst);
    _kkkRouteRisk.status = 'ok';
    _kkkUpdateRouteRiskUI();
}

async function _kkkSampleRouteForBackend(coords) {
    const entry = _kikikuruCurrentEntry;
    if (!entry || !Array.isArray(coords) || coords.length === 0) {
        return { status: 'unavailable', inund: null, flood: null, land: null };
    }

    const sample = _kkkSubsampleRoute(coords, 12);
    const kinds = Object.keys(_KIKIKURU_KINDS);
    const worst = { inund: null, flood: null, land: null };

    try {
        for (const pt of sample) {
            const levels = await Promise.all(kinds.map(k => _kkkSampleKind(pt.lat, pt.lng, entry, k)));
            kinds.forEach((k, i) => {
                worst[k] = worst[k] === null ? levels[i] : _kkkWorseLevel(worst[k], levels[i]);
            });
        }
    } catch (_) {
        return { status: 'unavailable', inund: null, flood: null, land: null };
    }

    return { status: 'ok', inund: worst.inund, flood: worst.flood, land: worst.land };
}

// 公開: ルート変更時に外部から呼ぶフック
function kikikuruOnRouteChange(route) {
    if (!route || !Array.isArray(route.coordinates) || route.coordinates.length === 0) {
        ++_kkkRouteVersion; // in-flight を無効化
        _kkkRouteRisk.status = 'off';
        _kkkRouteRisk.inund = null;
        _kkkRouteRisk.flood = null;
        _kkkRouteRisk.land  = null;
        _kkkBackendAdj = null; // Phase 3-B: 旧補正をクリア
        _kkkUpdateRouteRiskUI();
        return;
    }
    _kkkSampleRoute(route.coordinates).catch(() => {
        if (_kkkRouteRisk.status === 'loading') {
            _kkkRouteRisk.status = 'unavailable';
            _kkkUpdateRouteRiskUI();
        }
    });
}

// Phase 3-B — バックエンドから受け取ったキキクル補正結果
let _kkkBackendAdj = null;

// 公開: navigation.js から _assessRouteHazardRisk のレスポンスで呼ばれる
function kikikuruSetBackendAdjustment(adj) {
    _kkkBackendAdj = adj || null;
    _kkkUpdateRouteRiskUI();
}

function _kkkUpdateRouteRiskUI() {
    const el = document.getElementById('kkk-risk-route');
    if (!el) return;
    const rows = el.querySelector('.kkk-risk-rows');
    if (!rows) return;

    const st = _kkkRouteRisk.status;
    el.style.display = st === 'off' ? 'none' : '';
    if (st === 'off') return;

    if (st === 'unavailable') {
        rows.innerHTML = '<span class="kkk-risk-msg">取得不可</span>';
        return;
    }
    if (st === 'loading') {
        rows.innerHTML = '<span class="kkk-risk-msg">確認中…</span>';
        return;
    }

    // 種別ごとのリスク行
    let html = Object.keys(_KIKIKURU_KINDS).map(kind => {
        const kindLabel = _KIKIKURU_KINDS[kind].label.replace('キキクル', '');
        const { text, cls } = _kkkRiskLabel(_kkkRouteRisk[kind]);
        return `<span class="kkk-risk-item">${kindLabel}:<span class="kkk-risk-badge ${cls}">${text}</span></span>`;
    }).join('');

    // バックエンド補正（Phase 3-C: 自然文表示）
    html += _kkkAdjNaturalHtml(_kkkBackendAdj);

    rows.innerHTML = html;
}
