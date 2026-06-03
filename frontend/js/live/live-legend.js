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

    // 高潮警報対象の沿岸部（行政区域単位の概略エリア）
    const STORM_SURGE_ROWS = [
        { lineColor: '#ef4444', label: '高潮警報対象の沿岸部', sub: '警報発令区域（概略）' },
        { lineColor: '#f97316', label: '高潮注意報対象の沿岸部', sub: '注意報発令区域（概略）' },
    ];

    // ── DOM 生成 ──────────────────────────────────────────────────────────────

    function _row(r) {
        let swatch;
        if (r.lineColor) {
            // 折れ線スウォッチ（沿岸部ハイライト用）
            swatch = `<svg class="llp-swatch-line" width="24" height="14" aria-hidden="true">` +
                `<line x1="2" y1="7" x2="22" y2="7" stroke="${r.lineColor}" stroke-width="3" stroke-dasharray="6 3"/>` +
                `</svg>`;
        } else {
            const border = r.border ? ' style="border:1px solid rgba(48,54,61,0.8)"' : '';
            swatch = `<span class="llp-swatch"${border} style="background:${r.color}"></span>`;
        }
        return `<div class="llp-row">
            ${swatch}
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
                    <button class="llp-tab"            data-tab="storm-surge">高潮</button>
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
            </div>
            <div class="llp-body" data-body="storm-surge" hidden>
                ${STORM_SURGE_ROWS.map(_row).join('')}
                <div class="llp-note">行政区域単位の警報発令エリアです。<br>高潮浸水範囲とは異なります。</div>
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

        const riverLink = document.createElement('a');
        riverLink.href      = 'https://www.river.go.jp/index';
        riverLink.target    = '_blank';
        riverLink.rel       = 'noopener noreferrer';
        riverLink.className = 'live-legend-btn';
        riverLink.title     = '国土交通省 河川情報（外部サイト）';
        riverLink.innerHTML =
            '<svg viewBox="0 0 24 24" width="14" height="14" fill="none"' +
            ' stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
            '<path d="M3 17 Q6 12 9 17 Q12 22 15 17 Q18 12 21 17"/>' +
            '<path d="M3 10 Q6 5 9 10 Q12 15 15 10 Q18 5 21 10"/>' +
            '</svg>' +
            '<span>国土交通省 河川情報</span>';
        layerPanel.appendChild(riverLink);
    }

})();
