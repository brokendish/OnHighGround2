'use strict';
// live-sun-moon-card.js — /live 専用 日月情報カード
// navigation.js / state.js に一切依存しない。
// 東京固定の日の出・日の入り・月の出・月の入り・月齢を表示する。

(function () {

    function _row(label, value) {
        const v = value != null ? value : '--';
        return `<div class="live-sm-row"><span class="live-sm-label">${label}</span><span class="live-sm-value">${v}</span></div>`;
    }

    function _render(d) {
        const body = document.getElementById('live-sun-moon-body');
        if (!body) return;

        const phaseVal = d.moon_phase != null ? String(d.moon_phase) : '--';
        const phaseName = d.moon_phase_name ? `<small class="live-sm-phase">${d.moon_phase_name}</small>` : '';

        body.className = '';
        body.innerHTML =
            _row('日の出', d.sunrise) +
            _row('日の入り', d.sunset) +
            '<div class="live-sm-spacer"></div>' +
            _row('月の出', d.moonrise) +
            _row('月の入り', d.moonset) +
            '<div class="live-sm-spacer"></div>' +
            `<div class="live-sm-row"><span class="live-sm-label">月齢</span>` +
            `<span class="live-sm-value">${phaseVal}${phaseName}</span></div>`;
    }

    function _renderError() {
        const body = document.getElementById('live-sun-moon-body');
        if (!body) return;
        body.className = 'live-sm-error';
        body.textContent = '取得できません';
    }

    async function refresh() {
        try {
            const res = await fetch('/api/live/sun-moon');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();
            if (!d.sunrise && !d.sunset) throw new Error('empty response');
            _render(d);
            console.info('live sun moon loaded');
        } catch (err) {
            console.warn('live sun moon load failed:', err.message);
            _renderError();
        }
    }

    refresh();

    window.liveSunMoonCard = { refresh };

})();
