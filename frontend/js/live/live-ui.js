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
        _bindToggle('toggle-tsunami',    () => {
            // tsunami は表示レイヤーなし（カードのみ）。チェックが OFF でもデータは取り続ける
        });
        _bindToggle('toggle-tide', (v) => liveTideLayer.setVisible(v));
    }

    // ── ステータスバー ───────────────────────────────────────────────────────

    const _statusBar = document.getElementById('live-status-bar');

    // null = unknown（未確認）、true = ok、false = offline
    const _currentStatus = {
        rainOk:     null,
        kikikuruOk: null,
        eqOk:       null,
        tsunamiOk:  null,
        tideOk:     null,
    };

    function _dot(ok) {
        if (ok === null || ok === undefined)
            return `<span class="live-status-dot unknown"></span>`;
        return `<span class="live-status-dot${ok ? '' : ' offline'}"></span>`;
    }

    function _renderStatus() {
        if (!_statusBar) return;
        _statusBar.innerHTML = `
            <span class="live-status-item">${_dot(_currentStatus.rainOk)} 雨雲</span>
            <span class="live-status-item">${_dot(_currentStatus.kikikuruOk)} キキクル</span>
            <span class="live-status-item">${_dot(_currentStatus.eqOk)} 地震</span>
            <span class="live-status-item">${_dot(_currentStatus.tsunamiOk)} 津波</span>
            <span class="live-status-item">${_dot(_currentStatus.tideOk)} 潮位</span>
        `;
    }

    function setStatus({ rainOk, eqOk, tsunamiOk }) {
        _currentStatus.rainOk    = rainOk;
        _currentStatus.eqOk      = eqOk;
        _currentStatus.tsunamiOk = tsunamiOk;
        _renderStatus();
    }

    function updateRainStatus(ok) {
        _currentStatus.rainOk = ok;
        _renderStatus();
    }

    function updateAlertStatus({ eqOk, tsunamiOk }) {
        _currentStatus.eqOk      = eqOk;
        _currentStatus.tsunamiOk = tsunamiOk;
        _renderStatus();
    }

    function updateKikikuruStatus(ok) {
        _currentStatus.kikikuruOk = ok;
        _renderStatus();
    }

    function updateTideStatus(ok) {
        _currentStatus.tideOk = ok;
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

    window.liveUI = {
        initToggles,
        setStatus,
        updateRainStatus,
        updateAlertStatus,
        updateKikikuruStatus,
        updateTideStatus,
        setUpdating,
        hideLoading,
    };

})();
