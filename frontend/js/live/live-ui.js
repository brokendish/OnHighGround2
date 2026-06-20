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

    function _kikikuruParentToggle(visible) {
        const sub = document.getElementById('kikikuru-sub');
        if (sub) sub.classList.toggle('hidden', !visible);
        liveLayers.kikikuru.setVisible(visible);
    }

    function initToggles() {
        _bindToggle('toggle-rain',           (v) => liveLayers.rain.setVisible(v));
        _bindToggle('toggle-kikikuru',       _kikikuruParentToggle);
        _bindToggle('toggle-kikikuru-land',  (v) => liveLayers.kikikuru.setKindVisible('land',  v));
        _bindToggle('toggle-kikikuru-inund', (v) => liveLayers.kikikuru.setKindVisible('inund', v));
        _bindToggle('toggle-kikikuru-flood', (v) => liveLayers.kikikuru.setKindVisible('flood', v));
        _bindToggle('toggle-earthquake',     (v) => liveLayers.earthquake.setVisible(v));
        _bindToggle('toggle-tsunami',        (v) => liveLayers.tsunami.setVisible(v));
        _bindToggle('toggle-storm-surge',    (v) => liveLayers.stormSurge.setVisible(v));
        _bindToggle('toggle-tide',           (v) => liveTideLayer.setVisible(v));
        _bindToggle('toggle-train',          (v) => {
            liveLayers.train.setVisible(v);
            const hint = document.getElementById('train-layer-hint');
            if (hint) hint.classList.toggle('visible', v);
        });
        _bindToggle('toggle-road-traffic',   (v) => {
            liveLayers.roadTraffic.setVisible(v);
        });
    }

    // ── ステータスバー ───────────────────────────────────────────────────────

    const _statusBar = document.getElementById('live-status-bar');

    // null = unknown（未確認）、true = ok、false = offline
    const _currentStatus = {
        rainOk:         null,
        kikikuruOk:     null,
        eqOk:           null,
        tsunamiOk:      null,
        stormSurgeOk:   null,
        tideOk:         null,
        trainOk:        null,
        roadTrafficOk:  null,
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
            <span class="live-status-item">${_dot(_currentStatus.stormSurgeOk)} 高潮</span>
            <span class="live-status-item">${_dot(_currentStatus.tideOk)} 潮位</span>
            <span class="live-status-item">${_dot(_currentStatus.trainOk)} 鉄道</span>
            <span class="live-status-item">${_dot(_currentStatus.roadTrafficOk)} 道路</span>
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

    function updateStormSurgeStatus(ok) {
        _currentStatus.stormSurgeOk = ok;
        _renderStatus();
    }

    function updateTideStatus(ok) {
        _currentStatus.tideOk = ok;
        _renderStatus();
    }

    function updateTrainStatus(ok) {
        _currentStatus.trainOk = ok;
        _renderStatus();
    }

    function updateRoadTrafficStatus(ok) {
        _currentStatus.roadTrafficOk = ok;
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
        updateStormSurgeStatus,
        updateTideStatus,
        updateTrainStatus,
        updateRoadTrafficStatus,
        setUpdating,
        hideLoading,
    };

})();
