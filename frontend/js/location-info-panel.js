'use strict';

/**
 * location-info-panel.js — 非ナビ時の現在地情報パネル
 *
 * 情報タブの #loc-info-nonnav を管理する。
 * ナビ中は #loc-info-nav（既存の避難先情報）を表示し、このパネルは非表示。
 * 非ナビ時はこのパネルを表示し、#loc-info-nav を非表示にする。
 *
 * 既存処理を流用（新規watchPosition不要）:
 *   _lipUpdate()        ← fetchCurrentLocInfo() からフック
 *   _lipUpdateHazard()  ← _checkCurrentHazard() 結果からフック
 *   _lipUpdateElev()    ← _fetchElevation() 結果からフック
 *   _lipUpdateNavMode() ← _updateNavUI() 末尾からフック
 */

// ── 状態 ─────────────────────────────────────────────────────────
let _lipLastUpdateAt      = null;  // epoch ms
let _lipHazardAssessment  = null;  // {tsunami, flood, ...} or null
let _lipElevation         = null;  // number or null
let _lipLat               = null;
let _lipLon               = null;
let _lipAcc               = null;
let _lipAgeTimer          = null;  // setInterval ID

// ── エントリーポイント（navigation.js からフック） ────────────────

/**
 * 位置更新時に呼ぶ（fetchCurrentLocInfo から）。
 * @param {number} lat
 * @param {number} lon
 * @param {number|null} accuracy  GPS精度 (m)
 */
function _lipUpdate(lat, lon, accuracy) {
    _lipLat = lat;
    _lipLon = lon;
    _lipAcc = accuracy;
    _lipLastUpdateAt = Date.now();
    _lipRenderPosition();
    _lipRenderShelter();
    _lipStartAgeTimer();
}

/**
 * ハザード判定結果を受け取る（_checkCurrentHazard の結果からフック）。
 * @param {object|null} assessment  {tsunami, flood, landslide, ...}
 */
function _lipUpdateHazard(assessment) {
    _lipHazardAssessment = assessment || null;
    _lipRenderHazard();
}

/**
 * 標高更新時に呼ぶ（_fetchElevation の結果からフック）。
 * @param {number|null} elev
 */
function _lipUpdateElev(elev) {
    _lipElevation = elev;
    _lipRenderElev();
}

/**
 * ナビモード変更時に呼ぶ（_updateNavUI 末尾からフック）。
 * @param {string} mode  navigationMode の値
 */
function _lipUpdateNavMode(mode) {
    const isNav = mode === 'navigation_active'
               || mode === 'navigation_warning'
               || mode === 'navigation_paused'
               || mode === 'navigation_finished';

    const elNonNav = document.getElementById('loc-info-nonnav');
    const elNav    = document.getElementById('loc-info-nav');
    if (!elNonNav || !elNav) return;

    if (isNav) {
        elNonNav.style.display = 'none';
        elNav.style.display    = '';
        _lipStopAgeTimer();
    } else {
        elNonNav.style.display = '';
        elNav.style.display    = 'none';
        if (_lipLastUpdateAt) _lipStartAgeTimer();
    }
}

// ── 内部レンダリング ───────────────────────────────────────────────

function _lipRenderPosition() {
    _lipSet('lip-lat', _lipLat != null ? _lipLat.toFixed(6) : '--');
    _lipSet('lip-lon', _lipLon != null ? _lipLon.toFixed(6) : '--');
    _lipSet('lip-acc', _lipAcc != null ? `±${Math.round(_lipAcc)} m` : '--');
    _lipRenderAge();
}

function _lipRenderElev() {
    _lipSet('lip-elev', _lipElevation != null ? `${Math.round(_lipElevation)} m` : '--');
}

function _lipRenderHazard() {
    const a = _lipHazardAssessment;

    // 津波
    _lipSetHazard('lip-h-tsunami', a ? a.tsunami : undefined, {
        insideLabel: '⚠️ 該当',
        outsideLabel: '✅ 非該当',
    });

    // 洪水（flood / inland_flood / inland_flood_l2 / storm_surge いずれか）
    const floodVal = a
        ? (a.flood ?? a.inland_flood ?? a.inland_flood_l2 ?? a.storm_surge)
        : undefined;
    _lipSetHazard('lip-h-flood', floodVal, {
        insideLabel: '⚠️ 高リスク',
        outsideLabel: '✅ 域外',
    });

    // 土砂
    _lipSetHazard('lip-h-landslide', a ? a.landslide : undefined, {
        insideLabel: '⚠️ 警戒域',
        outsideLabel: '✅ 域外',
    });
}

function _lipSetHazard(id, value, { insideLabel, outsideLabel }) {
    const el = document.getElementById(id);
    if (!el) return;

    if (value === undefined || value === null) {
        el.textContent = '--';
        el.className = 'lip-row-value';
        return;
    }

    const inside = (typeof value === 'string' && value === 'inside') ||
                   (value && typeof value === 'object' && value.status === 'inside');
    const unknown = value === 'unknown' ||
                    (value && typeof value === 'object' && value.status === 'unknown');

    if (inside) {
        el.textContent = insideLabel;
        el.className = 'lip-row-value lip-hazard-danger';
    } else if (unknown) {
        el.textContent = '? 不明';
        el.className = 'lip-row-value lip-hazard-unknown';
    } else {
        el.textContent = outsideLabel;
        el.className = 'lip-row-value lip-hazard-safe';
    }
}

function _lipRenderShelter() {
    const el = document.getElementById('lip-nearest-shelter');
    if (!el) return;

    // destinations は state.js で宣言されたグローバル配列
    if (typeof destinations === 'undefined' || destinations.length === 0) {
        el.textContent = '未検索';
        return;
    }

    // 直線距離が最小のものを選ぶ
    const nearest = destinations.reduce((a, b) => {
        const da = (a.distance != null) ? a.distance : Infinity;
        const db = (b.distance != null) ? b.distance : Infinity;
        return da < db ? a : b;
    });

    if (!nearest) {
        el.textContent = '--';
        return;
    }

    const name = nearest.name || '候補';
    const dist = nearest.distance != null ? `${Math.round(nearest.distance)} m` : '- m';
    const dir  = (_lipLat != null && nearest.lat != null)
        ? _lipBearingLabel(_lipLat, _lipLon, nearest.lat, nearest.lon)
        : '';

    el.textContent = dir ? `${name}（${dist} ${dir}）` : `${name}（${dist}）`;
}

function _lipRenderAge() {
    const el = document.getElementById('lip-age');
    if (!el || _lipLastUpdateAt == null) return;
    const sec = Math.round((Date.now() - _lipLastUpdateAt) / 1000);
    el.textContent = sec < 5 ? 'たった今' : `${sec}秒前`;
}

// ── タイマー ───────────────────────────────────────────────────────

function _lipStartAgeTimer() {
    if (_lipAgeTimer) return;
    _lipAgeTimer = setInterval(_lipRenderAge, 5000);
}

function _lipStopAgeTimer() {
    if (_lipAgeTimer) {
        clearInterval(_lipAgeTimer);
        _lipAgeTimer = null;
    }
}

// ── ユーティリティ ────────────────────────────────────────────────

function _lipSet(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

/** 2点間の方位を8方位の日本語ラベルで返す。 */
function _lipBearingLabel(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180;
    const dLon  = (lon2 - lon1) * toRad;
    const lat1R = lat1 * toRad;
    const lat2R = lat2 * toRad;
    const y     = Math.sin(dLon) * Math.cos(lat2R);
    const x     = Math.cos(lat1R) * Math.sin(lat2R)
                - Math.sin(lat1R) * Math.cos(lat2R) * Math.cos(dLon);
    const deg   = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    const dirs  = ['北', '北東', '東', '南東', '南', '南西', '西', '北西'];
    return dirs[Math.round(deg / 45) % 8];
}
