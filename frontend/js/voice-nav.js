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

    // ── 日本語音声選択 ───────────────────────────────────────────────────────
    let _selectedVoice = null;

    function _selectJapaneseVoice() {
        if (!window.speechSynthesis) return null;
        const voices = window.speechSynthesis.getVoices();
        if (!voices || voices.length === 0) return null;

        // 優先順位: iOS Kyoko/O-ren → Google 日本語 → Haruka → ja-JP の最初
        const preferred = ['Kyoko', 'O-ren', 'Haruka', 'Google 日本語', 'Google Japanese'];
        for (const name of preferred) {
            const v = voices.find(v => v.name.includes(name));
            if (v) {
                _selectedVoice = v;
                console.info('[Voice] selected:', v.name);
                return v;
            }
        }
        // フォールバック: lang が ja-JP の最初の音声
        const fallback = voices.find(v => v.lang === 'ja-JP') || null;
        _selectedVoice = fallback;
        console.info('[Voice] selected (fallback):', fallback?.name ?? 'none');
        return fallback;
    }

    // getVoices() は非同期で返ることがあるため voiceschanged でも初期化
    if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = () => { _selectJapaneseVoice(); };
        _selectJapaneseVoice(); // 同期で返る環境（Chrome等）向けに即実行
    }

    // ── iOS Safari 音声ロック解除 ────────────────────────────────────────────
    // iOS では speechSynthesis.speak() がユーザー操作なしにブロックされる。
    // ナビ開始ボタン押下（ユーザー操作）のタイミングで呼ぶことで解除する。
    function _unlockSpeechSynthesis() {
        if (!window.speechSynthesis) return;
        const utter = new SpeechSynthesisUtterance('');
        utter.volume = 0;
        window.speechSynthesis.speak(utter);
    }

    // ── routing.js の翻訳語 → 音声向け自然文 ────────────────────────────────
    const VOICE_TEXT_MAP = {
        '右折':                  '右に曲がります',
        '左折':                  '左に曲がります',
        '直進':                  'まっすぐ進みます',
        'やや右へ':              'やや右へ進みます',
        'やや左へ':              'やや左へ進みます',
        '右側を進む':            '右側を進みます',
        '左側を進む':            '左側を進みます',
        '鋭く右折':              '鋭く右に曲がります',
        '鋭く左折':              '鋭く左に曲がります',
        'Uターン':               '少し戻って方向を変えます',
        '合流':                  '合流します',
        '目的地に到着しました':  '避難所に到着しました。お疲れ様でした',
        '目的地は右側です':      '避難所は右側です',
        '目的地は左側です':      '避難所は左側です',
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

    // ── 距離プレフィックス生成 ───────────────────────────────────────────────
    // distanceM が null/undefined なら空文字を返す
    function _formatDistancePrefix(distanceM) {
        if (distanceM == null || !Number.isFinite(distanceM)) return '';
        const m = distanceM;
        if (m < 50)          return 'まもなく';
        if (m < 100)         return '約50m先を';
        if (m < 200)         return '約100m先を';
        if (m < 400)         return '約200m先を';
        // 400m以上は100m単位で丸め
        const rounded = Math.round(m / 100) * 100;
        return `約${rounded}m先を`;
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
        if (_selectedVoice) utter.voice = _selectedVoice;
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

        // iOS Safari 音声ロック解除（ナビ開始ボタン押下時に呼ぶ）
        unlockSpeech() { _unlockSpeechSynthesis(); },

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
        // distanceM: 現在地から次のステップまでの距離（メートル）、省略可
        announceStep(rawText, stepId, distanceM = null) {
            if (!rawText) return;
            if (_isStraight(rawText)) return;
            const voiceText = _toVoiceText(rawText);
            const prefix    = _formatDistancePrefix(distanceM);
            // 「まもなく」プレフィックスの場合は語尾を接続（「まもなく右に曲がります」）
            const spokenText = prefix === 'まもなく'
                ? `まもなく${voiceText}`
                : prefix
                    ? `${prefix}${voiceText}`
                    : voiceText;
            this.announce({
                id:          `step-${stepId}`,
                text:        spokenText,
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
                    text:        'まもなく避難所に到着します',
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
