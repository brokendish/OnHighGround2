'use strict';
/* live-mobile.js — モバイル時のみ UI をボトムシート構成に再構成する「後付け」モジュール
 *
 * 設計方針:
 *  - 既存 DOM / 既存 JS（live-alert-panel.js など）には一切手を入れない非破壊エンハンサ。
 *  - #live-alert-card が再レンダリングされるたびに MutationObserver で検知し、
 *    その中身を .sheet-scroll でラップ → 上部に .sheet-handle と .sheet-peek を付与。
 *  - #live-layer-panel は右上のフローティングボタン(FAB)から開閉するポップオーバーに。
 *  - すべて (max-width: 640px) のときだけ有効。PC幅では何もしない（CSS側で各パーツは display:none）。
 *
 * 読み込み順: 既存スクリプト群（live-main.js 等）の「後」に 1 行追加するだけ。
 *   <script src="/js/live/live-mobile.js"></script>
 */
(function () {
    const mq    = window.matchMedia('(max-width: 640px)');
    const card  = document.getElementById('live-alert-card');
    const panel = document.getElementById('live-layer-panel');
    if (!card) return;

    let fab = null, scrim = null;

    /* ── FAB と スクリム を一度だけ生成 ─────────────────────────────────── */
    function ensureChrome() {
        if (!fab) {
            fab = document.createElement('button');
            fab.id = 'live-layers-fab';
            fab.setAttribute('aria-label', 'レイヤー切替');
            fab.innerHTML =
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
                '<polygon points="12 2 22 8.5 12 15 2 8.5 12 2"></polygon>' +
                '<polyline points="2 15.5 12 22 22 15.5"></polyline></svg>' +
                '<span class="fab-count"></span>';
            document.body.appendChild(fab);

            fab.addEventListener('click', (e) => {
                e.stopPropagation();
                if (!panel) return;
                const open = panel.classList.toggle('is-open');
                fab.classList.toggle('is-active', open);
            });
            document.addEventListener('click', (e) => {
                if (mq.matches && panel && !panel.contains(e.target) && !fab.contains(e.target)) {
                    panel.classList.remove('is-open');
                    fab.classList.remove('is-active');
                }
            });
            if (panel) {
                panel.querySelectorAll('input[type="checkbox"]').forEach(cb =>
                    cb.addEventListener('change', updateFabCount));
            }
            updateFabCount();
        }
        if (!scrim) {
            scrim = document.createElement('div');
            scrim.className = 'sheet-scrim';
            document.body.appendChild(scrim);
            scrim.addEventListener('click', collapse);
        }
    }

    function updateFabCount() {
        if (!fab || !panel) return;
        const n = panel.querySelectorAll('input[type="checkbox"]:checked').length;
        const c = fab.querySelector('.fab-count');
        if (c) c.textContent = String(n);
    }

    /* ── カード中身をボトムシート構造へ再構成 ───────────────────────────── */
    function needsDecorate() {
        return mq.matches && card.children.length > 0 &&
               !card.querySelector(':scope > .sheet-scroll');
    }

    function decorate() {
        if (!needsDecorate()) return;

        // 既存の中身を .sheet-scroll に退避
        const scroll = document.createElement('div');
        scroll.className = 'sheet-scroll';
        while (card.firstChild) scroll.appendChild(card.firstChild);

        // ── peek（折りたたみ時に見える要約）を構築 ──
        // 上部のステータス行(.lac-item)からチップを生成。種別の断定はせず、本文をそのまま要約表示。
        const chips = [...scroll.querySelectorAll('.lac-item')].slice(0, 4).map(it => {
            const color = getComputedStyle(it).borderLeftColor;
            const txt   = (it.querySelector('.lac-text')?.textContent || '').trim();
            const warn  = it.classList.contains('lac-warn') || it.classList.contains('lac-urgent');
            const off   = it.classList.contains('lac-offline');
            const cls   = off ? ' is-urgent' : (warn ? ' is-warn' : '');
            return `<span class="peek-chip${cls}"><span class="dot" style="background:${color}"></span>${txt}</span>`;
        }).join('');

        const dangerN = scroll.querySelectorAll('.lac-danger-item').length;
        const updated = (scroll.querySelector('.lac-updated')?.textContent || '').trim();

        const handle = document.createElement('div');
        handle.className = 'sheet-handle';

        const peek = document.createElement('div');
        peek.className = 'sheet-peek';
        peek.innerHTML =
            `<div class="peek-chips">${chips}</div>` +
            `<div class="peek-meta"><span>危険地域 ${dangerN}件${updated ? ' ・ ' + updated : ''}</span>` +
            `<span class="peek-expand">詳細を見る ↑</span></div>`;

        card.appendChild(handle);
        card.appendChild(peek);
        card.appendChild(scroll);

        bindDrag(handle, peek);
    }

    /* ── 展開 / 折りたたみ ───────────────────────────────────────────────── */
    function expand() {
        if (!mq.matches) return;
        card.classList.add('is-expanded');
        if (scrim) scrim.classList.add('is-visible');
    }
    function collapse() {
        card.classList.remove('is-expanded');
        if (scrim) scrim.classList.remove('is-visible');
    }

    /* ── ドラッグ / タップ開閉 ──────────────────────────────────────────── */
    let bound = false;
    function bindDrag(handle, peek) {
        if (bound) return;            // ドラッグ系イベントは一度だけ登録（要素は再生成されないため handle 参照は最新を都度取得）
        bound = true;

        let startY = null, startExpanded = false, dragged = false, sheetH = 0, lastPos = 0;
        const collapsedPx = () => Math.max(sheetH - 168, 1);

        const getHandle = () => card.querySelector('.sheet-handle');
        const getPeek   = () => card.querySelector('.sheet-peek');

        function onDown(e) {
            if (!mq.matches) return;
            const t = e.target;
            if (!getHandle()?.contains(t) && !getPeek()?.contains(t)) return;
            startY = (e.touches ? e.touches[0].clientY : e.clientY);
            startExpanded = card.classList.contains('is-expanded');
            dragged = false;
            sheetH = card.offsetHeight;
            lastPos = startExpanded ? 0 : collapsedPx();
            card.classList.add('is-dragging');
        }
        function onMove(e) {
            if (startY === null) return;
            const y = (e.touches ? e.touches[0].clientY : e.clientY);
            const dy = y - startY;
            if (Math.abs(dy) > 4) dragged = true;
            const base = startExpanded ? 0 : collapsedPx();
            lastPos = Math.min(Math.max(base + dy, 0), collapsedPx());
            card.style.transform = `translateY(${lastPos}px)`;
            if (scrim) {
                scrim.classList.add('is-visible');
                scrim.style.opacity = String(0.32 * (1 - lastPos / collapsedPx()));
            }
            if (e.cancelable) e.preventDefault();
        }
        function onUp() {
            if (startY === null) return;
            card.classList.remove('is-dragging');
            card.style.transform = '';
            if (scrim) scrim.style.opacity = '';
            if (!dragged) {
                startExpanded ? collapse() : expand();
            } else {
                lastPos < collapsedPx() * 0.5 ? expand() : collapse();
            }
            startY = null;
        }

        document.addEventListener('mousedown', onDown);
        document.addEventListener('touchstart', onDown, { passive: true });
        window.addEventListener('mousemove', onMove);
        window.addEventListener('touchmove', onMove, { passive: false });
        window.addEventListener('mouseup', onUp);
        window.addEventListener('touchend', onUp);
    }

    /* ── 起動 ───────────────────────────────────────────────────────────── */
    function boot() {
        if (!mq.matches) return;
        ensureChrome();
        decorate();
    }

    // カード再レンダリング（liveAlertPanel が innerHTML を差し替える）を監視
    const obs = new MutationObserver(() => { if (needsDecorate()) decorate(); });
    obs.observe(card, { childList: true });

    // ブレークポイント跨ぎにも追従
    (mq.addEventListener ? mq.addEventListener('change', boot) : mq.addListener(boot));

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
