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
 * リスクレベル（Phase2-B: 警報＋降水統合）:
 *   emergency: 暗赤・パルス強調
 *   warning:   赤バナー
 *   advisory:  黄バナー（小）
 *   none:      非表示
 *
 * 外部公開:
 *   _weatherAlertUiUpdate(alertsData, precipData, riskInfo)
 *   _weatherAlertUiClear()
 *
 * 抑制設計:
 *   - 雷注意報・乾燥注意報など避難に直結しない注意報のみかつ
 *     降水リスクもない場合は地図バナーを出さない（情報タブ止まり）
 *   - riskLevel=none の場合は必ずバナー非表示・残留なし
 *   - ダウングレード時は即時クリア（前回severity に引きずられない）
 */

const _WAU_BANNER_SEVERITIES = new Set(['emergency', 'warning', 'advisory']);

// 地図バナーを出す対象の警報種別キーワード（避難判断に関係するもの）
const _WAU_BANNER_KEYWORDS = new Set([
    '大雨', '洪水', '高潮', '暴風', '暴風雪', '竜巻',
    '土砂災害', '津波', '記録的短時間',
]);

// riskLevel に応じたバナー CSS クラス
const _WAU_CLASS = {
    emergency: 'wa-banner--emergency',
    warning:   'wa-banner--warning',
    advisory:  'wa-banner--advisory',
};

let _wauDismissed    = false;  // ユーザーが閉じた場合
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

function _wauIsHighPriorityKind(kind) {
    for (const kw of _WAU_BANNER_KEYWORDS) {
        if (kind.includes(kw)) return true;
    }
    return false;
}

/**
 * riskLevel・アラートリスト・降水データ・複合リスクからバナー文言を生成する。
 * combined が存在する場合は複合リスクの headline を優先して使用する。
 * null を返した場合はバナーを非表示にする。
 */
function _wauBannerText(riskLevel, alerts, precipData, hasBannerAlert, combined) {
    const precipSeverity = (precipData || {}).severity || 'none';
    // 最高レベルの複合リスクを使用
    const topCombined = Array.isArray(combined) && combined.length > 0 ? combined[0] : null;

    if (riskLevel === 'emergency') {
        if (topCombined && topCombined.level === 'emergency') {
            return `⚠ ${topCombined.headline} — 命を守る行動を確認してください`;
        }
        const kinds = alerts
            .filter(a => a.severity === 'emergency')
            .map(a => a.kind).join('・');
        return `⚠ ${kinds || '特別警報'} 発表中 — 命を守る行動を確認してください`;
    }

    if (riskLevel === 'warning') {
        if (topCombined) {
            return `⚠ ${topCombined.headline} — 避難を検討してください`;
        }
        if (hasBannerAlert) {
            const kinds = alerts
                .filter(a => a.severity === 'warning')
                .map(a => a.kind).slice(0, 2).join('・');
            return `⚠ ${kinds || '気象警報'} 発表中 — 避難を検討してください`;
        }
        if (precipSeverity === 'warning') {
            return '⚠ 30分以内に強雨域接近 — 安全な場所への移動を検討してください';
        }
        return null;
    }

    if (riskLevel === 'advisory') {
        if (topCombined) {
            return topCombined.headline;
        }
        if (hasBannerAlert) {
            const kinds = alerts
                .filter(a => a.severity === 'advisory' && _wauIsHighPriorityKind(a.kind))
                .map(a => a.kind).slice(0, 2).join('・');
            if (kinds) return `注意報: ${kinds}`;
        }
        if (precipSeverity === 'advisory') {
            return '現在地周辺で雨域を検出';
        }
        return null;
    }

    return null;
}

function _weatherAlertUiClear() {
    const banner = _wauBanner();
    if (banner) {
        banner.style.display = 'none';
        banner.className = 'weather-alert-banner';
        banner.innerHTML = '';
    }
    _wauLastSeverity = 'none';
    _wauDismissed    = false;
}

function _weatherAlertUiUpdate(alertsData, precipData, riskInfo) {
    const banner = _wauBanner();
    if (!banner) return;

    const alerts         = (alertsData || {}).alerts   || [];
    const riskLevel      = (riskInfo   || {}).riskLevel || (alertsData || {}).severity || 'none';
    const precipSeverity = (precipData || {}).severity  || 'none';
    const combined       = (riskInfo   || {}).combined  || [];

    // none → バナーを即時クリア（前回レベルに引きずられない・DOM残留なし）
    if (riskLevel === 'none' || !_WAU_BANNER_SEVERITIES.has(riskLevel)) {
        banner.style.display = 'none';
        banner.className = 'weather-alert-banner';
        banner.innerHTML = '';
        _wauLastSeverity = 'none';
        _wauDismissed = false;
        return;
    }

    // バナー表示条件: 警報キーワード該当アラート / 降水リスク / 複合リスク
    const hasBannerAlert   = _wauHasBannerAlert(alerts);
    const hasNotablePrecip = precipSeverity === 'warning' || precipSeverity === 'advisory';
    const hasCombinedRisk  = combined.length > 0;
    if (!hasBannerAlert && !hasNotablePrecip && !hasCombinedRisk) {
        banner.style.display = 'none';
        banner.className = 'weather-alert-banner';
        banner.innerHTML = '';
        _wauLastSeverity = riskLevel;
        return;
    }

    // リスクレベルが変化した場合は dismissed をリセット（ダウングレードも含む）
    if (riskLevel !== _wauLastSeverity) {
        _wauDismissed = false;
    }
    _wauLastSeverity = riskLevel;

    if (_wauDismissed && riskLevel !== 'emergency') {
        return;
    }

    const text = _wauBannerText(riskLevel, alerts, precipData, hasBannerAlert, combined);
    if (!text) {
        banner.style.display = 'none';
        banner.innerHTML = '';
        return;
    }

    banner.className = 'weather-alert-banner ' + (_WAU_CLASS[riskLevel] || '');
    banner.innerHTML = '';

    const msgEl = document.createElement('span');
    msgEl.className = 'wa-banner-text';
    msgEl.textContent = text;
    banner.appendChild(msgEl);

    // emergency 以外は閉じるボタンを付ける
    if (riskLevel !== 'emergency') {
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
    if (typeof _weatherServiceSetCallback === 'function') {
        _weatherServiceSetCallback(function(alerts, precip, riskInfo) {
            _weatherAlertUiUpdate(alerts, precip, riskInfo);
            if (typeof _weatherCardRender === 'function') {
                _weatherCardRender(alerts, precip, riskInfo);
            }
        });
    }
}
