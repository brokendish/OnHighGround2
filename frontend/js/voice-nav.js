'use strict';

// ── 音声ナビゲーション モジュール ─────────────────────────────────────────
// 音声と文字を同一ソースから同時出力する。
// voiceNav.announce(message) / announceStep() / announceApproach() を各ナビ
// イベントから呼ぶだけで動作する。音声OFFでも文字案内は常に表示される。

const voiceNav = (() => {

    // ── 内部ステート ─────────────────────────────────────────────────────────
    const state = {
        enabled:         true,   // 音声ON/OFF（文字案内は常に動作）
        lastMessageId:   null,
        lastMessageText: null,
        lastSpokenAt:    0,
        hideTimer:       null,
    };

    // ── routing.js の翻訳語 → 音声向け自然文 ────────────────────────────────
    // translateInstructionToJapanese() の出力を音声で読みやすい形に変換する
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
        'Uターン':               'Uターンしてください',
        '合流':                  '合流してください',
        '目的地に到着しました':  '目的地に到着しました',
        '目的地は右側です':      '目的地は右側です',
        '目的地は左側です':      '目的地は左側です',
    };

    function _toVoiceText(rawText) {
        // 方角系（"北へ進む" 等）はそのまま読める
        return VOICE_TEXT_MAP[rawText] || rawText;
    }

    // ── 重複発話チェック ─────────────────────────────────────────────────────
    function _shouldAnnounce(message) {
        if (state.lastMessageId === message.id) return false;
        if (state.lastMessageText === message.text &&
            Date.now() - state.lastSpokenAt < 5000) return false;
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

        span.textContent    = message.displayText || message.text;
        bar.dataset.category = message.category || 'maneuver';
        bar.style.display    = 'flex';

        // 警告・到着は手動クリアまで表示継続。それ以外は 5 秒後に自動非表示
        if (state.hideTimer) { clearTimeout(state.hideTimer); state.hideTimer = null; }
        if (message.category !== 'warning' && message.category !== 'arrival') {
            state.hideTimer = setTimeout(() => { bar.style.display = 'none'; }, 5000);
        }
    }

    // ── 公開API ──────────────────────────────────────────────────────────────
    return {

        get enabled() { return state.enabled; },

        // 汎用アナウンス（ナビ開始・逸脱・到着など）
        announce(message) {
            if (!message || !message.text) return;
            if (!_shouldAnnounce(message)) return;

            _updateDisplay(message);
            if (state.enabled) _speak(message.text);

            state.lastMessageId   = message.id;
            state.lastMessageText = message.text;
            state.lastSpokenAt    = Date.now();
        },

        // ステップ変化時（routing.js から呼ぶ）
        // rawText: "左折" / "右折" / "直進" 等の短縮語
        announceStep(rawText, stepId) {
            if (!rawText) return;
            const voiceText = _toVoiceText(rawText);
            this.announce({
                id:          `step-${stepId}`,
                text:        voiceText,
                displayText: rawText,   // 表示は短い語のまま
                category:    'maneuver',
                priority:    'normal',
            });
        },

        // 接近通知（曲がり角の手前で "まもなく〇〇" と予告）
        announceApproach(rawText, stepId) {
            // 直進は予告不要
            if (!rawText || rawText === '直進' || rawText === 'まっすぐ進んでください') return;
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
        },
    };
})();
