'use strict';

/**
 * weather-alert-ui.js — 気象警報・注意報の地図本体バナー表示
 *
 * tsunami-warning.js のバナーパターンを参考に実装。
 * 既存の津波バナー・ナビUI・雨雲レイヤーには干渉しない。
 *
 * DOM:
 *   #weather-alert-banner — 地図最上部のバナー（tsunami-warning-banner の下）
 *
 * 表示優先度:
 *   emergency: 赤背景・強強調
 *   warning:   赤バナー
 *   advisory:  オレンジ小バナー
 *   none:      非表示
 *
 * 外部公開:
 *   _weatherAlertUiUpdate(alertsData, precipData)
 *   _weatherAlertUiClear()
 *
 * 抑制設計:
 *   - 雷注意報・乾燥注意報など避難に直結しない注意報のみの場合、
 *     地図バナーは出さず情報タブ止まりにする
 *   - severity=none の場合は必ずバナー非表示
 */

// 地図バナーを出す対象の severity
const _WAU_BANNER_SEVERITIES = new Set(['emergency', 'warning', 'advisory']);

// 地図バナーを出す対象の警報種別キーワード（避難判断に関係するもの）
const _WAU_BANNER_KEYWORDS = new Set([
    '大雨', '洪水', '高潮', '暴風', '暴風雪', '竜巻',
    '土砂災害', '津波', '記録的短時間',
]);

// severity に応じたバナー CSS クラス
const _WAU_CLASS = {
    emergency: 'wa-banner--emergency',
    warning:   'wa-banner--warning',
    advisory:  'wa-banner--advisory',
};

let _wauDismissed = false;  // ユーザーが閉じた場合
let _wauLastSeverity = 'none';

function _wauBanner() {
    return document.getElementById('weather-alert-banner');
}

function _wauHasBannerAlert(alerts) {
    if (!Array.isArray(alerts) || alerts.length === 0) return false;
    for (const a of alerts) {
        const kind = a.kind || '';
        const sev  = a.severity || 'none';
        if (sev === 'emergency' || sev === 'warning') return true;
        if (sev === 'advisory') {
            for (const kw of _WAU_BANNER_KEYWORDS) {
                if (kind.includes(kw)) return true;
            }
        }
    }
    return false;
}

function _wauBannerText(severity, alerts) {
    if (severity === 'emergency') {
        const kinds = alerts
            .filter(a => a.severity === 'emergency')
            .map(a => a.kind).join('・');
        return `⚠ ${kinds || '特別警報'} 発表中 — 命を守る行動を確認してください`;
    }
    if (severity === 'warning') {
        const kinds = alerts
            .filter(a => a.severity === 'warning')
            .map(a => a.kind).slice(0, 2).join('・');
        return `⚠ ${kinds || '気象警報'} 発表中 — 現在地周辺で気象リスクがあります`;
    }
    if (severity === 'advisory') {
        const kinds = alerts
            .filter(a => a.severity === 'advisory' && _wauIsHighPriorityKind(a.kind))
            .map(a => a.kind).slice(0, 2).join('・');
        if (!kinds) return null;
        return `注意報: ${kinds}`;
    }
    return null;
}

function _wauIsHighPriorityKind(kind) {
    for (const kw of _WAU_BANNER_KEYWORDS) {
        if (kind.includes(kw)) return true;
    }
    return false;
}

function _weatherAlertUiClear() {
    const banner = _wauBanner();
    if (banner) {
        banner.style.display = 'none';
        banner.className = 'weather-alert-banner';
        banner.innerHTML = '';
    }
    _wauLastSeverity = 'none';
}

function _weatherAlertUiUpdate(alertsData, _precipData) {
    const banner = _wauBanner();
    if (!banner) return;

    const status   = (alertsData || {}).status   || 'unavailable';
    const severity = (alertsData || {}).severity || 'none';
    const alerts   = (alertsData || {}).alerts   || [];

    // unavailable / none は必ずバナーを消す（前回 severity に引きずられない）
    if (status === 'unavailable' || severity === 'none') {
        banner.style.display = 'none';
        banner.className = 'weather-alert-banner';
        _wauLastSeverity = 'none';
        _wauDismissed = false;
        return;
    }

    // 気象バナー対象外 severity
    if (!_WAU_BANNER_SEVERITIES.has(severity)) {
        banner.style.display = 'none';
        banner.className = 'weather-alert-banner';
        _wauLastSeverity = 'none';
        _wauDismissed = false;
        return;
    }

    // 地図バナー対象の警報があるか確認
    if (!_wauHasBannerAlert(alerts)) {
        banner.style.display = 'none';
        banner.className = 'weather-alert-banner';
        _wauLastSeverity = severity;
        return;
    }

    // severity が下がったらdismissedをリセット
    if (severity !== _wauLastSeverity) {
        _wauDismissed = false;
    }
    _wauLastSeverity = severity;

    if (_wauDismissed && severity !== 'emergency') {
        return;
    }

    const text = _wauBannerText(severity, alerts);
    if (!text) {
        banner.style.display = 'none';
        return;
    }

    banner.className = 'weather-alert-banner ' + (_WAU_CLASS[severity] || '');
    banner.innerHTML = '';

    const msgEl = document.createElement('span');
    msgEl.className = 'wa-banner-text';
    msgEl.textContent = text;
    banner.appendChild(msgEl);

    // emergency 以外は閉じるボタンを付ける
    if (severity !== 'emergency') {
        const closeBtn = document.createElement('button');
        closeBtn.className = 'wa-banner-close';
        closeBtn.textContent = '×';
        closeBtn.setAttribute('aria-label', '閉じる');
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            _wauDismissed = true;
            banner.style.display = 'none';
        });
        banner.appendChild(closeBtn);
    }

    banner.style.display = 'flex';
}

function _weatherAlertUiInit() {
    // weather-service.js のコールバックに登録
    if (typeof _weatherServiceSetCallback === 'function') {
        _weatherServiceSetCallback(function(alerts, precip) {
            _weatherAlertUiUpdate(alerts, precip);
            if (typeof _weatherCardRender === 'function') {
                _weatherCardRender(alerts, precip);
            }
        });
    }
}
