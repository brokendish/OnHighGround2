'use strict';

/**
 * tsunami-warning.js — 津波警報・注意報バナー表示
 *
 * 外部公開:
 *   _tsunamiWarningInit()   — 起動時に一度呼ぶ（60秒ポーリング開始）
 *   _tsunamiWarningUpdate() — 任意のタイミングで即時更新する場合
 *
 * UI:
 *   #tsunami-warning-banner — 地図最上部の全幅バナー
 *   大津波警報: --tw-danger（赤）
 *   津波警報:   --tw-danger（赤）
 *   津波注意報: --tw-advisory（橙）
 *   status=none:       バナー非表示
 *   status=stale:      警告UIに古い情報の注記を付けて表示
 *   status=error:      エラー時は既存機能を止めず静かに失敗
 *
 * 津波浸水想定レイヤー:
 *   警報・注意報が active の場合、showTsunamiHazard* チェックボックスを
 *   自動 ON にする。
 */

const _TW_POLL_MS = 60_000;

let _twTimer = null;
let _twLastStatus = null;
let _twLastNavAlertAt = 0;

function _twBanner() {
    return document.getElementById('tsunami-warning-banner');
}

function _twLevelPriority(level) {
    return { major_warning: 4, warning: 3, advisory: 2, forecast: 1 }[level] ?? 0;
}

function _twMaxLevel(areas) {
    let max = null;
    for (const a of areas) {
        if (_twLevelPriority(a.level) > _twLevelPriority(max)) max = a.level;
    }
    return max;
}

function _twApplyBanner(data) {
    const banner = _twBanner();
    if (!banner) return;

    const status = data.status;

    if (status === 'none' || status === 'error') {
        banner.style.display = 'none';
        banner.className = 'tsunami-warning-banner';
        return;
    }

    const maxLevel = _twMaxLevel(data.areas || []);
    if (!maxLevel) {
        banner.style.display = 'none';
        return;
    }

    // クラス付与
    banner.className = 'tsunami-warning-banner';
    if (maxLevel === 'major_warning' || maxLevel === 'warning') {
        banner.classList.add('tw-danger');
    } else if (maxLevel === 'advisory') {
        banner.classList.add('tw-advisory');
    } else {
        banner.classList.add('tw-forecast');
    }

    // エリア一覧テキスト（最大5件）
    const areaNames = (data.areas || []).map(a => a.name).filter(Boolean);
    const areaText = areaNames.length > 0
        ? areaNames.slice(0, 5).join('・') + (areaNames.length > 5 ? `他${areaNames.length - 5}区域` : '')
        : '';

    // stale 表示
    const staleNote = status === 'stale'
        ? '<span class="tw-stale-note">（情報が古い可能性があります）</span>'
        : '';

    // メッセージ
    const msg = data.message || '';

    banner.innerHTML =
        `<span class="tw-icon">&#9888;</span>` +
        `<span class="tw-msg">${_twEscape(msg)}</span>` +
        (areaText ? `<span class="tw-areas">${_twEscape(areaText)}</span>` : '') +
        staleNote;

    banner.style.display = 'flex';
}

function _twMaybeShowNavWarning(data) {
    if (typeof navigationMode === 'undefined' || typeof _showNavBanner !== 'function') return;
    if (navigationMode !== 'navigation_active' && navigationMode !== 'navigation_warning') return;

    const maxLevel = _twMaxLevel(data.areas || []);
    if (maxLevel !== 'major_warning' && maxLevel !== 'warning') return;

    const now = Date.now();
    if (now - _twLastNavAlertAt < _TW_POLL_MS - 1000) return;

    const message = maxLevel === 'major_warning'
        ? '大津波警報発表中。海岸・河口付近を避け、高台への避難を続けてください。'
        : '津波警報発表中。海岸・河口付近を避けて避難してください。';
    _twLastNavAlertAt = now;
    _showNavBanner(message, 'danger', 8000);
}

function _twEscape(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function _twAutoEnableTsunamiLayers(active) {
    if (!active) return;
    const ids = [
        'showTsunamiHazardTokyo',
        'showTsunamiHazardKanagawa',
        'showTsunamiHazardChiba',
    ];
    for (const id of ids) {
        const cb = document.getElementById(id);
        if (cb && !cb.checked && !cb.disabled) {
            cb.checked = true;
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
}

async function _tsunamiWarningUpdate() {
    try {
        const res = await fetch('/api/tsunami/warnings/current');
        if (!res.ok) return;
        const data = await res.json();

        const prevStatus = _twLastStatus;
        _twLastStatus = data.status;

        _twApplyBanner(data);

        // 新規 active になったときだけ津波レイヤーを自動 ON
        if (data.status === 'active' && prevStatus !== 'active') {
            _twAutoEnableTsunamiLayers(true);
        }
        if (data.status === 'active') {
            _twMaybeShowNavWarning(data);
        }
    } catch (_) {
        // ネットワークエラー時は静かに失敗（既存機能を止めない）
    }
}

function _tsunamiWarningInit() {
    _tsunamiWarningUpdate();
    _twTimer = setInterval(_tsunamiWarningUpdate, _TW_POLL_MS);
}
