'use strict';
// live-rain-timeline.js — 雨雲予測タイムライン UI (Phase 5-B)
// liveLayers.rain.setFrame() に依存。navigation.js / state.js には依存しない。
// 危険地域集計・キキクル判定には一切影響しない。

(function () {

    const _TIMELINE_API    = '/api/live/rain/timeline';
    const _PLAY_INTERVAL   = 500;   // ms / step

    let _frames       = [];
    let _currentIdx   = 0;
    let _playing      = false;
    let _playTimer    = null;
    let _initialized  = false;

    // DOM refs (init 後に有効)
    let _container, _slider, _playBtn, _offsetLabel, _timeLabel;

    // ── ヘルパー ─────────────────────────────────────────────────────────────

    function _fmtJmaTime(vt) {
        // "20260603013000" (UTC) → "10:30" (JST = UTC+9)
        if (!vt || vt.length < 12) return '--:--';
        const hh = (parseInt(vt.slice(8, 10), 10) + 9) % 24;
        return String(hh).padStart(2, '0') + ':' + vt.slice(10, 12);
    }

    function _offsetStr(min) {
        if (min === 0) return '現在';
        return `+${min}分`;
    }

    // ── フレーム適用 ─────────────────────────────────────────────────────────

    function _applyFrame(idx) {
        if (!_frames.length) return;
        idx = Math.max(0, Math.min(idx, _frames.length - 1));
        _currentIdx = idx;

        const frame = _frames[idx];
        if (_slider)      _slider.value         = idx;
        if (_offsetLabel) _offsetLabel.textContent = _offsetStr(frame.offset_minutes);
        if (_timeLabel)   _timeLabel.textContent  = _fmtJmaTime(frame.validtime);

        window.liveLayers?.rain?.setFrame?.(frame.tile_url_template);
    }

    // ── 再生制御 ─────────────────────────────────────────────────────────────

    function _play() {
        if (_playing || !_frames.length) return;
        _playing = true;
        if (_playBtn) _playBtn.textContent = '⏸';
        console.log('live rain timeline play');
        _playTimer = setInterval(() => {
            const next = (_currentIdx + 1) % _frames.length;
            _applyFrame(next);
        }, _PLAY_INTERVAL);
    }

    function _pause() {
        if (!_playing) return;
        _playing = false;
        if (_playBtn) _playBtn.textContent = '▶';
        console.log('live rain timeline pause');
        clearInterval(_playTimer);
        _playTimer = null;
    }

    // ── データ取得 ───────────────────────────────────────────────────────────

    async function _fetchFrames() {
        const res = await fetch(_TIMELINE_API);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        return (data.times || []).filter(t => t.offset_minutes >= 0);
    }

    // ── 公開: init ───────────────────────────────────────────────────────────

    async function init() {
        _container  = document.getElementById('live-rain-timeline');
        _slider     = document.getElementById('rain-tl-slider');
        _playBtn    = document.getElementById('rain-tl-play');
        _offsetLabel = document.getElementById('rain-tl-offset');
        _timeLabel  = document.getElementById('rain-tl-time');

        if (!_container || !_slider || !_playBtn) return;

        try {
            _frames = await _fetchFrames();
            if (!_frames.length) return;

            _slider.max   = _frames.length - 1;
            _slider.value = 0;

            console.log(`live rain timeline: frames=${_frames.length}`);
            _applyFrame(0);
            _container.classList.remove('hidden');
            _initialized = true;
        } catch (e) {
            console.warn('[live-rain-timeline] init 失敗:', e.message);
            return;
        }

        _slider.addEventListener('input', () => {
            _pause();
            _applyFrame(parseInt(_slider.value, 10));
        });

        _playBtn.addEventListener('click', () => {
            if (_playing) _pause(); else _play();
        });
    }

    // ── 公開: refresh（5分ごとの更新サイクルから呼ぶ） ─────────────────────

    async function refresh() {
        if (!_initialized) return;
        try {
            _frames = await _fetchFrames();
            if (!_frames.length) return;
            _slider.max = _frames.length - 1;
        } catch (e) {
            console.warn('[live-rain-timeline] refresh 失敗:', e.message);
            return;
        }
        _pause();
        _applyFrame(0);
    }

    window.liveRainTimeline = { init, refresh };

})();
