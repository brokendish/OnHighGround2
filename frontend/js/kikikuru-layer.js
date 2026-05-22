'use strict';

/**
 * kikikuru-layer.js — 気象庁キキクル（危険度分布）表示レイヤー
 *
 * 外部エントリポイント:
 *   _kikikuruSetVisible(kind, visible)  — kind: 'inund'|'land'|'flood'
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
const _KIKIKURU_KINDS = {
    inund: { label: '浸水キキクル', elem: 'inund', zIndex: 440 },
    land:  { label: '土砂キキクル', elem: 'land',  zIndex: 441 },
    flood: { label: '洪水キキクル', elem: 'flood', zIndex: 442 },
};

// 危険度凡例（気象庁の危険度色に準拠）
const _KIKIKURU_LEGEND = [
    { color: '#7b00d4', label: '災害切迫（レベル5）' },
    { color: '#ff2800', label: '危険（レベル4）'     },
    { color: '#ff9900', label: '警戒（レベル3）'     },
    { color: '#f0e000', label: '注意（レベル2）'     },
    { color: '#00aa00', label: '今後の情報等に留意'  },
];

// 状態
let _kikikuruCurrentEntry = null;   // targetTimesの最新エントリ
let _kikikuruLastUpdated  = null;   // 最終取得成功時刻（Date）
let _kikikuruStatus       = 'init'; // 'init'|'ok'|'stale'|'error'
let _kikikuruTimer        = null;

// レイヤーインスタンス（kind → TileLayer | null）
const _kikikuruLayers = { inund: null, land: null, flood: null };
// 有効フラグ（kind → bool）
const _kikikuruEnabled = { inund: false, land: false, flood: false };

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
        if (!_kikikuruCurrentEntry) {
            refreshKikikuru();
        } else {
            _kikikuruUpdateLayer(kind);
        }
    } else {
        _kikikuruRemoveLayer(kind);
    }

    _kikikuruSyncPanelVisibility();
}

// ── 更新処理 ────────────────────────────────────────────────────────────────

async function refreshKikikuru() {
    _kikikuruSetStatusUI('checking');
    try {
        const entry = await _kikikuruFetchLatest();

        const isNew = !_kikikuruCurrentEntry
            || entry.basetime !== _kikikuruCurrentEntry.basetime;

        _kikikuruCurrentEntry = entry;
        _kikikuruLastUpdated  = new Date();
        _kikikuruStatus       = 'ok';

        if (isNew) {
            for (const kind of Object.keys(_kikikuruEnabled)) {
                if (_kikikuruEnabled[kind]) _kikikuruUpdateLayer(kind);
            }
        }

        _kikikuruSetStatusUI('ok');

    } catch (err) {
        console.warn('[kikikuru] fetch failed:', err);
        if (_kikikuruCurrentEntry) {
            _kikikuruStatus = 'stale';
            _kikikuruSetStatusUI('stale');
        } else {
            _kikikuruStatus = 'error';
            _kikikuruSetStatusUI('error');
        }
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

// ── UI 状態 ──────────────────────────────────────────────────────────────────

function _kikikuruSetStatusUI(status) {
    const statusEl  = document.getElementById('kkk-status-text');
    const timeEl    = document.getElementById('kkk-updated-time');
    const badgeEl   = document.getElementById('kkk-status-badge');

    const timeStr = _kikikuruLastUpdated
        ? _kikikuruLastUpdated.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
        : '';

    const validtimeStr = _kikikuruCurrentEntry
        ? _kikikuruFmtValidtime(_kikikuruCurrentEntry.validtime)
        : '';

    if (statusEl) {
        switch (status) {
            case 'checking':
                statusEl.textContent = '更新確認中…';
                break;
            case 'ok':
                statusEl.textContent = validtimeStr ? `${validtimeStr} 時点` : '取得済み';
                break;
            case 'stale':
                statusEl.textContent = '情報が古い可能性があります';
                break;
            case 'error':
                statusEl.textContent = '取得不可';
                break;
        }
    }

    if (timeEl) {
        timeEl.textContent = timeStr ? `（取得: ${timeStr}）` : '';
    }

    if (badgeEl) {
        badgeEl.className    = 'kkk-status-badge';
        badgeEl.style.display = '';
        switch (status) {
            case 'ok':       badgeEl.classList.add('kkk-badge--ok');      badgeEl.textContent = '正常'; break;
            case 'checking': badgeEl.classList.add('kkk-badge--check');   badgeEl.textContent = '確認中'; break;
            case 'stale':    badgeEl.classList.add('kkk-badge--stale');   badgeEl.textContent = '古い可能性'; break;
            case 'error':    badgeEl.classList.add('kkk-badge--error');   badgeEl.textContent = '取得不可'; break;
        }
    }

    // 凡例パネル内の時刻も更新
    const legendTime = document.getElementById('kkk-legend-time');
    if (legendTime) legendTime.textContent = validtimeStr ? `${validtimeStr} 時点の危険度` : '';
}

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

    // 自動更新の開始/停止
    if (anyOn) {
        if (!_kikikuruTimer) _kikikuruStartAutoRefresh();
    } else {
        _kikikuruStopAutoRefresh();
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

    el.dataset.built = '1';
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

// ── 初期化 ───────────────────────────────────────────────────────────────────

window.addEventListener('load', () => {
    // 地図上ボタン（浸水のみ直接ON/OFF）
    const mapBtn = document.getElementById('kikikuru-map-btn');
    if (mapBtn) {
        mapBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const next = !_kikikuruEnabled.inund;
            _kikikuruSetVisible('inund', next);
            mapBtn.classList.toggle('map-overlay-btn--active', next);
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
});

function _kikikuruCheckLegendHide() {
    if (!Object.values(_kikikuruEnabled).some(Boolean)) {
        _kikikuruLegendHide();
    }
}
