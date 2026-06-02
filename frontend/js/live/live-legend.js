'use strict';
// live-legend.js — キキクル・雨雲 凡例パネル
// liveMap に依存しない独立モジュール。

(function () {

    // ── 凡例データ ─────────────────────────────────────────────────────────────

    // キキクル（気象庁 危険度分布 公式カラー）
    const KIKI_ROWS = [
        { color: '#231815', label: '災害切迫', sub: '警戒レベル5相当' },
        { color: '#9B009B', label: '危険',     sub: '警戒レベル4相当' },
        { color: '#FF6400', label: '警戒',     sub: '警戒レベル3相当' },
        { color: '#FAF500', label: '注意',     sub: '警戒レベル2相当' },
        { color: '#E0E0DC', label: '今後の情報等に留意', sub: '', border: true },
    ];

    // 雨雲（気象庁 降水ナウキャスト 降水強度カラー）
    const RAIN_ROWS = [
        { color: '#C8EBFA', label: '0.5mm/h 未満',  sub: 'ごく弱い雨', border: true },
        { color: '#9ED3F0', label: '0.5〜1mm/h',    sub: '弱い雨' },
        { color: '#1464D2', label: '1〜10mm/h',     sub: 'やや強い雨' },
        { color: '#FAF500', label: '10〜20mm/h',    sub: '強い雨' },
        { color: '#F28C00', label: '20〜50mm/h',    sub: '激しい雨' },
        { color: '#E60000', label: '50〜80mm/h',    sub: '非常に激しい雨' },
        { color: '#9600C8', label: '80mm/h 以上',   sub: '猛烈な雨' },
    ];

    // ── DOM 生成 ──────────────────────────────────────────────────────────────

    function _row(r) {
        const border = r.border ? ' style="border:1px solid rgba(48,54,61,0.8)"' : '';
        return `<div class="llp-row">
            <span class="llp-swatch"${border} style="background:${r.color}"></span>
            <div class="llp-text">
                <div class="llp-label">${r.label}</div>
                ${r.sub ? `<div class="llp-sub">${r.sub}</div>` : ''}
            </div>
        </div>`;
    }

    function _buildPanel() {
        const el = document.createElement('div');
        el.id = 'live-legend-panel';
        el.setAttribute('hidden', '');
        el.innerHTML = `
            <div class="llp-header">
                <div class="llp-tabs">
                    <button class="llp-tab is-active" data-tab="kikikuru">キキクル</button>
                    <button class="llp-tab"            data-tab="rain">雨雲</button>
                </div>
                <button class="llp-close" aria-label="凡例を閉じる">×</button>
            </div>
            <div class="llp-body" data-body="kikikuru">
                ${KIKI_ROWS.map(_row).join('')}
                <div class="llp-note">出典: 気象庁 キキクル（危険度分布）</div>
            </div>
            <div class="llp-body" data-body="rain" hidden>
                ${RAIN_ROWS.map(_row).join('')}
                <div class="llp-note">出典: 気象庁 降水ナウキャスト</div>
            </div>`;
        document.body.appendChild(el);

        // タブ切替
        el.querySelectorAll('.llp-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                el.querySelectorAll('.llp-tab').forEach(b => b.classList.toggle('is-active', b === btn));
                el.querySelectorAll('.llp-body').forEach(b => b.hidden = (b.dataset.body !== tab));
            });
        });

        // 閉じる
        el.querySelector('.llp-close').addEventListener('click', _hide);

        // パネル外クリックで閉じる
        document.addEventListener('click', (e) => {
            if (!el.hidden && !el.contains(e.target) && !e.target.closest('#live-legend-toggle'))
                _hide();
        });

        return el;
    }

    let _panel = null;

    function _show() {
        if (!_panel) _panel = _buildPanel();
        _panel.removeAttribute('hidden');
    }
    function _hide() {
        if (_panel) _panel.setAttribute('hidden', '');
    }
    function _toggle() {
        if (!_panel || _panel.hasAttribute('hidden')) _show(); else _hide();
    }

    // ── 凡例ボタンをレイヤーパネル下部に追加 ─────────────────────────────────

    const layerPanel = document.getElementById('live-layer-panel');
    if (layerPanel) {
        const sep = document.createElement('hr');
        sep.className = 'live-panel-sep';

        const btn = document.createElement('button');
        btn.id        = 'live-legend-toggle';
        btn.className = 'live-legend-btn';
        btn.title     = '凡例を表示';
        btn.setAttribute('aria-label', '凡例');
        btn.innerHTML =
            '<svg viewBox="0 0 24 24" width="14" height="14" fill="none"' +
            ' stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
            '<rect x="3" y="3" width="18" height="18" rx="2"/>' +
            '<path d="M9 9h6M9 12h6M9 15h4"/>' +
            '</svg>' +
            '<span>凡例</span>';
        btn.addEventListener('click', (e) => { e.stopPropagation(); _toggle(); });

        layerPanel.appendChild(sep);
        layerPanel.appendChild(btn);
    }

})();
