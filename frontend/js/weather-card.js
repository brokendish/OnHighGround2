'use strict';

/**
 * weather-card.js — 情報タブ「気象」カードの表示制御
 *
 * DOM:
 *   #lip-weather-card-section  — カード全体（lip-card-section）
 *   #lip-wc-status-badge       — severity バッジ
 *   #lip-wc-alert-list         — 警報・注意報リスト
 *   #lip-wc-precip-summary     — 降水予測サマリー
 *   #lip-wc-area-name          — 現在地エリア名
 *   #lip-wc-updated-at         — 更新時刻
 *   #lip-wc-message            — 平常時 / 取得不可メッセージ
 *
 * 外部から呼ぶ:
 *   _weatherCardRender(alertsData, precipData)
 *   _weatherCardSetLoading()
 *   _weatherCardSetNoLocation()
 */

const _WC_SEVERITY_LABELS = {
    emergency: '特別警報',
    warning:   '警報',
    advisory:  '注意報',
    unknown:   '情報',
    none:      '',
};

const _WC_SEVERITY_CLASS = {
    emergency: 'wc-badge--emergency',
    warning:   'wc-badge--warning',
    advisory:  'wc-badge--advisory',
    unknown:   'wc-badge--unknown',
    none:      'wc-badge--none',
};

// 優先度が高い警報種別（地図バナー連動対象）
const _WC_HIGH_PRIORITY = new Set([
    '大雨', '洪水', '高潮', '暴風', '暴風雪', '竜巻', '土砂災害', '津波',
]);

function _wcEl(id) { return document.getElementById(id); }

function _wcIsHighPriority(kind) {
    for (const kw of _WC_HIGH_PRIORITY) {
        if (kind.includes(kw)) return true;
    }
    return false;
}

function _wcFmtTime(isoStr) {
    if (!isoStr) return '';
    try {
        const dt = new Date(isoStr);
        return dt.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
    } catch (_) { return ''; }
}

function _weatherCardSetLoading() {
    const msg = _wcEl('lip-wc-message');
    if (msg) msg.textContent = '気象情報を取得中...';
    const badge = _wcEl('lip-wc-status-badge');
    if (badge) { badge.textContent = ''; badge.className = 'wc-status-badge'; }
    const list = _wcEl('lip-wc-alert-list');
    if (list) list.innerHTML = '';
    const precip = _wcEl('lip-wc-precip-summary');
    if (precip) precip.textContent = '';
}

function _weatherCardSetNoLocation() {
    const msg = _wcEl('lip-wc-message');
    if (msg) msg.textContent = '現在地取得後に表示します';
    const badge = _wcEl('lip-wc-status-badge');
    if (badge) { badge.textContent = ''; badge.className = 'wc-status-badge'; }
    const list = _wcEl('lip-wc-alert-list');
    if (list) list.innerHTML = '';
}

function _weatherCardRender(alertsData, precipData) {
    if (!alertsData) {
        _weatherCardSetLoading();
        return;
    }

    const status   = alertsData.status   || 'unavailable';
    const severity = alertsData.severity || 'none';
    const alerts   = alertsData.alerts   || [];
    const location = alertsData.location || {};
    const updatedAt = alertsData.updated_at || null;

    // エリア名
    const areaEl = _wcEl('lip-wc-area-name');
    if (areaEl) areaEl.textContent = location.area_name || '';

    // severity バッジ
    const badge = _wcEl('lip-wc-status-badge');
    if (badge) {
        const label = _WC_SEVERITY_LABELS[severity] || '';
        badge.textContent = label;
        badge.className = 'wc-status-badge ' + (_WC_SEVERITY_CLASS[severity] || '');
        badge.style.display = label ? '' : 'none';
    }

    // 警報・注意報リスト
    const list = _wcEl('lip-wc-alert-list');
    if (list) {
        list.innerHTML = '';
        if (alerts.length === 0) {
            const row = document.createElement('div');
            row.className = 'wc-alert-none';
            row.textContent = '警報・注意報なし';
            list.appendChild(row);
        } else {
            for (const a of alerts) {
                const row = document.createElement('div');
                row.className = 'wc-alert-row wc-alert--' + (a.severity || 'unknown');
                if (_wcIsHighPriority(a.kind || '')) row.classList.add('wc-alert--high-priority');
                const kindEl = document.createElement('span');
                kindEl.className = 'wc-alert-kind';
                kindEl.textContent = a.kind || '';
                const statusEl = document.createElement('span');
                statusEl.className = 'wc-alert-status';
                statusEl.textContent = a.status || '';
                row.appendChild(kindEl);
                row.appendChild(statusEl);
                list.appendChild(row);
            }
        }
    }

    // 降水予測サマリー
    const precipEl = _wcEl('lip-wc-precip-summary');
    if (precipEl) {
        if (precipData && precipData.summary) {
            precipEl.textContent = precipData.summary;
        } else {
            precipEl.textContent = '降水ナウキャスト: レーダー参照';
        }
    }

    // メッセージ（stale / unavailable）
    const msg = _wcEl('lip-wc-message');
    if (msg) {
        if (status === 'unavailable') {
            msg.textContent = '気象情報を取得できません';
            msg.style.display = '';
        } else if (status === 'stale') {
            msg.textContent = '⚠ 前回取得データを表示中';
            msg.style.display = '';
        } else {
            msg.textContent = '';
            msg.style.display = 'none';
        }
    }

    // 更新時刻
    const updEl = _wcEl('lip-wc-updated-at');
    if (updEl) {
        const t = _wcFmtTime(updatedAt);
        updEl.textContent = t ? `更新 ${t}` : '';
    }

    // カードヘッダーの severity クラスを付与（アコーディオン閉じていても視認できるように）
    const header = _wcEl('lip-weather-card-header');
    if (header) {
        header.className = 'lip-accordion-header wc-header--' + severity;
    }
}
