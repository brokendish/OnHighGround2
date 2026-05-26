'use strict';
// live-alert-panel.js — アクティブ警戒カード（左上）
// liveLayers に依存。navigation.js / state.js には依存しない。

(function () {

    const _card = document.getElementById('live-alert-card');

    // ── 津波 ────────────────────────────────────────────────────────────────

    const _TSUNAMI_PRIORITY = ['major_warning', 'warning', 'advisory'];

    const _TSUNAMI_LABEL = {
        major_warning: '大津波警報',
        warning:       '津波警報',
        advisory:      '津波注意報',
    };

    const _TSUNAMI_COLOR = {
        major_warning: '#da3633',
        warning:       '#ff6b35',
        advisory:      '#e3b341',
    };

    function _tsunamiSummary(data) {
        if (!data || !Array.isArray(data.areas) || !data.areas.length) {
            return null;
        }
        const levels = data.areas.map(a => a.level);
        const top = _TSUNAMI_PRIORITY.find(l => levels.includes(l));
        if (!top) return null;
        const areas = data.areas
            .filter(a => a.level === top)
            .map(a => a.name)
            .slice(0, 3);
        return { level: top, label: _TSUNAMI_LABEL[top], color: _TSUNAMI_COLOR[top], areas };
    }

    // ── 地震 ────────────────────────────────────────────────────────────────

    function _eqSummary(eqData) {
        const items = eqData || [];
        const count = items.length;
        const bigCount = items.filter(e => (e.magnitude || 0) >= 5.0).length;
        const recent = items[0];
        return { count, bigCount, recent };
    }

    // ── レンダリング ─────────────────────────────────────────────────────────

    function _render(tsunamiData, eqData) {
        const tsm = _tsunamiSummary(tsunamiData);
        const eq  = _eqSummary(eqData);

        let html = '<div class="lac-title">現在の状況</div>';

        // 津波
        if (tsm) {
            const areaText = tsm.areas.join(' / ');
            html += `
                <div class="lac-item lac-urgent" style="border-left-color:${tsm.color}">
                    <span class="lac-badge" style="background:${tsm.color};color:#fff">${tsm.label}</span>
                    <span class="lac-text">
                        <small>${areaText}</small>
                    </span>
                </div>`;
        } else {
            html += `
                <div class="lac-item" style="border-left-color:#3fb950">
                    <span class="lac-text">津波警報なし</span>
                </div>`;
        }

        // 地震
        if (eq.bigCount > 0) {
            const recentName = eq.recent ? eq.recent.epicenter_name || '' : '';
            html += `
                <div class="lac-item lac-warn" style="border-left-color:#ff6b35">
                    <span class="lac-badge" style="background:#ff6b35;color:#fff">M5以上 ${eq.bigCount}件</span>
                    <span class="lac-text"><small>${recentName}</small></span>
                </div>`;
        } else if (eq.count > 0) {
            html += `
                <div class="lac-item" style="border-left-color:#e3b341">
                    <span class="lac-text">地震 ${eq.count}件 (24h)</span>
                </div>`;
        } else {
            html += `
                <div class="lac-item" style="border-left-color:#3fb950">
                    <span class="lac-text">地震なし (24h)</span>
                </div>`;
        }

        const now = new Date().toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
        html += `<div class="lac-updated">更新 ${now}</div>`;

        _card.innerHTML = html;
    }

    // refresh 失敗時はキャッシュデータを使って描画する。
    // 戻り値 { tsunamiOk, eqOk } を live-main.js が status dot に使う。
    async function update() {
        const [tsunamiResult, eqResult] = await Promise.allSettled([
            liveLayers.tsunami.refresh(),
            liveLayers.earthquake.refresh(),
        ]);
        const tsunamiData = tsunamiResult.status === 'fulfilled'
            ? tsunamiResult.value
            : liveLayers.tsunami.getData();
        const eqData = eqResult.status === 'fulfilled'
            ? eqResult.value
            : liveLayers.earthquake.getData();
        _render(tsunamiData, eqData);
        return {
            tsunamiOk: tsunamiResult.status === 'fulfilled',
            eqOk:      eqResult.status === 'fulfilled',
        };
    }

    // 津波データのみ再取得してカードを更新（地震データは既取得分を流用）
    async function refreshTsunami() {
        let tsunamiData;
        try {
            tsunamiData = await liveLayers.tsunami.refresh();
        } catch (_) {
            tsunamiData = liveLayers.tsunami.getData();
        }
        _render(tsunamiData, liveLayers.earthquake.getData());
    }

    window.liveAlertPanel = { update, refreshTsunami };

})();
