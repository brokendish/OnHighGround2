'use strict';

// ── 音声ナビゲーション モジュール ─────────────────────────────────────────
// 音声と文字を同一ソースから同時出力する。
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

    // ── 内部ステート ─────────────────────────────────────────────────────────
    const state = {
        enabled:         true,   // 音声ON/OFF（文字案内は常に動作）
        lastMessageId:   null,
        lastMessageText: null,
        lastSpokenAt:    0,
        lastCategory:    null,
        hideTimer:       null,
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
    // 曲がり・逸脱・到着以外の "そのまま進む" 系はスキップする
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
        // "を進む" 系（"道路名を進む" 等）もスキップ
        if (/を進む$/.test(rawText) && !/(右|左|折)/.test(rawText)) return true;
        return false;
    }

    // ── 重複発話チェック ─────────────────────────────────────────────────────
    // カテゴリ別クールダウンを適用する
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

    // ── テキスト案内バー更新 ─────────────────────────────────────────────────
    function _updateDisplay(message) {
        const bar  = document.getElementById('nav-announcement-bar');
        const span = document.getElementById('nav-announcement-text');
        if (!bar || !span) return;

        span.textContent     = message.displayText || message.text;
        bar.dataset.category = message.category || 'maneuver';
        bar.style.display    = 'flex';

        // 警告・到着は手動クリアまで表示継続。それ以外は設定時間後に自動非表示
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
        get config()   { return CONFIG; },          // テスト・デバッグ用

        // 汎用アナウンス（ナビ開始・逸脱・到着など）
        announce(message) {
            if (!message || !message.text) return;
            if (!_shouldAnnounce(message)) return;

            _updateDisplay(message);
            if (state.enabled) _speak(message.text);

            state.lastMessageId   = message.id;
            state.lastMessageText = message.text;
            state.lastSpokenAt    = Date.now();
            state.lastCategory    = message.category || null;
        },

        // ステップ変化時（routing.js から呼ぶ）
        // rawText: "左折" / "右折" / "直進" 等
        // 直進系はスキップ。曲がり系のみ発話する。
        announceStep(rawText, stepId) {
            if (!rawText) return;
            if (_isStraight(rawText)) return;   // 直進・方角系はスキップ
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
        // 直進系・方角系はスキップ。逸脱中はスキップ（呼び出し側で制御）。
        announceApproach(rawText, stepId) {
            if (!rawText) return;
            if (_isStraight(rawText)) return;   // 直進系はスキップ
            const voiceText = _toVoiceText(rawText);
            this.announce({
                id:          `pre-${stepId}`,
                text:        `まもなく${voiceText}`,
                displayText: `まもなく: ${rawText}`,
                category:    'maneuver',
                priority:    'normal',
            });
        },

        // 音声ON/OFFトグル
        setEnabled(val) {
            state.enabled = !!val;
            const btn = document.getElementById('voice-nav-toggle-btn');
            if (btn) btn.classList.toggle('map-overlay-btn--active', state.enabled);
            if (!val && window.speechSynthesis) window.speechSynthesis.cancel();
        },

        // ナビ停止時に案内バーをリセット
        clear() {
            const bar = document.getElementById('nav-announcement-bar');
            if (bar) bar.style.display = 'none';
            if (state.hideTimer) { clearTimeout(state.hideTimer); state.hideTimer = null; }
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            state.lastMessageId   = null;
            state.lastMessageText = null;
            state.lastCategory    = null;
        },
    };
})();
