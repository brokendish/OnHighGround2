'use strict';

// ── 音声ナビゲーション モジュール ─────────────────────────────────────────
// 音声・文字・振動を同一ソースから同時出力する。
// voiceNav.announce(message) / announceStep() / announceApproach() を各ナビ
// イベントから呼ぶだけで動作する。音声OFFでも文字案内は常に表示される。

const voiceNav = (() => {

    // ── 設定パラメータ ───────────────────────────────────────────────────────
    const CONFIG = {
        approachDistanceMeters:    40,     // 接近予告を出す距離
        duplicateSpeechCooldownMs: 5000,   // 通常の重複発話防止（ms）
        offRouteSpeechCooldownMs:  10000,  // 逸脱警告の再発話間隔（ms）
        textDisplayDurationMs:     5000,   // 通常案内の文字表示時間（ms）
    };

    // ── 振動パターン ─────────────────────────────────────────────────────────
    const HAPTIC_PATTERNS = {
        start:       [80],               // ナビ開始: 短く1回
        approach:    [120],              // 接近予告: 短く1回
        offRoute:    [150, 80, 150],     // 逸脱: 2回、強め
        backOnRoute: [60, 60, 60],       // ルート復帰: 3回、軽め
        arrival:     [80, 60, 80, 60, 180], // 到着: 終了感
    };

    // ── 内部ステート ─────────────────────────────────────────────────────────
    const state = {
        enabled:         true,   // 音声ON/OFF（文字案内は常に動作）
        lastMessageId:   null,
        lastMessageText: null,
        lastSpokenAt:    0,
        lastCategory:    null,
        hideTimer:       null,
    };

    const hapticsState = {
        enabled:         true,   // 振動ON/OFF（音声とは独立して制御可）
        lastPatternKey:  null,
        lastVibratedAt:  0,
    };

    // ── routing.js の翻訳語 → 音声向け自然文 ────────────────────────────────
    const VOICE_TEXT_MAP = {
        '右折':                  '右に曲がってください',
        '左折':                  '左に曲がってください',
        '直進':                  'まっすぐ進んでください',
        'やや右へ':              'やや右へ進んでください',
        'やや左へ':              'やや左へ進んでください',
        '右側を進む':            '右側を進んでください',
        '左側を進む':            '左側を進んでください',
        '鋭く右折':              '鋭く右に曲がってください',
        '鋭く左折':              '鋭く左に曲がってください',
        'Uターン':               '引き返してください',
        '合流':                  '合流してください',
        '目的地に到着しました':  '目的地に到着しました',
        '目的地は右側です':      '目的地は右側です',
        '目的地は左側です':      '目的地は左側です',
    };

    // ── 直進系ステップ（発話スキップ対象）────────────────────────────────────
    const STRAIGHT_STEPS = new Set([
        '直進',
        '右側を進む', '左側を進む',
        '北へ進む', '南へ進む', '東へ進む', '西へ進む',
        '北東へ進む', '南東へ進む', '南西へ進む', '北西へ進む',
    ]);

    function _toVoiceText(rawText) {
        return VOICE_TEXT_MAP[rawText] || rawText;
    }

    function _isStraight(rawText) {
        if (!rawText) return false;
        if (STRAIGHT_STEPS.has(rawText)) return true;
        if (/を進む$/.test(rawText) && !/(右|左|折)/.test(rawText)) return true;
        return false;
    }

    // ── 重複発話チェック ─────────────────────────────────────────────────────
    function _shouldAnnounce(message) {
        if (state.lastMessageId === message.id) return false;
        const cooldown = message.category === 'warning'
            ? CONFIG.offRouteSpeechCooldownMs
            : CONFIG.duplicateSpeechCooldownMs;
        if (state.lastMessageText === message.text &&
            Date.now() - state.lastSpokenAt < cooldown) return false;
        return true;
    }

    // ── SpeechSynthesis 発話 ─────────────────────────────────────────────────
    function _speak(text) {
        if (!window.speechSynthesis || !text) return;
        window.speechSynthesis.cancel();
        const utter  = new SpeechSynthesisUtterance(text);
        utter.lang   = 'ja-JP';
        utter.rate   = 1.05;
        utter.pitch  = 1.0;
        utter.volume = 1.0;
        window.speechSynthesis.speak(utter);
    }

    // ── 振動通知 ─────────────────────────────────────────────────────────────
    // navigator.vibrate() 非対応端末（iPhone Safari 等）では静かに無効化する
    function _canVibrate() {
        return typeof navigator !== 'undefined' &&
               typeof navigator.vibrate === 'function';
    }

    // patternKey: クールダウンの識別キー
    // pattern:    振動パターン（ms配列）
    // cooldownMs: 同一キーの再振動を抑制する時間
    function _vibrate(patternKey, pattern, cooldownMs) {
        if (!hapticsState.enabled) return;
        if (!_canVibrate()) return;
        const now = Date.now();
        if (hapticsState.lastPatternKey === patternKey &&
            now - hapticsState.lastVibratedAt < cooldownMs) return;
        navigator.vibrate(pattern);
        hapticsState.lastPatternKey = patternKey;
        hapticsState.lastVibratedAt = now;
    }

    // メッセージカテゴリ/IDから振動パターンを選択して実行
    function _vibrateForMessage(message) {
        if (message.category === 'arrival') {
            _vibrate('arrival', HAPTIC_PATTERNS.arrival, 15000);
        } else if (message.category === 'warning') {
            _vibrate('off-route', HAPTIC_PATTERNS.offRoute, 10000);
        } else if (message.id === 'nav-start') {
            _vibrate('nav-start', HAPTIC_PATTERNS.start, 5000);
        } else if (message.id === 'nav-back-on-route') {
            _vibrate('nav-back-on-route', HAPTIC_PATTERNS.backOnRoute, 5000);
        } else if (message.id && message.id.startsWith('pre-')) {
            // 接近予告（pre-xxxxx）: stepId 単位でクールダウン
            _vibrate(`approach-${message.id}`, HAPTIC_PATTERNS.approach, 5000);
        }
    }

    // ── テキスト案内バー更新 ─────────────────────────────────────────────────
    function _updateDisplay(message) {
        const bar  = document.getElementById('nav-announcement-bar');
        const span = document.getElementById('nav-announcement-text');
        if (!bar || !span) return;

        span.textContent     = message.displayText || message.text;
        bar.dataset.category = message.category || 'maneuver';
        bar.style.display    = 'flex';

        if (state.hideTimer) { clearTimeout(state.hideTimer); state.hideTimer = null; }
        if (message.category !== 'warning' && message.category !== 'arrival') {
            state.hideTimer = setTimeout(
                () => { bar.style.display = 'none'; },
                CONFIG.textDisplayDurationMs
            );
        }
    }

    // ── 公開API ──────────────────────────────────────────────────────────────
    return {

        get enabled()  { return state.enabled; },
        get config()   { return CONFIG; },

        // 汎用アナウンス（ナビ開始・逸脱・到着など）
        announce(message) {
            if (!message || !message.text) return;
            if (!_shouldAnnounce(message)) return;

            _updateDisplay(message);
            if (state.enabled) _speak(message.text);
            _vibrateForMessage(message);   // 音声ON/OFFに関わらず振動は独立動作

            state.lastMessageId   = message.id;
            state.lastMessageText = message.text;
            state.lastSpokenAt    = Date.now();
            state.lastCategory    = message.category || null;
        },

        // ステップ変化時（routing.js から呼ぶ）
        announceStep(rawText, stepId) {
            if (!rawText) return;
            if (_isStraight(rawText)) return;
            const voiceText = _toVoiceText(rawText);
            this.announce({
                id:          `step-${stepId}`,
                text:        voiceText,
                displayText: rawText,
                category:    'maneuver',
                priority:    'normal',
            });
        },

        // 接近予告（曲がり角の手前で "まもなく〇〇" と予告）
        announceApproach(rawText, stepId) {
            if (!rawText) return;
            if (_isStraight(rawText)) return;
            // 目的地系ステップは専用の文言で予告する
            const isDestination = /目的地/.test(rawText);
            if (isDestination) {
                this.announce({
                    id:          `pre-${stepId}`,
                    text:        'まもなく目的地です',
                    displayText: 'まもなく目的地です',
                    category:    'maneuver',
                    priority:    'normal',
                });
                return;
            }
            const voiceText = _toVoiceText(rawText);
            this.announce({
                id:          `pre-${stepId}`,
                text:        `まもなく${voiceText}`,
                displayText: `まもなく: ${rawText}`,
                category:    'maneuver',
                priority:    'normal',
            });
        },

        // 音声ON/OFFトグル（文字案内は常に動作）
        setEnabled(val) {
            state.enabled = !!val;
            const btn = document.getElementById('voice-nav-toggle-btn');
            if (btn) btn.classList.toggle('map-overlay-btn--active', state.enabled);
            if (!val && window.speechSynthesis) window.speechSynthesis.cancel();
        },

        // 振動ON/OFFトグル（音声・文字とは独立）
        haptics: {
            get enabled() { return hapticsState.enabled; },
            setEnabled(val) {
                hapticsState.enabled = !!val;
                if (!val && _canVibrate()) navigator.vibrate(0); // 振動を即停止
            },
        },

        // ナビ停止時にリセット
        clear() {
            const bar = document.getElementById('nav-announcement-bar');
            if (bar) bar.style.display = 'none';
            if (state.hideTimer) { clearTimeout(state.hideTimer); state.hideTimer = null; }
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            if (_canVibrate()) navigator.vibrate(0);
            state.lastMessageId   = null;
            state.lastMessageText = null;
            state.lastCategory    = null;
        },
    };
})();
