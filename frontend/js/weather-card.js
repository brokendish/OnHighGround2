'use strict';

/**
 * weather-card.js — 情報タブ「気象」カードの表示制御
 *
 * DOM:
 *   #lip-weather-card-section  — カード全体（lip-card-section）
 *   #lip-wc-status-badge       — severity バッジ
 *   #lip-wc-alert-list         — 警報・注意報リスト
 *   #lip-wc-precip-summary     — 降水予測（現在/予測を動的構築）
 *   #lip-wc-risk-msg           — 避難行動メッセージ
 *   #lip-wc-area-name          — 現在地エリア名
 *   #lip-wc-updated-at         — 更新時刻
 *   #lip-wc-message            — stale / 取得不可メッセージ
 *
 * 外部から呼ぶ:
 *   _weatherCardRender(alertsData, precipData, riskInfo)
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

const _WC_INTENSITY_LABEL = {
    none:     '降水なし',
    weak:     '弱い雨',
    moderate: '雨',
    strong:   '強い雨',
    severe:   '非常に激しい雨',
    unknown:  '不明',
};

// 避難判断に直結するメッセージ（リスクレベル別）
const _WC_RISK_MSG = {
    emergency: '命を守る行動を今すぐとってください',
    warning:   '状況を注視し、避難を検討してください',
    advisory:  '気象情報に注意し、行動計画を確認してください',
};

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
    if (precip) precip.innerHTML = '';
    const combined = _wcEl('lip-wc-combined-risk');
    if (combined) { combined.innerHTML = ''; combined.style.display = 'none'; }
    const riskMsg = _wcEl('lip-wc-risk-msg');
    if (riskMsg) { riskMsg.textContent = ''; riskMsg.style.display = 'none'; }
}

function _weatherCardSetNoLocation() {
    const msg = _wcEl('lip-wc-message');
    if (msg) msg.textContent = '現在地取得後に表示します';
    const badge = _wcEl('lip-wc-status-badge');
    if (badge) { badge.textContent = ''; badge.className = 'wc-status-badge'; }
    const list = _wcEl('lip-wc-alert-list');
    if (list) list.innerHTML = '';
    const combined = _wcEl('lip-wc-combined-risk');
    if (combined) { combined.innerHTML = ''; combined.style.display = 'none'; }
    const riskMsg = _wcEl('lip-wc-risk-msg');
    if (riskMsg) { riskMsg.textContent = ''; riskMsg.style.display = 'none'; }
}

// ── 降水予測セクション（現在/予測分離） ──────────────────────────────────────

function _wcRenderPrecip(precipData, precipInfo, precipUnknown) {
    const el = _wcEl('lip-wc-precip-summary');
    if (!el) return;
    el.innerHTML = '';

    if (!precipData || precipData.status === 'unavailable') {
        const d = document.createElement('div');
        d.className = 'wc-precip-current';
        d.textContent = 'ナウキャスト取得不可';
        el.appendChild(d);
        return;
    }

    // unknown = タイル取得できたが色マッチ失敗 → none と同一表示にしない
    if (precipUnknown) {
        const warnDiv = document.createElement('div');
        warnDiv.className = 'wc-precip-unknown';
        warnDiv.textContent = '降水予測を判定できません';
        el.appendChild(warnDiv);
        const current = (precipInfo || {}).current;
        if (current) {
            const curDiv = document.createElement('div');
            curDiv.className = 'wc-precip-current';
            curDiv.dataset.intensity = 'unknown';
            curDiv.textContent = `現在: ${current.label || '判定不能'}`;
            el.appendChild(curDiv);
        }
        return;
    }

    const current           = (precipInfo || {}).current;
    const forecastStrongest = (precipInfo || {}).forecastStrongest;
    const curIntensity      = current ? (current.intensity || 'unknown') : 'unknown';
    const curLabel          = current ? (current.label || _WC_INTENSITY_LABEL[curIntensity] || '不明') : '不明';

    // 現在の強度
    const curDiv = document.createElement('div');
    curDiv.className = 'wc-precip-current';
    curDiv.dataset.intensity = curIntensity;
    curDiv.textContent = `現在: ${curLabel}`;
    el.appendChild(curDiv);

    // 予測（強度が notable な場合のみ）
    const NOTABLE = new Set(['weak', 'moderate', 'strong', 'severe']);
    if (forecastStrongest && NOTABLE.has(forecastStrongest.intensity)) {
        const fDiv = document.createElement('div');
        fDiv.className = 'wc-precip-forecast';
        fDiv.dataset.intensity = forecastStrongest.intensity;
        const fLabel = _WC_INTENSITY_LABEL[forecastStrongest.intensity] || forecastStrongest.intensity;
        fDiv.textContent = `${forecastStrongest.minutes}分後: ${fLabel}`;
        el.appendChild(fDiv);
    }
}

// ── 複合リスク（気象 × ハザード）Phase2-C ────────────────────────────────────

function _wcRenderCombinedRisk(combined) {
    const el = _wcEl('lip-wc-combined-risk');
    if (!el) return;
    el.innerHTML = '';

    if (!Array.isArray(combined) || combined.length === 0) {
        el.style.display = 'none';
        return;
    }
    el.style.display = '';
    for (const item of combined) {
        const row = document.createElement('div');
        row.className = 'wc-combined-row wc-combined--' + (item.level || 'advisory');
        const headline = document.createElement('div');
        headline.className = 'wc-combined-headline';
        headline.textContent = item.headline || '';
        row.appendChild(headline);
        if (item.message) {
            const msg = document.createElement('div');
            msg.className = 'wc-combined-message';
            msg.textContent = item.message;
            row.appendChild(msg);
        }
        el.appendChild(row);
    }
}

// ── 避難行動メッセージ ───────────────────────────────────────────────────────

function _wcRenderRiskMsg(riskLevel) {
    const el = _wcEl('lip-wc-risk-msg');
    if (!el) return;
    const msg = _WC_RISK_MSG[riskLevel];
    if (msg) {
        el.textContent = msg;
        el.className = 'wc-risk-msg wc-risk-msg--' + riskLevel;
        el.style.display = '';
    } else {
        el.textContent = '';
        el.style.display = 'none';
    }
}

// ── メインレンダー ──────────────────────────────────────────────────────────

function _weatherCardRender(alertsData, precipData, riskInfo) {
    if (!alertsData) {
        _weatherCardSetLoading();
        return;
    }

    const status   = alertsData.status   || 'unavailable';
    const severity = alertsData.severity || 'none';
    const alerts   = alertsData.alerts   || [];
    const location = alertsData.location || {};
    const updatedAt = alertsData.updated_at || null;

    // Phase2-B/C: riskLevel はアラート・降水・複合リスクの統合
    const riskLevel     = (riskInfo || {}).riskLevel     || severity;
    const precipInfo    = (riskInfo || {}).precipInfo    || null;
    const precipUnknown = (riskInfo || {}).precipUnknown || false;
    const combined      = (riskInfo || {}).combined      || [];

    // エリア名
    const areaEl = _wcEl('lip-wc-area-name');
    if (areaEl) areaEl.textContent = location.area_name || '';

    // severity バッジ（表示はアラート severity のまま）
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

    // 降水予測（現在/予測分離）
    _wcRenderPrecip(precipData, precipInfo, precipUnknown);

    // 複合リスク（強雨 × ハザードゾーン）Phase2-C
    _wcRenderCombinedRisk(combined);

    // 避難行動メッセージ（riskLevel ベース）
    _wcRenderRiskMsg(riskLevel);

    // Phase 4-B: 状況理解カードへ降水情報を通知
    if (typeof situationCardOnWeatherUpdate === 'function') {
        situationCardOnWeatherUpdate(precipInfo || null);
    }

    // stale / unavailable メッセージ
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

    // カードヘッダーのクラスは riskLevel で決定（アコーディオン閉じていても視認）
    const header = _wcEl('lip-weather-card-header');
    if (header) {
        header.className = 'lip-accordion-header wc-header--' + riskLevel;
    }
}
