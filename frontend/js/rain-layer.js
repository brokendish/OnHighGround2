'use strict';

/**
 * rain-layer.js — JMA 降水ナウキャスト（Phase2B + 自動更新/スライダー/アニメーション）
 *
 * 外部エントリポイント:
 *   _rainLayerSetVisible(visible)      — ON/OFF 切替
 *
 * 公開関数（state.js の rainRadar オブジェクトと連動）:
 *   refreshRainRadar()                 — 最新 basetime に更新（同一時刻はスキップ）
 *   startRainRadarAutoRefresh()        — 5分ごと自動更新開始
 *   stopRainRadarAutoRefresh()         — 自動更新停止
 *   setRainRadarOffset(offsetMinutes)  — 予測オフセット変更
 *   updateRainRadarLayer()             — 現在 offset でレイヤー更新
 *   startRainRadarAnimation()          — 0→60分 順再生（1秒/フレーム）
 *   stopRainRadarAnimation()           — アニメーション停止
 *
 * UI 配置:
 *   - スライダー・再生ボタン → 情報タブ #lip-rain-radar-ctrl-section
 *   - カラースケール + 時刻  → 凡例タブ #rain-legend
 */

let _rainLayer    = null;   // Leaflet TileLayer | null
let _rainAllTimes = [];     // [{validtime, offset_minutes, tile_url_template}]

// ── API fetch ────────────────────────────────────────────────────────────────

async function _rainFetchTimes() {
    const res = await fetch('/api/weather/rain/tile/times');
    if (!res.ok) throw new Error(`rain tile times API ${res.status}`);
    return await res.json();
}

// ── Leaflet レイヤー操作 ──────────────────────────────────────────────────────

function _rainLayerRemove() {
    if (_rainLayer) {
        try { map.removeLayer(_rainLayer); } catch (_) {}
        _rainLayer = null;
    }
}

const _RAIN_TILE_OPTIONS = {
    opacity:       0.6,
    attribution:   '気象庁 降水ナウキャスト',
    minZoom:       4,
    maxNativeZoom: 10,
    maxZoom:       18,
    tileSize:      256,
    zIndex:        450,
};

// ── Step1: 自動更新 ───────────────────────────────────────────────────────────

async function refreshRainRadar() {
    try {
        const data = await _rainFetchTimes();
        if (!data || !data.basetime) return;

        if (data.basetime === rainRadar.baseTime) return;  // 同一 basetime はスキップ

        rainRadar.baseTime = data.basetime;
        _rainAllTimes = data.times || [];

        const offsetExists = _rainAllTimes.some(t => t.offset_minutes === rainRadar.offset);
        if (!offsetExists) rainRadar.offset = 0;

        updateRainRadarLayer();
        _rainInfoCtrlUpdate(data);

    } catch (err) {
        console.warn('[rain-layer] refresh failed (keeping existing layer):', err);
    }
}

function startRainRadarAutoRefresh() {
    stopRainRadarAutoRefresh();
    rainRadar.timer = setInterval(refreshRainRadar, 5 * 60 * 1000);
}

function stopRainRadarAutoRefresh() {
    if (rainRadar.timer) {
        clearInterval(rainRadar.timer);
        rainRadar.timer = null;
    }
}

// ── Step2: オフセット切替 / レイヤー更新 ──────────────────────────────────────

function _rainNearestEntry(offset) {
    if (!_rainAllTimes.length) return null;
    return _rainAllTimes.find(t => t.offset_minutes === offset)
        || _rainAllTimes.reduce((a, b) =>
            Math.abs(a.offset_minutes - offset) <= Math.abs(b.offset_minutes - offset) ? a : b
        );
}

function updateRainRadarLayer() {
    const entry = _rainNearestEntry(rainRadar.offset);
    if (!entry) return;

    if (_rainLayer) {
        _rainLayer.setUrl(entry.tile_url_template);
    } else {
        _rainLayer = L.tileLayer(entry.tile_url_template, _RAIN_TILE_OPTIONS).addTo(map);
    }

    _rainTimeDisplay(entry);
}

function setRainRadarOffset(offsetMinutes) {
    rainRadar.offset = offsetMinutes;
    updateRainRadarLayer();
    _rainSliderSync();
}

// ── Step3: アニメーション ────────────────────────────────────────────────────

function startRainRadarAnimation() {
    stopRainRadarAnimation();

    const offsets = _rainAllTimes.map(t => t.offset_minutes).sort((a, b) => a - b);
    if (offsets.length < 2) return;

    let idx = offsets.indexOf(rainRadar.offset);
    if (idx < 0) idx = 0;

    _rainAnimBtnUpdate(true);

    rainRadar.animationTimer = setInterval(() => {
        idx = (idx + 1) % offsets.length;
        rainRadar.offset = offsets[idx];
        updateRainRadarLayer();
        _rainSliderSync();
    }, 1000);
}

function stopRainRadarAnimation() {
    if (rainRadar.animationTimer) {
        clearInterval(rainRadar.animationTimer);
        rainRadar.animationTimer = null;
    }
    _rainAnimBtnUpdate(false);
}

// ── ON / OFF 切替（外部エントリポイント） ────────────────────────────────────

async function _rainLayerAdd() {
    try {
        const data = await _rainFetchTimes();
        if (!data || !data.times || !data.times.length) {
            throw new Error('rain tile: no times returned');
        }

        rainRadar.baseTime = data.basetime;
        _rainAllTimes      = data.times;
        rainRadar.offset   = 0;   // 0 = 最新観測

        _rainLayerRemove();
        updateRainRadarLayer();
        _rainInfoCtrlUpdate(data);
        _rainInfoCtrlShow();
        _rainLegendShow();
        startRainRadarAutoRefresh();

    } catch (err) {
        console.warn('[rain-layer] failed to add layer:', err);
        rainRadar.enabled = false;
        _rainUpdateButtonState();
        if (typeof showMapToast === 'function') {
            showMapToast('雨量レーダー取得不可', { warn: true, durationMs: 4000 });
        }
    }
}

function _rainLayerSetVisible(visible) {
    rainRadar.enabled = visible;
    _rainUpdateButtonState();

    if (visible) {
        _rainLayerAdd();
    } else {
        stopRainRadarAnimation();
        stopRainRadarAutoRefresh();
        _rainLayerRemove();
        _rainInfoCtrlHide();
        _rainLegendHide();
        rainRadar.baseTime = null;
        rainRadar.offset   = 0;
        _rainAllTimes = [];
    }
}

function _rainUpdateButtonState() {
    const btn = document.getElementById('rain-toggle-btn');
    if (btn) btn.classList.toggle('map-overlay-btn--active', rainRadar.enabled);
}

// ── 情報タブ コントロール UI ──────────────────────────────────────────────────

function _rainInfoCtrlShow() {
    const el = document.getElementById('lip-rain-radar-ctrl-section');
    if (el) el.style.display = '';
}

function _rainInfoCtrlHide() {
    const el = document.getElementById('lip-rain-radar-ctrl-section');
    if (el) el.style.display = 'none';
}

function _rainInfoCtrlUpdate(data) {
    const slider  = document.getElementById('lip-rain-slider');
    const animBtn = document.getElementById('lip-rain-anim-btn');
    if (!slider || !data || !data.times) return;

    const offsets   = data.times.map(t => t.offset_minutes).sort((a, b) => a - b);
    const minOffset = offsets.length > 0 ? offsets[0]  : 0;   // 負値（過去）
    const maxOffset = offsets.length > 0 ? offsets[offsets.length - 1] : 0;  // 0（最新）
    const hasRange  = offsets.length >= 2;

    slider.min      = String(minOffset);
    slider.max      = String(maxOffset);
    slider.step     = '5';
    slider.disabled = !hasRange;

    if (animBtn) animBtn.disabled = !hasRange;

    _rainSliderSync();
}

function _rainSliderSync() {
    const slider = document.getElementById('lip-rain-slider');
    if (slider) slider.value = String(rainRadar.offset);
}

function _rainAnimBtnUpdate(playing) {
    const btn = document.getElementById('lip-rain-anim-btn');
    if (!btn) return;
    btn.textContent = playing ? '■ 停止' : '▶ 再生';
    btn.classList.toggle('lip-rain-anim-btn--playing', playing);
}

// ── 時刻表示（情報タブ + 凡例パネルを同時更新） ──────────────────────────────

function _rainTimeDisplay(entry) {
    const vt  = entry.validtime || '';
    const off = entry.offset_minutes || 0;

    let timeStr = '';
    if (vt.length >= 12) {
        const hour = vt.substring(8, 10);
        const min  = vt.substring(10, 12);
        timeStr = `${hour}:${min} JST`;
    }

    // offset は 0=最新観測、負値=過去、正値=予測
    let offsetStr;
    if (off === 0)    offsetStr = '現在';
    else if (off < 0) offsetStr = `${Math.abs(off)}分前`;
    else              offsetStr = `+${off}分予測`;

    // 情報タブ
    const infoTime   = document.getElementById('lip-rain-time-text');
    const infoOffset = document.getElementById('lip-rain-offset-label');
    if (infoTime)   infoTime.textContent   = timeStr;
    if (infoOffset) infoOffset.textContent = offsetStr;

    // 凡例タブ
    const legendTime = document.getElementById('rain-legend-time');
    if (legendTime) {
        legendTime.textContent = timeStr
            ? `${timeStr}（${offsetStr}）`
            : offsetStr;
    }
}

// ── 凡例 ─────────────────────────────────────────────────────────────────────

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
    title.className   = 'rain-legend-title';
    title.textContent = '雨量レーダー';
    el.appendChild(title);

    const timeEl = document.createElement('div');
    timeEl.id        = 'rain-legend-time';
    timeEl.className = 'rain-legend-time';
    el.appendChild(timeEl);

    const rows = document.createElement('div');
    rows.className = 'rain-legend-rows';
    _RAIN_LEGEND_ENTRIES.forEach(entry => {
        const row = document.createElement('div');
        row.className = 'rain-legend-row';
        row.innerHTML = `<span class="rain-legend-swatch" style="background:${entry.color}"></span>`
                      + `<span class="rain-legend-label">${entry.label}</span>`;
        rows.appendChild(row);
    });
    el.appendChild(rows);

    const src = document.createElement('div');
    src.className   = 'rain-legend-source';
    src.textContent = '出典: 気象庁';
    el.appendChild(src);

    el.dataset.built = '1';
}

function _rainLegendShow() {
    const el = document.getElementById('rain-legend');
    if (!el) return;
    _rainLegendBuild();
    el.style.display = '';
}

function _rainLegendHide() {
    const el = document.getElementById('rain-legend');
    if (el) el.style.display = 'none';
}

// ── 初期化 ───────────────────────────────────────────────────────────────────

window.addEventListener('load', () => {
    // 地図オーバーレイ ON/OFF ボタン
    const btn = document.getElementById('rain-toggle-btn');
    if (btn) {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            _rainLayerSetVisible(!rainRadar.enabled);
        });
    }

    // 情報タブ: 予測スライダー
    const slider = document.getElementById('lip-rain-slider');
    if (slider) {
        slider.addEventListener('input', () => {
            stopRainRadarAnimation();
            setRainRadarOffset(parseInt(slider.value, 10));
        });
    }

    // 情報タブ: 再生/停止ボタン
    const animBtn = document.getElementById('lip-rain-anim-btn');
    if (animBtn) {
        animBtn.addEventListener('click', () => {
            if (rainRadar.animationTimer) {
                stopRainRadarAnimation();
            } else {
                startRainRadarAnimation();
            }
        });
    }

    _rainLegendBuild();
    _rainLegendHide();
});
