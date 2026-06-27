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
 * スナップ段階: peek（折りたたみ168px）/ half（画面高50%）/ full（全展開）
 *
 * 読み込み順: 既存スクリプト群（live-main.js 等）の「後」に 1 行追加するだけ。
 *   <script src="/js/live/live-mobile.js"></script>
 */
(function () {
    /* ── 定数 ─────────────────────────────────────────────────────────────── */
    const SNAP_VEL_THRESHOLD  = 0.3;   // px/ms: これ以上の速度でフリックと判定
    const HALF_VIEWPORT_RATIO = 0.50;  // half スナップ = ビューポート高の 50%
    const PEEK_HEIGHT_PX      = 168;   // peek 時の表示高 (px)

    const mq    = window.matchMedia('(max-width: 640px)');
    const card  = document.getElementById('live-alert-card');
    const panel = document.getElementById('live-layer-panel');
    if (!card) return;

    let fab = null, scrim = null, _restoreBtn = null;

    /* ── CSS変数 --sheet-half をカード実測高から更新 ─────────────────────── */
    /* visualViewport.height は iOS Safari でアドレスバー高を除いた実可視高を返す */
    function _vph() { return window.visualViewport?.height ?? window.innerHeight; }

    function updateHalfVar() {
        const h = card.offsetHeight;
        const t = Math.max(h - Math.round(_vph() * HALF_VIEWPORT_RATIO), 0);
        card.style.setProperty('--sheet-half', `${t}px`);
    }

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
        if (!_restoreBtn) {
            _restoreBtn = document.createElement('button');
            _restoreBtn.id = 'live-sheet-restore';
            _restoreBtn.setAttribute('aria-label', '情報パネルを表示');
            _restoreBtn.innerHTML =
                '<svg viewBox="0 0 24 24" width="14" height="14" fill="none"' +
                ' stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
                '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>' +
                '情報';
            document.body.appendChild(_restoreBtn);
            _restoreBtn.addEventListener('click', _restoreSheet);
        }
    }

    function updateFabCount() {
        if (!fab || !panel) return;
        const n = panel.querySelectorAll('input[type="checkbox"]:checked').length;
        const c = fab.querySelector('.fab-count');
        if (c) c.textContent = String(n);
    }

    /* ── スナップ状態 ────────────────────────────────────────────────────── */
    function currentSnapName() {
        if (card.classList.contains('is-expanded')) return 'full';
        if (card.classList.contains('is-half'))     return 'half';
        return 'peek';
    }

    /* snapTo: スナップ確定の単一エントリポイント。CSS クラスを付け替え、地図をパンする */
    function snapTo(name) {
        card.classList.remove('is-expanded', 'is-half');
        if (name === 'full') {
            card.classList.add('is-expanded');
            if (scrim) scrim.classList.add('is-visible');
        } else if (name === 'half') {
            updateHalfVar();
            card.classList.add('is-half');
            if (scrim) scrim.classList.add('is-visible');
        } else {
            if (scrim) scrim.classList.remove('is-visible');
        }
        _panMapForSnap(name);
    }

    /* ── 地図パン: シート可視高に合わせ選択地点を可視領域中央へ移動 ──────── */
    function _panMapForSnap(snapName) {
        const map = window.liveMap;
        if (!map) return;
        const sel = window.liveLayers?.earthquake?.getSelected?.();
        if (!sel || sel.lat == null || sel.lng == null) return;

        const vph = _vph();
        const sheetVisH = snapName === 'full' ? card.offsetHeight
                        : snapName === 'half' ? vph * HALF_VIEWPORT_RATIO
                        : PEEK_HEIGHT_PX;

        const visMapH = vph - sheetVisH;
        if (visMapH < 80) return;

        const pt = map.latLngToContainerPoint(L.latLng(sel.lat, sel.lng));
        const targetY = visMapH / 2;
        const dy = pt.y - targetY;
        if (Math.abs(dy) < 20) return;

        map.panBy([0, dy], { animate: true, duration: 0.34 });
    }

    /* ── シート全体を閉じる / 復元 ───────────────────────────────────────── */
    function _closeSheet() {
        card.classList.add('is-sheet-closed');
        card.classList.remove('is-expanded', 'is-half');
        if (scrim) scrim.classList.remove('is-visible');
        if (_restoreBtn) _restoreBtn.classList.add('is-visible');
    }
    function _restoreSheet() {
        card.classList.remove('is-sheet-closed');
        if (_restoreBtn) _restoreBtn.classList.remove('is-visible');
    }

    /* scrim クリックなどの後方互換ラッパー */
    function expand()   { snapTo('full'); }
    function collapse() { snapTo('peek'); }

    /* ── カード中身をボトムシート構造へ再構成 ───────────────────────────── */
    function needsDecorate() {
        return mq.matches && card.children.length > 0 &&
               !card.querySelector(':scope > .sheet-scroll');
    }

    let _initialSnap = true;

    function decorate() {
        if (!needsDecorate()) return;

        // 既存の中身を .sheet-scroll に退避
        const scroll = document.createElement('div');
        scroll.className = 'sheet-scroll';
        while (card.firstChild) scroll.appendChild(card.firstChild);

        // ── peek（折りたたみ時に見える要約）を構築 ──
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

        const closeBtn = document.createElement('button');
        closeBtn.className = 'sheet-close-btn';
        closeBtn.setAttribute('aria-label', 'パネルを閉じる');
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            _closeSheet();
        });
        handle.appendChild(closeBtn);

        const peek = document.createElement('div');
        peek.className = 'sheet-peek';
        peek.innerHTML =
            `<div class="peek-chips">${chips}</div>` +
            `<div class="peek-meta"><span>危険地域 ${dangerN}件${updated ? ' ・ ' + updated : ''}</span>` +
            `<span class="peek-expand">詳細を見る ↑</span></div>`;

        card.appendChild(handle);
        card.appendChild(peek);
        card.appendChild(scroll);

        bindDrag();

        // 初回コンテンツ表示時のみ half スナップへ（再レンダリング時は現状維持）
        if (_initialSnap) {
            _initialSnap = false;
            setTimeout(() => { if (mq.matches) snapTo('half'); }, 50);
        }
    }

    /* ── ドラッグ / タップ開閉 ──────────────────────────────────────────── */
    let bound = false;
    function bindDrag() {
        if (bound) return;
        bound = true;

        let startY     = null;
        let startPos   = 0;
        let dragged    = false;
        let sheetH     = 0;
        let lastPos    = 0;
        let _velY      = 0;
        let _prevMoveT = 0;
        let _prevMoveY = 0;

        const peekPx = () => Math.max(sheetH - PEEK_HEIGHT_PX, 1);
        const halfPx = () => Math.max(sheetH - Math.round(_vph() * HALF_VIEWPORT_RATIO), 0);

        const getHandle = () => card.querySelector('.sheet-handle');
        const getPeek   = () => card.querySelector('.sheet-peek');

        function onDown(e) {
            if (!mq.matches) return;
            if (card.classList.contains('is-sheet-closed')) return;
            const t = e.target;
            if (t.closest('.sheet-close-btn')) return;
            if (!getHandle()?.contains(t) && !getPeek()?.contains(t)) return;

            sheetH   = card.offsetHeight;
            startY   = (e.touches ? e.touches[0].clientY : e.clientY);
            const snap = currentSnapName();
            startPos = snap === 'full' ? 0
                     : snap === 'half' ? halfPx()
                     : peekPx();
            lastPos  = startPos;
            dragged  = false;
            _velY    = 0;
            _prevMoveT = performance.now();
            _prevMoveY = startY;
            card.classList.add('is-dragging');
        }

        function onMove(e) {
            if (startY === null) return;
            const y  = (e.touches ? e.touches[0].clientY : e.clientY);
            const dy = y - startY;
            if (Math.abs(dy) > 4) dragged = true;

            const now = performance.now();
            const dt  = now - _prevMoveT;
            if (dt > 0) _velY = (y - _prevMoveY) / dt; // px/ms (正=下方向)
            _prevMoveT = now;
            _prevMoveY = y;

            lastPos = Math.min(Math.max(startPos + dy, 0), peekPx());
            card.style.transform = `translateY(${lastPos}px)`;
            if (scrim) {
                scrim.classList.add('is-visible');
                scrim.style.opacity = String(0.32 * (1 - lastPos / peekPx()));
            }
            if (e.cancelable) e.preventDefault();
        }

        function onUp() {
            if (startY === null) return;
            card.classList.remove('is-dragging');
            card.style.transform = '';
            if (scrim) scrim.style.opacity = '';

            const vel = _velY;
            _velY      = 0;
            _prevMoveT = 0;

            if (!dragged) {
                // タップ: peek → half、それ以外 → peek
                snapTo(currentSnapName() === 'peek' ? 'half' : 'peek');
            } else {
                const snaps = [
                    { name: 'full', px: 0        },
                    { name: 'half', px: halfPx() },
                    { name: 'peek', px: peekPx() },
                ];
                const nearest = snaps.reduce((a, b) =>
                    Math.abs(b.px - lastPos) < Math.abs(a.px - lastPos) ? b : a);

                if (Math.abs(vel) > SNAP_VEL_THRESHOLD) {
                    // フリック: 速度方向に1段送り（下=peek方向、上=full方向）
                    const dir     = vel > 0 ? 1 : -1;
                    const curIdx  = snaps.indexOf(nearest);
                    const nextIdx = Math.min(Math.max(curIdx + dir, 0), snaps.length - 1);
                    snapTo(snaps[nextIdx].name);
                } else {
                    // ゆっくりドラッグ: 最寄りスナップに確定
                    snapTo(nearest.name);
                }
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

    /* ── ビューポートリサイズ（アドレスバー伸縮・画面回転）対応 ─────────── */
    function _onViewportResize() {
        if (card.classList.contains('is-half')) updateHalfVar();
    }
    window.addEventListener('resize', _onViewportResize);
    // iOS Safari のアドレスバー伸縮は visualViewport の resize で通知される
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', _onViewportResize);
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
