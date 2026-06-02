'use strict';
// live-gesture.js — ダブルタップ + 上下スワイプでズーム変更
// liveMap に依存。navigation.js / state.js には依存しない。
//
// 操作: 2 回目のタップを押し続けたまま上下にドラッグ
//   上方向 → ズームイン  /  下方向 → ズームアウト
//
// ダブルタップのみ（ドラッグなし）→ Leaflet デフォルトのダブルタップズームをそのまま使用。

(function () {

    const container = liveMap.getContainer();

    const TAP_MS      = 300;  // ダブルタップ判定間隔 (ms)
    const TAP_PX      = 60;   // ダブルタップ判定半径 (px)
    const DRAG_MIN_PX = 8;    // スワイプ開始と見なす最小移動量 (px)
    const PX_PER_ZOOM = 80;   // 1 ズームレベル変化に必要な移動量 (px)

    let _lastTime = 0;
    let _lastX    = 0;
    let _lastY    = 0;

    let _active    = false;
    let _startY    = 0;
    let _startZoom = 0;
    let _moved     = false;
    let _touchId   = null;

    // ── タッチ開始 ──────────────────────────────────────────────────────────

    container.addEventListener('touchstart', (e) => {
        if (e.touches.length !== 1) { _cancel(); return; }

        const t   = e.touches[0];
        const now = Date.now();
        const dx  = Math.abs(t.clientX - _lastX);
        const dy  = Math.abs(t.clientY - _lastY);

        if (now - _lastTime < TAP_MS && dx < TAP_PX && dy < TAP_PX) {
            // ダブルタップ検出 → ドラッグズームモード開始
            _active    = true;
            _startY    = t.clientY;
            _startZoom = liveMap.getZoom();
            _moved     = false;
            _touchId   = t.identifier;
            liveMap.dragging.disable();
        }

        _lastTime = now;
        _lastX    = t.clientX;
        _lastY    = t.clientY;
    }, { passive: true });

    // ── タッチ移動 ──────────────────────────────────────────────────────────

    container.addEventListener('touchmove', (e) => {
        if (!_active) return;

        let t = null;
        for (let i = 0; i < e.touches.length; i++) {
            if (e.touches[i].identifier === _touchId) { t = e.touches[i]; break; }
        }
        if (!t) return;

        const delta = t.clientY - _startY;
        if (Math.abs(delta) < DRAG_MIN_PX) return;

        _moved = true;
        // 上方向 (delta < 0) → ズームイン、下方向 (delta > 0) → ズームアウト
        const z = _startZoom - delta / PX_PER_ZOOM;
        liveMap.setZoom(Math.max(1, Math.min(19, z)), { animate: false });

        if (e.cancelable) e.preventDefault();
    }, { passive: false });

    // ── タッチ終了 ──────────────────────────────────────────────────────────

    container.addEventListener('touchend', () => {
        if (_active && _moved) {
            // ドラッグした場合は後続の dblclick（Leaflet タップズーム）を 1 回だけ抑制
            const block = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
            container.addEventListener('dblclick', block, { capture: true, once: true });
            setTimeout(() => {
                container.removeEventListener('dblclick', block, { capture: true });
            }, 400);
        }
        _cancel();
    }, { passive: true });

    container.addEventListener('touchcancel', _cancel, { passive: true });

    function _cancel() {
        if (_active) liveMap.dragging.enable();
        _active = false;
        _moved  = false;
    }

})();
