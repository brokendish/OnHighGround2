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
 *   status=active: 警報・注意報バナー表示
 *   status=none/cleared/stale/unavailable/error: バナー非表示
 *
 * 津波浸水想定レイヤー:
 *   警報・注意報が active の場合、showTsunamiHazard* チェックボックスを
 *   自動 ON にする。
 */

const _TW_POLL_MS = 60_000;

let _twTimer = null;
let _twLastStatus = null;
let _twLastNavAlertAt = 0;

// 警報種別ラベル
const _TW_TITLE = {
    major_warning: '大津波警報',
    warning:       '津波警報',
    advisory:      '津波注意報',
    forecast:      '津波予報',
};

// 警報種別アクションメッセージ
const _TW_ACTION = {
    major_warning: 'ただちに高台や津波避難ビルへ避難してください',
    warning:       'ただちに海岸・河口付近から離れ、高い場所へ避難してください',
    advisory:      '海岸・河口付近から離れてください',
    forecast:      '最新の津波情報に注意してください',
};

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

    // active のときのみバナーを表示する（stale 含むそれ以外は非表示）
    if (status !== 'active') {
        banner.style.display = 'none';
        banner.className = 'tsunami-warning-banner';
        banner.innerHTML = '';
        return;
    }

    const maxLevel = _twMaxLevel(data.areas || []);
    if (!maxLevel) {
        banner.style.display = 'none';
        banner.innerHTML = '';
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

    // エリア一覧テキスト（最大3件、日本語読点区切り）
    const areaNames = (data.areas || []).map(a => a.name).filter(Boolean);
    const _MAX_AREAS = 3;
    const areaText = areaNames.length > 0
        ? areaNames.slice(0, _MAX_AREAS).join('、') +
          (areaNames.length > _MAX_AREAS ? ' ほか' : '')
        : '';

    const title  = _TW_TITLE[maxLevel]  || '';
    const action = _TW_ACTION[maxLevel] || (data.message || '');

    banner.innerHTML =
        `<span class="tw-icon">&#9888;</span>` +
        `<div class="tw-content">` +
        `<div class="tw-title">${_twEscape(title)}</div>` +
        `<div class="tw-msg">${_twEscape(action)}</div>` +
        (areaText ? `<div class="tw-areas">対象：${_twEscape(areaText)}</div>` : '') +
        `</div>`;

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
        if (!res.ok) {
            // HTTP エラー時: 古い警告を出し続けないためバナーを非表示にする
            _twApplyBanner({ status: 'unavailable', areas: [] });
            return;
        }
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
        // ネットワークエラー時: 古い警告を出し続けないためバナーを非表示にする
        _twApplyBanner({ status: 'unavailable', areas: [] });
    }
}

function _tsunamiWarningInit() {
    _tsunamiWarningUpdate();
    _twTimer = setInterval(_tsunamiWarningUpdate, _TW_POLL_MS);
}
