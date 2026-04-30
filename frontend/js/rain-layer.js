'use strict';

/**
 * rain-layer.js — JMA 降水ナウキャストタイルレイヤー（Phase2B）
 *
 * 外部から呼ぶ:
 *   _rainLayerSetVisible(visible)  — ON/OFF 切替（地図オーバーレイボタンから）
 *
 * 実装方針:
 *   - /api/weather/rain/tile/latest から basetime/validtime/tile_url_template を取得
 *   - Leaflet TileLayer として地図に重ねる（opacity 0.6）
 *   - TTL 秒間はキャッシュ（再取得しない）
 *   - 取得失敗時はサイレント失敗 → 既存レイヤーを壊さない
 *   - 将来 XRAIN に差し替える場合はバックエンドのみ変更
 */

let _rainLayer   = null;    // Leaflet TileLayer | null
let _rainVisible = false;

let _rainTileCache = null;  // { data, fetchedAt }

// ── タイル情報取得（TTL キャッシュ付き） ────────────────────────────────────

async function _rainFetchTileInfo() {
    const now = Date.now();
    if (
        _rainTileCache &&
        now - _rainTileCache.fetchedAt < (_rainTileCache.data.ttl_seconds || 120) * 1000
    ) {
        return _rainTileCache.data;
    }

    const res = await fetch('/api/weather/rain/tile/latest');
    if (!res.ok) throw new Error(`rain tile API ${res.status}`);
    const data = await res.json();
    _rainTileCache = { data, fetchedAt: now };
    return data;
}

// ── Leaflet レイヤー操作 ──────────────────────────────────────────────────

function _rainLayerRemove() {
    if (_rainLayer) {
        try { map.removeLayer(_rainLayer); } catch (_) {}
        _rainLayer = null;
    }
}

async function _rainLayerAdd() {
    try {
        const info = await _rainFetchTileInfo();
        if (!info || !info.tile_url_template) {
            throw new Error('rain tile: tile_url_template missing');
        }

        _rainLayerRemove();

        _rainLayer = L.tileLayer(info.tile_url_template, {
            opacity:       0.6,
            attribution:   '気象庁 降水ナウキャスト',
            minZoom:       4,
            maxNativeZoom: 10,
            maxZoom:       18,
            tileSize:      256,
            zIndex:        450,
        });

        // ハザードレイヤーより手前、ルート線より背面に配置
        _rainLayer.addTo(map);

        _rainLegendShow(info);

    } catch (err) {
        console.warn('[rain-layer] failed to add layer:', err);
        _rainVisible = false;
        _rainUpdateButtonState();
        if (typeof showMapToast === 'function') {
            showMapToast('雨量レーダー取得不可', { warn: true, durationMs: 4000 });
        }
    }
}

// ── ON / OFF 切替（外部エントリポイント） ────────────────────────────────────

function _rainLayerSetVisible(visible) {
    _rainVisible = visible;
    _rainUpdateButtonState();

    if (visible) {
        _rainLayerAdd();
    } else {
        _rainLayerRemove();
        _rainLegendHide();
    }
}

function _rainUpdateButtonState() {
    const btn = document.getElementById('rain-toggle-btn');
    if (btn) btn.classList.toggle('map-overlay-btn--active', _rainVisible);
}

// ── 凡例 ────────────────────────────────────────────────────────────────────

// JMA 降水ナウキャスト配色（公式仕様に準拠）
const _RAIN_LEGEND_ENTRIES = [
    { color: '#a50026', label: '80 mm/h 以上' },
    { color: '#d73027', label: '50〜80'        },
    { color: '#f46d43', label: '30〜50'        },
    { color: '#fdae61', label: '20〜30'        },
    { color: '#fee090', label: '10〜20'        },
    { color: '#e0f3f8', label: '5〜10'         },
    { color: '#abd9e9', label: '1〜5'          },
    { color: '#74add1', label: '0.5〜1'        },
];

function _rainLegendBuild() {
    const el = document.getElementById('rain-legend');
    if (!el || el.dataset.built) return;

    const title = document.createElement('div');
    title.className = 'rain-legend-title';
    title.textContent = '雨量レーダー';
    el.appendChild(title);

    const timeEl = document.createElement('div');
    timeEl.id = 'rain-legend-time';
    timeEl.className = 'rain-legend-time';
    el.appendChild(timeEl);

    const rows = document.createElement('div');
    rows.className = 'rain-legend-rows';
    _RAIN_LEGEND_ENTRIES.forEach(entry => {
        const row = document.createElement('div');
        row.className = 'rain-legend-row';
        row.innerHTML = `<span class="rain-legend-swatch" style="background:${entry.color}"></span><span class="rain-legend-label">${entry.label}</span>`;
        rows.appendChild(row);
    });
    el.appendChild(rows);

    const src = document.createElement('div');
    src.className = 'rain-legend-source';
    src.textContent = '出典: 気象庁';
    el.appendChild(src);

    el.dataset.built = '1';
}

function _rainLegendShow(info) {
    const el = document.getElementById('rain-legend');
    if (!el) return;

    _rainLegendBuild();

    // validtime "20250430120000" → "12:00 JST"
    const timeEl = document.getElementById('rain-legend-time');
    if (timeEl && info.validtime && info.validtime.length >= 12) {
        const vt   = info.validtime;
        const hour = vt.substring(8,  10);
        const min  = vt.substring(10, 12);
        timeEl.textContent = `${hour}:${min} JST`;
    }

    el.style.display = '';
}

function _rainLegendHide() {
    const el = document.getElementById('rain-legend');
    if (el) el.style.display = 'none';
}

// ── 初期化 ───────────────────────────────────────────────────────────────────

window.addEventListener('load', () => {
    const btn = document.getElementById('rain-toggle-btn');
    if (btn) {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            _rainLayerSetVisible(!_rainVisible);
        });
    }

    _rainLegendBuild();
    _rainLegendHide();
});
