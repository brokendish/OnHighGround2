'use strict';
// live-ui.js — レイヤー切替 UI / ステータスバー
// liveLayers に依存。navigation.js / state.js には依存しない。

(function () {

    // ── レイヤー切替チェックボックス ────────────────────────────────────────

    function _bindToggle(id, handler) {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('change', () => handler(el.checked));
    }

    function initToggles() {
        _bindToggle('toggle-rain',       (v) => liveLayers.rain.setVisible(v));
        _bindToggle('toggle-kikikuru',   (v) => liveLayers.kikikuru.setVisible(v));
        _bindToggle('toggle-earthquake', (v) => liveLayers.earthquake.setVisible(v));
        _bindToggle('toggle-tsunami',    (v) => {
            // tsunami は表示レイヤーなし（カードのみ）。チェックが OFF でもデータは取り続ける
        });
    }

    // ── ステータスバー ───────────────────────────────────────────────────────

    const _statusBar = document.getElementById('live-status-bar');

    // 現在の各 API 状態を保持する（定期更新で部分的に書き換えるため）
    const _currentStatus = { rainOk: false, eqOk: false, tsunamiOk: false };

    function _dot(online) {
        return `<span class="live-status-dot${online ? '' : ' offline'}"></span>`;
    }

    function _renderStatus() {
        if (!_statusBar) return;
        _statusBar.innerHTML = `
            <span class="live-status-item">${_dot(_currentStatus.rainOk)} 雨雲</span>
            <span class="live-status-item">${_dot(_currentStatus.eqOk)} 地震</span>
            <span class="live-status-item">${_dot(_currentStatus.tsunamiOk)} 津波</span>
        `;
    }

    function setStatus({ rainOk, eqOk, tsunamiOk }) {
        _currentStatus.rainOk    = rainOk;
        _currentStatus.eqOk      = eqOk;
        _currentStatus.tsunamiOk = tsunamiOk;
        _renderStatus();
    }

    // 定期更新時に雨雲だけを更新する
    function updateRainStatus(ok) {
        _currentStatus.rainOk = ok;
        _renderStatus();
    }

    // 定期更新時に地震・津波だけを更新する
    function updateAlertStatus({ eqOk, tsunamiOk }) {
        _currentStatus.eqOk      = eqOk;
        _currentStatus.tsunamiOk = tsunamiOk;
        _renderStatus();
    }

    function setUpdating() {
        if (!_statusBar) return;
        const dot = `<span class="live-status-dot updating"></span>`;
        _statusBar.innerHTML = `<span class="live-status-item">${dot} 更新中...</span>`;
    }

    // ── ローディングオーバーレイ ─────────────────────────────────────────────

    function hideLoading() {
        const el = document.getElementById('live-loading');
        if (el) el.classList.add('hidden');
    }

    window.liveUI = { initToggles, setStatus, updateRainStatus, updateAlertStatus, setUpdating, hideLoading };

})();
