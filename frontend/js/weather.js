'use strict';

/**
 * weather.js — 現在地気象情報の取得とパネル表示（Phase1.5 / Phase2A）
 *
 * 外部から呼ぶ:
 *   _weatherUpdate(lat, lon)  — 位置更新時に呼ぶ（fetchCurrentLocInfo からフック）
 *
 * キャッシュ: 60 秒間は同一座標のリクエストを再発行しない。
 *
 * 表示項目:
 *   雨量 / 風速 / 気温 / 観測点（距離km）/ 更新（HH:MM・X分前）
 *   警報・注意報（Phase2A）
 *   station_quality=far  → 「観測点が遠い」ノーティス
 *   freshness=stale      → 「観測データが古い」ノーティス
 */

const _WEATHER_CACHE_TTL_MS = 60_000;
let _weatherCache = null;  // { lat, lon, data, fetchedAt }

async function _weatherFetch(lat, lon) {
    const now = Date.now();
    if (
        _weatherCache &&
        Math.abs(_weatherCache.lat - lat) < 0.01 &&
        Math.abs(_weatherCache.lon - lon) < 0.01 &&
        now - _weatherCache.fetchedAt < _WEATHER_CACHE_TTL_MS
    ) {
        return _weatherCache.data;
    }

    const res = await fetch(`/api/weather/current?lat=${lat}&lon=${lon}`);
    if (!res.ok) return null;
    const data = await res.json();
    _weatherCache = { lat, lon, data, fetchedAt: now };
    return data;
}

function _weatherFmt(value, unit, decimals = 1) {
    if (value == null) return '--';
    return `${Number(value).toFixed(decimals)} ${unit}`;
}

function _weatherFmtStation(station, distance_km) {
    const name = station || '--';
    if (distance_km == null) return name;
    return `${name}（${distance_km}km）`;
}

function _weatherFmtTime(observed_at, age_minutes) {
    if (!observed_at) return '--';
    let timeStr = '--';
    try {
        const dt = new Date(observed_at);
        timeStr = dt.toLocaleTimeString('ja-JP', {
            hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo',
        });
    } catch (_) {}
    if (age_minutes == null) return timeStr;
    return `${timeStr}（${Math.round(age_minutes)}分前）`;
}

function _weatherRender(data) {
    const section = document.getElementById('lip-weather-section');
    if (!section) return;
    section.style.display = '';

    const set = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    };

    set('lip-weather-rain',    _weatherFmt(data.rain, 'mm/h'));
    set('lip-weather-wind',    _weatherFmt(data.wind, 'm/s'));
    set('lip-weather-temp',    _weatherFmt(data.temperature, '℃'));
    set('lip-weather-station', _weatherFmtStation(data.station, data.distance_km));
    set('lip-weather-time',    _weatherFmtTime(data.observed_at, data.age_minutes));

    _weatherRenderNotice(data);
}

function _weatherRenderNotice(data) {
    const el = document.getElementById('lip-weather-notice');
    if (!el) return;

    const notes = [];
    if (data.station_quality === 'far') {
        const km = data.distance_km != null ? `${data.distance_km}km` : '';
        notes.push(`⚠ 観測点が遠い${km ? `（${km}）` : ''}`);
    }
    if (data.freshness === 'stale') {
        const min = data.age_minutes != null ? `${Math.round(data.age_minutes)}分前` : '';
        notes.push(`⚠ 観測データが古い${min ? `（${min}）` : ''}`);
    }

    if (notes.length > 0) {
        el.textContent = notes.join('　');
        el.style.display = '';
    } else {
        el.textContent = '';
        el.style.display = 'none';
    }
}

function _weatherRenderError() {
    const section = document.getElementById('lip-weather-section');
    if (section) section.style.display = 'none';
}

// ── Phase2A: 警報・注意報 ───────────────────────────────────────────────────

const _WARNING_CACHE_TTL_MS = 120_000;  // 2 分
let _warningCache = null;  // { lat, lon, data, fetchedAt }

async function _warningFetch(lat, lon) {
    const now = Date.now();
    if (
        _warningCache &&
        Math.abs(_warningCache.lat - lat) < 0.05 &&
        Math.abs(_warningCache.lon - lon) < 0.05 &&
        now - _warningCache.fetchedAt < _WARNING_CACHE_TTL_MS
    ) {
        return _warningCache.data;
    }
    const res = await fetch(`/api/weather/warnings/current?lat=${lat}&lon=${lon}`);
    if (!res.ok) return null;
    const data = await res.json();
    _warningCache = { lat, lon, data, fetchedAt: now };
    return data;
}

function _warningLevelStyle(level) {
    if (level === '警報')  return 'color:#c62828;font-weight:700;';
    if (level === '注意報') return 'color:#e65100;font-weight:600;';
    return 'color:#2e7d32;';
}

function _warningRender(data) {
    const el = document.getElementById('lip-weather-warning');
    if (!el) return;

    if (!data || data.warnings == null) {
        el.textContent = '--';
        el.removeAttribute('style');
        return;
    }

    const active = data.warnings.filter(w => w.level === '警報' || w.level === '注意報');
    if (active.length === 0) {
        el.textContent = 'なし';
        el.style.cssText = _warningLevelStyle('なし');
        return;
    }

    const names = active.map(w => w.name).join('・');
    el.textContent = names;
    el.style.cssText = _warningLevelStyle(data.highest_level);
}

function _warningRenderError() {
    const el = document.getElementById('lip-weather-warning');
    if (el) {
        el.textContent = '取得不可';
        el.style.cssText = 'color:#94a3b8;';
    }
}

async function _weatherWarningUpdate(lat, lon) {
    try {
        const data = await _warningFetch(lat, lon);
        if (data) {
            _warningRender(data);
        } else {
            _warningRenderError();
        }
    } catch (err) {
        console.warn('[weather] warning fetch error:', err);
        _warningRenderError();
    }
}

// ── エントリーポイント ──────────────────────────────────────────────────────

/**
 * 位置更新時に外部から呼ぶエントリーポイント。
 */
async function _weatherUpdate(lat, lon) {
    try {
        const data = await _weatherFetch(lat, lon);
        if (data) {
            _weatherRender(data);
        } else {
            _weatherRenderError();
        }
    } catch (err) {
        console.warn('[weather] fetch error:', err);
        _weatherRenderError();
    }
    // 警報・注意報は独立して取得（失敗しても気象表示には影響しない）
    _weatherWarningUpdate(lat, lon);
}
